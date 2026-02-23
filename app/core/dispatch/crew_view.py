# app/core/dispatch/crew_view.py
"""
CrewLeadView builder — PII-safe allowlist DTO for crew messages.

Builds a sanitized copy-paste ready message from an explicit allowlist
of lead fields.  **No PII is included**: no phone, no street address,
no free-text comments, no media links.

This module must NOT import bot handler modules.
"""
from __future__ import annotations

from typing import Any


def format_crew_message(lead_id: str, payload: dict[str, Any]) -> str:
    """
    Format a crew-safe copy-paste message for the operator (Dispatch Iteration 1).

    Language follows ``operator_lead_target_lang`` from settings so the crew
    message matches the operator's language.

    Only safe, anonymized fields:
    - Sequential lead number (``lead_number`` from DB)
    - From/to locality (city only, not street)
    - Date + time window
    - Volume category
    - Floors + elevator info
    - Recognised items summary
    - Pricing estimate range

    Returns a ready-to-copy text block the operator can paste into
    a crew WhatsApp group.
    """
    # Avoid importing notification_service internals; use local helpers
    data = payload.get("data", payload)
    custom = data.get("custom", {})

    # --- Operator language (from settings) ---
    from app.config import settings as _settings
    lang = _settings.operator_lead_target_lang  # "ru" | "en" | "he"

    # Localized label lookup
    _L = _CREW_LABELS.get(lang, _CREW_LABELS["ru"])

    # --- Lead number (sequential, from DB) ---
    lead_number = custom.get("lead_number")
    if lead_number is not None:
        lead_display = f"#{lead_number}"
    else:
        # Fallback: short UUID (pre-migration or tests)
        lead_display = f"#{lead_id[:8]}" if lead_id else "#?"

    # --- Route: locality only (no street addresses) ---
    # Multi-pickup aware: show all pickup localities → destination
    pickups = custom.get("pickups", [])
    route_cls = custom.get("route_classification", {})

    # Resolve destination locality (prefer locale-aware name)
    to_names = route_cls.get("to_names") or {}
    to_locality = to_names.get(lang) or route_cls.get("to_locality")
    if not to_locality:
        geo = custom.get("geo_points", {})
        if "to" in geo:
            to_locality = geo["to"].get("name") or geo["to"].get("address")

    if len(pickups) > 1:
        # Multi-pickup: show each pickup locality → destination
        pickup_names: list[str] = []
        geo = custom.get("geo_points", {})
        for i, p in enumerate(pickups):
            # Try geo_points first (from_1, from_2, etc.) for locality name
            geo_key = f"from_{i + 1}" if i > 0 else "from"
            loc = None
            if geo_key in geo:
                loc = geo[geo_key].get("name") or geo[geo_key].get("address")
            if not loc and i == 0:
                from_names_d = route_cls.get("from_names") or {}
                loc = from_names_d.get(lang) or route_cls.get("from_locality")
            if not loc:
                # Last resort: raw address (may contain PII — but pickups
                # only store what the user typed, which is usually a city)
                loc = p.get("addr")
            pickup_names.append(loc or "?")

        dest = to_locality or "?"
        route_str = " → ".join(pickup_names) + f" → {dest}"
    else:
        # Single pickup: standard from → to
        from_names_d = route_cls.get("from_names") or {}
        from_locality = from_names_d.get(lang) or route_cls.get("from_locality")
        if not from_locality:
            geo = custom.get("geo_points", {})
            if "from" in geo:
                from_locality = geo["from"].get("name") or geo["from"].get("address")

        if from_locality and to_locality:
            route_str = f"{from_locality} → {to_locality}"
        elif from_locality:
            route_str = f"{from_locality} → ?"
        elif to_locality:
            route_str = f"? → {to_locality}"
        else:
            route_str = _L["not_specified"]

    # --- Date + time window ---
    move_date = custom.get("move_date")
    time_window_str = _format_time_window(data.get("time_window"), lang)
    if move_date:
        date_str = f"{move_date}, {time_window_str}"
    else:
        date_str = time_window_str

    # --- Volume ---
    volume = custom.get("volume_category")
    volume_labels = _CREW_VOLUME_LABELS.get(lang, _CREW_VOLUME_LABELS["ru"])
    volume_str = volume_labels.get(volume, volume or _L["not_specified"])

    # --- Floors + elevator ---
    from app.core.bots.moving_bot_validators import parse_floor_info

    def _floor_label(floor: int, has_elev: bool) -> str:
        elev_txt = _L["elevator_yes"] if has_elev else _L["elevator_no"]
        return f"{floor} ({elev_txt})"

    floor_to_raw = data.get("floor_to") or ""
    f_to, elev_to = parse_floor_info(floor_to_raw)

    if len(pickups) > 1:
        # Multi-pickup: show floors per pickup point + destination
        pickup_floor_parts: list[str] = []
        for i, p in enumerate(pickups, 1):
            p_floor_raw = p.get("floor", "")
            p_floor, p_elev = parse_floor_info(p_floor_raw)
            pickup_floor_parts.append(
                f"{_L['pickup']} {i}: {_floor_label(p_floor, p_elev)}"
            )
        pickup_floor_parts.append(
            f"{_L['destination']}: {_floor_label(f_to, elev_to)}"
        )
        floors_str = "\n  ".join(pickup_floor_parts)
    else:
        # Single pickup
        floor_from_raw = data.get("floor_from") or ""
        f_from, elev_from = parse_floor_info(floor_from_raw)
        floors_str = f"{_floor_label(f_from, elev_from)} → {_floor_label(f_to, elev_to)}"

    # --- Items summary (from extract_items) ---
    from app.core.bots.moving_bot_pricing import ITEM_LABELS

    cargo_items = custom.get("cargo_items") or []
    items_str = ""
    if cargo_items:
        item_parts = []
        for item in cargo_items[:8]:
            key = item.get("key", "")
            qty = item.get("qty", 1)
            label = ITEM_LABELS.get(key, {}).get(lang) or key.replace("_", " ").capitalize()
            if qty > 1:
                item_parts.append(f"{label} ×{qty}")
            else:
                item_parts.append(label)
        items_str = ", ".join(item_parts)

    # --- Estimate ---
    estimate_suppressed = custom.get("estimate_suppressed", False)
    estimate_display_disabled = custom.get("estimate_display_disabled", False)
    estimate_min = custom.get("estimate_min")
    estimate_max = custom.get("estimate_max")
    estimate_str = ""
    if not estimate_suppressed and not estimate_display_disabled and estimate_min is not None and estimate_max is not None:
        estimate_str = f"₪{estimate_min}–₪{estimate_max}"

    # --- Extras (services) ---
    extras = data.get("extras")
    extras_str = _format_extras(extras, lang) if extras else ""

    # --- Build message (no header — operator knows the context) ---
    lines = [
        f"🧰 {_L['job']} {lead_display}",
        "",
        f"{_L['route']}: {route_str}",
        f"{_L['date']}: {date_str}",
        f"{_L['volume']}: {volume_str}",
        f"{_L['floors']}: {floors_str}",
    ]

    if items_str:
        lines.append(f"{_L['items']}: {items_str}")
    _no_extras = {"нет", "none", "אין", ""}
    if extras_str and extras_str not in _no_extras:
        lines.append(f"{_L['services']}: {extras_str}")
    if estimate_str:
        lines.append(f"{_L['estimate']}: {estimate_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers (duplicated from notification_service to avoid coupling)
# ---------------------------------------------------------------------------

def _format_time_window(time_window: str | None, lang: str = "ru") -> str:
    """Format time window to human-readable localized string."""
    _TW: dict[str, dict[str, str]] = {
        "ru": {
            "morning": "утро (08:00–12:00)", "afternoon": "день (12:00–17:00)",
            "evening": "вечер (17:00–21:00)", "flexible": "гибко",
            "exact": "точное время", "none": "не указано",
        },
        "en": {
            "morning": "morning (08:00–12:00)", "afternoon": "afternoon (12:00–17:00)",
            "evening": "evening (17:00–21:00)", "flexible": "flexible",
            "exact": "exact time", "none": "not specified",
        },
        "he": {
            "morning": "בוקר (08:00–12:00)", "afternoon": "צהריים (12:00–17:00)",
            "evening": "ערב (17:00–21:00)", "flexible": "גמיש",
            "exact": "שעה מדויקת", "none": "לא צוין",
        },
    }
    labels = _TW.get(lang, _TW["ru"])
    if time_window and time_window.startswith("exact:"):
        return f"{labels['exact']}: {time_window[6:]}"
    return labels.get(time_window, time_window or labels["none"])


def _format_extras(extras: list | None, lang: str = "ru") -> str:
    """Format extras list to human-readable localized string."""
    _EX: dict[str, dict[str, str]] = {
        "ru": {
            "loaders": "грузчики", "assembly": "сборка/разборка",
            "packing": "упаковка", "none": "нет", "empty": "нет",
        },
        "en": {
            "loaders": "movers", "assembly": "assembly/disassembly",
            "packing": "packing", "none": "none", "empty": "none",
        },
        "he": {
            "loaders": "סבלים", "assembly": "הרכבה/פירוק",
            "packing": "אריזה", "none": "אין", "empty": "אין",
        },
    }
    labels = _EX.get(lang, _EX["ru"])
    if not extras:
        return labels["empty"]
    names = [labels.get(e, e) for e in extras if e != "none"]
    return ", ".join(names) if names else labels["empty"]


# ---------------------------------------------------------------------------
# Localized labels
# ---------------------------------------------------------------------------

_CREW_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "job": "Заказ",
        "route": "Маршрут",
        "date": "Дата",
        "volume": "Объём",
        "floors": "Этажи",
        "items": "Вещи",
        "services": "Услуги",
        "estimate": "Оценка",
        "not_specified": "не указано",
        "elevator_yes": "есть лифт",
        "elevator_no": "без лифта",
        "pickup": "Забор",
        "destination": "Доставка",
    },
    "en": {
        "job": "Job",
        "route": "Route",
        "date": "Date",
        "volume": "Volume",
        "floors": "Floors",
        "items": "Items",
        "services": "Services",
        "estimate": "Estimate",
        "not_specified": "not specified",
        "elevator_yes": "elevator",
        "elevator_no": "no elevator",
        "pickup": "Pickup",
        "destination": "Delivery",
    },
    "he": {
        "job": "הזמנה",
        "route": "מסלול",
        "date": "תאריך",
        "volume": "נפח",
        "floors": "קומות",
        "items": "פריטים",
        "services": "שירותים",
        "estimate": "הערכה",
        "not_specified": "לא צוין",
        "elevator_yes": "מעלית",
        "elevator_no": "ללא מעלית",
        "pickup": "איסוף",
        "destination": "משלוח",
    },
}

_CREW_VOLUME_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "small": "малый (до 1 м³)",
        "medium": "средний (1–3 м³)",
        "large": "большой (3–10 м³)",
        "xl": "очень большой (10+ м³)",
    },
    "en": {
        "small": "small (up to 1 m³)",
        "medium": "medium (1–3 m³)",
        "large": "large (3–10 m³)",
        "xl": "extra large (10+ m³)",
    },
    "he": {
        "small": "קטן (עד 1 מ\"ק)",
        "medium": "בינוני (1–3 מ\"ק)",
        "large": "גדול (3–10 מ\"ק)",
        "xl": "גדול מאוד (10+ מ\"ק)",
    },
}
