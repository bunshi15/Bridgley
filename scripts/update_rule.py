import json
import os
import re
import sys
from pathlib import Path

import requests

API = "https://api.cloudflare.com/client/v4"

def _headers():
    token = os.environ["CF_API_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def smoke_test(zone_id: str):
    url = f"{API}/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint"
    r = requests.get(url, headers=_headers(), timeout=30)
    print("status:", r.status_code)
    print("body:", r.text[:500])
    try:
        r.raise_for_status()
    except requests.HTTPError:
        print("status:", r.status_code)
        print(r.text[:800])
        sys.exit(2)

def redact_url(url: str) -> str:
    # маскируем UUID/hex-похожие куски в URL
    return re.sub(r"([0-9a-f]{8,})", "***", url, flags=re.IGNORECASE)

def patch_rule(zone_id: str, ruleset_id: str, rule_id: str, *, expression: str, enabled: bool = True) -> dict:
    url = f"{API}/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}"
    payload = {
        "action": "block",
        "expression": expression,
        "enabled": enabled,
    }
    r = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        print("status:", r.status_code)
        print(r.text[:800])
        sys.exit(2)
    return r.json()["result"]

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def update_block_security_from_seen(seen_path: Path, cfg_path: Path) -> dict:
    """
    Обновляет rules/block_security.json на основании reports/seen_paths.txt
    Не добавляет каждый путь — только "сжатые" паттерны (директории/расширения/точные).
    """
    cfg = load_json(cfg_path) or {}

    contains = set(cfg.get("contains", []))
    ends_with = set(cfg.get("ends_with", []))
    exact = set(cfg.get("exact", []))


    # Базовые паттерны, которые почти всегда полезны для FastAPI проекта
    contains |= {"/wp-", "phpmyadmin", "/bak/", "/old/", "/backup", "/cgi-bin/"}
    ends_with |= {".php", ".sql", ".zip", ".rar", ".tar", ".gz", ".7z", ".env"}

    # Агрегируем из seen_paths
    if seen_path.exists():
        for raw in seen_path.read_text(encoding="utf-8").splitlines():
            p = raw.strip()
            if not p:
                continue

            p_norm = "/" + p.lstrip("/")
            p_norm_lower = p_norm.lower()

            for ext in (".php", ".sql", ".zip", ".rar", ".tar", ".gz", ".7z", ".env"):
                if p_norm_lower.endswith(ext):
                    ends_with.add(ext)

            if "/wp-" in p_norm_lower or p_norm_lower.startswith("/wp-"):
                contains.add("/wp-")
            if p_norm_lower.startswith("/wp-admin/"):
                contains.add("/wp-admin/")
            if p_norm_lower.startswith("/wp-content/"):
                contains.add("/wp-content/")
            if p_norm_lower.startswith("/wp-includes/"):
                contains.add("/wp-includes/")
            if p_norm_lower.startswith("/vendor/"):
                contains.add("/vendor/")
            if p_norm_lower.startswith("/uploads/"):
                contains.add("/uploads/")
            if p_norm_lower.startswith("/cgi-bin/"):
                contains.add("/cgi-bin/")

            if p_norm_lower == "/xmlrpc.php":
                exact.add("/xmlrpc.php")
            if p_norm_lower == "/wp-login.php":
                exact.add("/wp-login.php")

    new_cfg = {
        "contains": sorted(contains),
        "ends_with": sorted(ends_with),
    }
    if exact:
        new_cfg["exact"] = sorted(exact)

    save_json(cfg_path, new_cfg)
    return new_cfg

def build_expr():
    cfg_path = Path(__file__).resolve().parent.parent / "rules" / "block_security.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    parts = []

    for val in cfg.get("exact", []):
        parts.append(f'(http.request.uri.path eq "{val}")')

    for val in cfg.get("contains", []):
        parts.append(f'(http.request.uri.path contains "{val}")')

    for val in cfg.get("ends_with", []):
        parts.append(f'(http.request.uri.path ends_with "{val}")')

    return " or ".join(parts)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    cfg_path = root / "rules" / "block_security.json"
    seen_path = root / "reports" / "seen_paths.txt"

    if "--update-config-from-seen" in sys.argv:
        cfg = update_block_security_from_seen(seen_path, cfg_path)
        print(f"Updated {cfg_path} from {seen_path}")
        print("contains:", len(cfg.get("contains", [])))
        print("ends_with:", len(cfg.get("ends_with", [])))
        print("exact:", len(cfg.get("exact", [])))

    if "--push" not in sys.argv:
        sys.exit(0)

    zone_id = os.environ["CF_ZONE_ID"]
    ruleset_id = os.environ["CF_RULESET_ID"]
    rule_id = os.environ["CF_RULE_ID"]

    smoke_test(zone_id)
    expr = build_expr()

    try:
        updated = patch_rule(zone_id, ruleset_id, rule_id, expression=expr, enabled=True)
        print("Updated rule OK")
        print("Expression length:", len(updated["expression"]))
    except requests.HTTPError as e:
        # скрываем id в URL
        url = getattr(e.response, "url", "")
        code = getattr(e.response, "status_code", "?")
        print(f"HTTPError {code} on {redact_url(url)}")
        # можно распечатать тело (оно обычно без id)
        try:
            print(e.response.text)
        except Exception:
            pass
        raise