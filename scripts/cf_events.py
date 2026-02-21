import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


SUSPICIOUS_EXT = {".sql", ".zip", ".rar", ".tar", ".gz", ".7z", ".env", ".php"}
WATCH_PATH_PREFIXES = (
    "/webhook",
    "/webhooks",
    "/admin",
    "/bot-admin",
    "/internal",
)
WATCH_PATH_EXACT = (
    "/metrics",
    "/health",
    "/health/detailed",
    "/docs",
    "/redoc",
    "/openapi.json",
)
CRITICAL_PATHS = ("/webhooks", "/webhook")
SENSITIVE_PATHS = ("/admin", "/bot-admin", "/internal")
OBSERVABILITY_PATHS = ("/metrics", "/health")


def parse_dt(dt_str: str):
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def top(counter, n=20):
    return [{"value": k, "count": v} for k, v in counter.most_common(n)]


def report(json_path: str, seen_path: str, output_path: str) -> None:

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    c_action = Counter()
    c_rule = Counter()
    c_src = Counter()
    c_path = Counter()
    c_ip = Counter()
    c_asn = Counter()
    c_cc = Counter()
    suspicious_ext = Counter()
    watch_hits = Counter()  # path -> count
    watch_hits_by_ip = Counter()  # (path, ip) -> count
    watch_samples = {}  # path -> one sample record

    uniq = set()
    per_minute = defaultdict(int)
    dts = []


    for r in data:
        ip = r.get("clientIP", "")
        method = r.get("clientRequestHTTPMethodName", "")
        path = r.get("clientRequestPath", "")

        uniq.add((ip, method, path))

        c_action[r.get("action", "")] += 1
        c_rule[r.get("ruleId", "")] += 1
        c_src[r.get("source", "")] += 1
        c_path[path] += 1
        c_ip[ip] += 1

        asn = f'{r.get("clientAsn","")} {r.get("clientASNDescription","")}'.strip()
        c_asn[asn] += 1
        c_cc[r.get("clientCountryName", "")] += 1

        for ext in SUSPICIOUS_EXT:
            if path.endswith(ext):
                suspicious_ext[ext] += 1

        dt_str = r.get("datetime")
        if dt_str:
            dt = parse_dt(dt_str)
            dts.append(dt)
            per_minute[dt.strftime("%Y-%m-%d %H:%M")] += 1

        # --- WATCHLIST detection ---
        # ignore obvious PHP scan noise for watchlist (FastAPI app)
        if not path.endswith(".php"):
            is_watch = (path in WATCH_PATH_EXACT) or any(
                path.startswith(pfx) for pfx in WATCH_PATH_PREFIXES
            )

            if is_watch and path:
                watch_hits[path] += 1
                watch_hits_by_ip[(path, ip)] += 1
                watch_samples.setdefault(
                    path,
                    {
                        "datetime": r.get("datetime"),
                        "ip": ip,
                        "country": r.get("clientCountryName"),
                        "asn": r.get("clientAsn"),
                        "asn_desc": r.get("clientASNDescription"),
                        "action": r.get("action"),
                        "ruleId": r.get("ruleId"),
                        "source": r.get("source"),
                        "ua": r.get("userAgent"),
                        "host": r.get("clientRequestHTTPHost"),
                        "method": method,
                    },
                )


    peak = max(per_minute.values()) if per_minute else 0

    # --- seen paths ---
    seen = set()
    if Path(seen_path).exists():
        with open(seen_path, "r", encoding="utf-8") as f:
            seen = {x.strip() for x in f if x.strip()}

    paths = {r.get("clientRequestPath", "") for r in data if r.get("clientRequestPath")}
    new_paths = sorted(p for p in paths if p not in seen)

    with open(seen_path, "w", encoding="utf-8") as f:
        for p in sorted(seen | paths):
            f.write(p + "\n")

    # --- result ---
    alerts = []
    for item in top(watch_hits, 50):
        p = item["value"]
        # топ IP по этому пути
        ip_top = []
        for (pp, ip), cnt in watch_hits_by_ip.most_common(200):
            if pp == p:
                ip_top.append({"ip": ip, "count": cnt})
            if len(ip_top) >= 10:
                break
        severity = "info"
        if p.startswith(CRITICAL_PATHS):
            severity = "critical"
        elif p.startswith(SENSITIVE_PATHS):
            severity = "high"
        elif p in OBSERVABILITY_PATHS:
            severity = "medium"

        alerts.append({
            "path": p,
            "count": item["count"],
            "severity": severity,
            "top_ips": ip_top,
            "sample": watch_samples.get(p),
        })


    result = {
        "totals": {
            "records": len(data),
            "unique": len(uniq),
            "peak_per_minute": peak,
            "actions": top(c_action),
            "ruleId": top(c_rule),
            "source": top(c_src),
            "countries": top(c_cc),
            "ASN_top": top(c_asn),
            "IP_top": top(c_ip),
            "PATH_top": top(c_path, 30),
            "suspicious_extensions": top(suspicious_ext),
            "version": "1.2",
        },
        "alerts": {
            "watchlist_total_hits": sum(watch_hits.values()),
            "watchlist_unique_paths": len(watch_hits),
            "watchlist": alerts,
        },
        "date_from": min(dts).isoformat() if dts else None,
        "date_to": max(dts).isoformat() if dts else None,
        "new_paths_count": len(new_paths),
    }


    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Processed {len(data)} records")
    print(f"Unique triplets: {len(uniq)}")
    print(f"Peak per minute: {peak}")
    print(f"New paths: {len(new_paths)}")
    if watch_hits:
        print("\n[ALERT] Watchlist paths were hit:")
        for x in top(watch_hits, 20):
            print(f"  {x['count']:>6}  {x['value']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/cf_evets.py <json_path>")
        sys.exit(1)

    json_path = sys.argv[1]

    output_path = str(
        Path(__file__).resolve().parent.parent / "reports" / "report.json"
    )
    seen_path = str(
        Path(__file__).resolve().parent.parent / "reports" / "seen_paths.txt"
    )

    report(json_path, seen_path, output_path)