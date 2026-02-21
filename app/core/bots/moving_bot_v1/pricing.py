# app/core/bots/moving_bot_v1/pricing.py
"""
Pricing configuration for the Moving Bot — Nationwide zone-based.

All tunable values live in ``data/pricing_config.json`` (sub-directory).
This module loads the JSON once at import time and exposes:
- ``PricingConfig`` — base parameters dataclass
- ``ITEM_CATALOG`` — item (min, max) prices
- ``ITEM_ALIAS_LOOKUP`` — multilingual alias -> canonical key (Phase 10)
- ``VOLUME_CATEGORIES`` — volume surcharges (Phase 9)
- ``EXTRAS_ADJUSTMENTS`` — extras surcharges / discounts
- ``ROUTING_BANDS`` / ``ROUTING_MINIMUMS`` — route-band fees (Phase 14)
- ``GUARDS`` — underpricing guard thresholds (Phase 14)
- ``estimate_price()`` — the estimate function

v1.0 — wide-range estimate (items_min/items_max expanded separately).
v1.1 — midpoint-based estimate (Phase 6): stable center, symmetric margin.
v1.2 — JSON-driven config + volume categories (Phase 9).
v1.3 — Multilingual item aliases + qty-based items (Phase 10).
v2.0 — Nationwide routing bands + underpricing guards (Phase 14).

All values are in **ILS** and must match mover expectations.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    # Public API
    "PricingConfig", "HAIFA_METRO_PRICING",
    "ITEM_CATALOG", "ITEM_ALIAS_LOOKUP",
    "VOLUME_CATEGORIES", "EXTRAS_ADJUSTMENTS",
    "ROUTING_BANDS", "ROUTING_MINIMUMS",
    "GUARDS",
    "estimate_price",
    # Private — used by tests:
    "_RAW_CONFIG", "_CONFIG_PATH",
    "_load_pricing_config", "_build_alias_lookup",
    "_EXTRAS_TO_ADJUSTMENTS",
]


# ---------------------------------------------------------------------------
# Load JSON config (once at import time)
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "data" / "pricing_config.json"


def _load_pricing_config() -> dict:
    """Load pricing configuration from JSON file."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_RAW_CONFIG = _load_pricing_config()


# ---------------------------------------------------------------------------
# Base parameters (from JSON)
# ---------------------------------------------------------------------------

@dataclass
class PricingConfig:
    """Base pricing parameters for a region."""
    base_callout: int = _RAW_CONFIG["base"]["callout"]
    no_elevator_per_floor: int = _RAW_CONFIG["base"]["no_elevator_per_floor"]
    extra_pickup: int = _RAW_CONFIG["base"]["extra_pickup"]
    estimate_margin: float = _RAW_CONFIG["base"]["estimate_margin"]
    distance_factor: float = 1.0  # set per-request by geo classification


HAIFA_METRO_PRICING = PricingConfig()


# ---------------------------------------------------------------------------
# Item catalog — (min_price, max_price) in ILS (from JSON)
# ---------------------------------------------------------------------------

ITEM_CATALOG: dict[str, tuple[int, int]] = {
    k: (v[0], v[1]) for k, v in _RAW_CONFIG["item_catalog"].items()
}


# ---------------------------------------------------------------------------
# Item aliases — multilingual alias -> canonical key (Phase 10, from JSON)
# ---------------------------------------------------------------------------

def _build_alias_lookup(
    raw_aliases: dict[str, list[str]],
    catalog: dict[str, tuple[int, int]],
) -> dict[str, str]:
    """Build reversed alias -> canonical key lookup.

    - Only includes aliases whose canonical key exists in ``catalog``.
    - Raises ``ValueError`` on duplicate aliases (catches config errors).
    - Returns dict sorted longest-alias-first for correct multi-word matching.
    """
    lookup: dict[str, str] = {}
    for canonical_key, aliases in raw_aliases.items():
        if canonical_key not in catalog:
            continue  # skip unknown keys silently
        for alias in aliases:
            normalized = alias.strip().lower()
            if not normalized:
                continue
            if normalized in lookup:
                raise ValueError(
                    f"Duplicate item alias {normalized!r}: "
                    f"maps to both {lookup[normalized]!r} and {canonical_key!r}"
                )
            lookup[normalized] = canonical_key
    # Sort longest-first so multi-word aliases match before shorter ones
    return dict(sorted(lookup.items(), key=lambda kv: -len(kv[0])))


ITEM_ALIAS_LOOKUP: dict[str, str] = _build_alias_lookup(
    _RAW_CONFIG.get("item_aliases", {}),
    ITEM_CATALOG,
)


# ---------------------------------------------------------------------------
# Volume categories — flat surcharges by move size (Phase 9, from JSON)
# ---------------------------------------------------------------------------

VOLUME_CATEGORIES: dict[str, int] = dict(_RAW_CONFIG["volume_categories"])


# ---------------------------------------------------------------------------
# Extras adjustments — fixed ILS surcharges / discounts (from JSON)
# ---------------------------------------------------------------------------

EXTRAS_ADJUSTMENTS: dict[str, int] = dict(_RAW_CONFIG["extras_adjustments"])


# ---------------------------------------------------------------------------
# Extras-service -> adjustment mapping (from JSON)
# ---------------------------------------------------------------------------

# Maps the handler's extras enum values (from EXTRA_CHOICES) to
# the pricing adjustment keys when relevant.
_EXTRAS_TO_ADJUSTMENTS: dict[str, str] = dict(_RAW_CONFIG["extras_service_mapping"])


# ---------------------------------------------------------------------------
# Routing bands — flat fees and minimums by route distance (Phase 14)
# ---------------------------------------------------------------------------

ROUTING_BANDS: dict[str, int] = dict(
    _RAW_CONFIG.get("routing", {}).get("bands", {})
)
ROUTING_MINIMUMS: dict[str, int] = dict(
    _RAW_CONFIG.get("routing", {}).get("minimums", {})
)


# ---------------------------------------------------------------------------
# Underpricing guards — thresholds and multipliers (Phase 14)
# ---------------------------------------------------------------------------

GUARDS: dict[str, object] = dict(_RAW_CONFIG.get("guards", {}))


# ---------------------------------------------------------------------------
# Estimate function (Phase 3 -> v1.1 Phase 6 -> v1.2 Phase 9 -> v2.0 Phase 14)
# ---------------------------------------------------------------------------

def estimate_price(
    *,
    items: list[dict] | list[str] | None = None,
    volume_category: str | None = None,
    floor_from: int = 0,
    floor_to: int = 0,
    has_elevator_from: bool = True,
    has_elevator_to: bool = True,
    extra_pickups: int = 0,
    extras: list[str] | None = None,
    pricing: PricingConfig | None = None,
    pickup_floors: list[tuple[int, bool]] | None = None,
    route_band: str | None = None,
) -> dict:
    """
    Calculate a price estimate range for a moving request (v2.0).

    The estimate uses a **stable midpoint** with symmetric margin:

    1. **Base callout** — minimum fee.
    2. **Floor surcharges** — for each floor without an elevator at
       both pickup(s) and delivery.  Floor 0 and 1 are free (ground level).
    3. **Extra pickups** — flat fee per additional pickup location.
    4. **Volume surcharge** — flat fee by move size category (Phase 9).
    5. **Item costs** — midpoint of each item's (min, max) range x qty, summed.
    6. **Extras adjustments** — surcharges / discounts from
       ``EXTRAS_ADJUSTMENTS`` that match the requested extras.
    7. **Route fee** — flat fee by route distance band (Phase 14).
    8. **Distance factor** — coarse geo multiplier (legacy, default 1.0).
    9. **Margin** — the midpoint is expanded by +/-``estimate_margin``.
    10. **Route minimum** — floor for inter-city routes (Phase 14).
    11. **Underpricing guards** — XL floor, high-floor multiplier,
        national minimum (Phase 14).

    Args:
        volume_category: Phase 9 — "small", "medium", "large", or "xl".
        pickup_floors: Phase 4 — list of (floor_num, has_elevator) tuples.
        route_band: Phase 14 — route distance band string
            (e.g. "same_city", "inter_region_long", "extreme_distance").
            ``None`` -> no route fee (backward compat).

    Returns::

        {
            "estimate_min": int,
            "estimate_max": int,
            "currency": "ILS",
            "breakdown": { ... },
        }
    """
    cfg = pricing or HAIFA_METRO_PRICING

    # 1. Base
    base = cfg.base_callout

    # 2. Floor surcharges (floors 0 and 1 are ground-level -> free)
    floor_surcharge = 0

    # Phase 4: multi-pickup floors
    if pickup_floors:
        for p_floor, p_has_elevator in pickup_floors:
            if not p_has_elevator and p_floor > 1:
                floor_surcharge += (p_floor - 1) * cfg.no_elevator_per_floor
    else:
        # Legacy: single pickup floor
        if not has_elevator_from and floor_from > 1:
            floor_surcharge += (floor_from - 1) * cfg.no_elevator_per_floor

    if not has_elevator_to and floor_to > 1:
        floor_surcharge += (floor_to - 1) * cfg.no_elevator_per_floor

    # Phase 14 guard: high-floor no-elevator multiplier
    hf_threshold = int(GUARDS.get("high_floor_no_elevator_threshold", 99))
    hf_multiplier = float(GUARDS.get("high_floor_surcharge_multiplier", 1.0))
    has_high_floor = False
    if pickup_floors:
        for p_floor, p_has_elevator in pickup_floors:
            if not p_has_elevator and p_floor >= hf_threshold:
                has_high_floor = True
                break
    else:
        if not has_elevator_from and floor_from >= hf_threshold:
            has_high_floor = True
    if not has_elevator_to and floor_to >= hf_threshold:
        has_high_floor = True

    if has_high_floor and hf_multiplier > 1.0:
        floor_surcharge = math.ceil(floor_surcharge * hf_multiplier)

    # 3. Extra pickups
    pickup_fee = max(0, extra_pickups) * cfg.extra_pickup

    # 4. Volume surcharge (Phase 9)
    volume_surcharge = 0
    if volume_category and volume_category in VOLUME_CATEGORIES:
        volume_surcharge = VOLUME_CATEGORIES[volume_category]

    # 5. Items — v1.3: supports dict (key+qty) or str (backward compat)
    items_mid = 0.0
    if items:
        for item in items:
            if isinstance(item, dict):
                key = item.get("key", "")
                qty = item.get("qty", 1)
            else:
                key, qty = item, 1
            if key in ITEM_CATALOG:
                lo, hi = ITEM_CATALOG[key]
                items_mid += ((lo + hi) / 2) * qty

    # 6. Extras adjustments
    extras_adj = 0
    if extras:
        for svc in extras:
            # Direct match in EXTRAS_ADJUSTMENTS
            if svc in EXTRAS_ADJUSTMENTS:
                extras_adj += EXTRAS_ADJUSTMENTS[svc]
            # Mapped match (e.g. "assembly" -> "disassembly")
            elif svc in _EXTRAS_TO_ADJUSTMENTS:
                adj_key = _EXTRAS_TO_ADJUSTMENTS[svc]
                extras_adj += EXTRAS_ADJUSTMENTS.get(adj_key, 0)

    # 7. Route band fee (Phase 14)
    route_fee = 0
    route_minimum = 0
    if route_band and route_band in ROUTING_BANDS:
        route_fee = ROUTING_BANDS[route_band]
        route_minimum = ROUTING_MINIMUMS.get(route_band, 0)

    # 7.1. Midpoint
    fixed = base + floor_surcharge + pickup_fee + volume_surcharge + extras_adj + route_fee
    mid = fixed + items_mid

    # 7.2: Apply distance factor (coarse geo multiplier, legacy)
    mid = mid * cfg.distance_factor

    # 8. Symmetric margin around midpoint
    estimate_min = max(0, math.floor(mid * (1 - cfg.estimate_margin)))
    estimate_max = math.ceil(mid * (1 + cfg.estimate_margin))

    # 9. Route minimum (Phase 14)
    minimum_applied = False
    if route_minimum > 0 and estimate_min < route_minimum:
        estimate_min = route_minimum
        if estimate_max < route_minimum:
            estimate_max = route_minimum
        minimum_applied = True

    # 10. Underpricing guards (Phase 14)
    guards_applied: list[str] = []

    # Guard A: XL volume floor
    xl_floor = int(GUARDS.get("xl_volume_floor", 0))
    if volume_category == "xl" and xl_floor > 0 and estimate_min < xl_floor:
        estimate_min = xl_floor
        if estimate_max < xl_floor:
            estimate_max = xl_floor
        minimum_applied = True
        guards_applied.append("xl_volume_floor")

    # Guard B: National move minimum (inter-region moves never below threshold)
    national_min = int(GUARDS.get("national_move_minimum", 0))
    if route_band and route_band in (
        "inter_region_short", "inter_region_long", "extreme_distance",
    ):
        if national_min > 0 and estimate_min < national_min:
            estimate_min = national_min
            minimum_applied = True
            guards_applied.append("national_move_minimum")

    if has_high_floor:
        guards_applied.append("high_floor_surcharge")

    return {
        "estimate_min": estimate_min,
        "estimate_max": estimate_max,
        "currency": "ILS",
        "breakdown": {
            "base": base,
            "floor_surcharge": floor_surcharge,
            "pickup_fee": pickup_fee,
            "volume_surcharge": volume_surcharge,
            "items_mid": items_mid,
            "extras_adj": extras_adj,
            "distance_factor": cfg.distance_factor,
            "route_band": route_band,
            "route_fee": route_fee,
            "route_minimum": route_minimum,
            "minimum_applied": minimum_applied,
            "guards_applied": guards_applied,
        },
    }
