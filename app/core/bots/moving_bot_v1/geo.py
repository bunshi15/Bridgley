# app/core/bots/moving_bot_v1/geo.py
"""
Regional classification for the Moving Bot.

Phase 8 (original):
    GPS-based Haifa metro classification — binary inside/outside.

Phase 14 (nationwide):
    Text-based route-band classifier — deterministic, no external APIs.
    Uses CBS locality dataset (``localities``) to resolve
    city names from address text and classify routes into six bands.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    # Public API
    "HAIFA_CENTER_LAT", "HAIFA_CENTER_LON", "HAIFA_METRO_RADIUS_KM",
    "FACTOR_INSIDE_METRO", "FACTOR_OUTSIDE_METRO",
    "RegionClassification",
    "haversine_km", "classify_point", "classify_geo_points",
    "RouteBand", "RouteClassification",
    "MACRO_REGIONS", "METRO_CLUSTERS", "EILAT_CODE",
    "classify_route",
    # Private — used by tests:
    "_same_metro", "_LONG_PAIRS",
]


# ---------------------------------------------------------------------------
# Haifa Metro definition
# ---------------------------------------------------------------------------
HAIFA_CENTER_LAT = 32.794
HAIFA_CENTER_LON = 34.989
HAIFA_METRO_RADIUS_KM = 15.0

# ---------------------------------------------------------------------------
# Distance-factor tiers
# ---------------------------------------------------------------------------
FACTOR_INSIDE_METRO = 1.0
FACTOR_OUTSIDE_METRO = 1.2


@dataclass(frozen=True)
class RegionClassification:
    """Result of classifying a single geo point."""

    inside_metro: bool
    distance_km: float       # distance from Haifa center
    distance_factor: float   # pricing multiplier for this point


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    R = 6371.0  # Earth mean radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Single-point classification
# ---------------------------------------------------------------------------

def classify_point(lat: float, lon: float) -> RegionClassification:
    """Classify a single GPS point as inside / outside Haifa metro."""
    dist = haversine_km(HAIFA_CENTER_LAT, HAIFA_CENTER_LON, lat, lon)
    inside = dist <= HAIFA_METRO_RADIUS_KM
    factor = FACTOR_INSIDE_METRO if inside else FACTOR_OUTSIDE_METRO
    return RegionClassification(
        inside_metro=inside,
        distance_km=round(dist, 2),
        distance_factor=factor,
    )


# ---------------------------------------------------------------------------
# Multi-point classification (worst-case)
# ---------------------------------------------------------------------------

def classify_geo_points(
    geo_points: dict[str, Any] | None,
) -> tuple[float, dict[str, RegionClassification]]:
    """Classify all geo points and return the worst-case distance factor.

    If *any* point is outside the metro area the entire move gets the
    outside-metro surcharge.  This is the conservative approach: a move
    from Haifa to Nazareth should use the outside factor even though one
    end is inside.

    Returns
    -------
    (distance_factor, classifications)
        ``distance_factor`` is ``1.0`` when there are no geo points or all
        points are inside the metro area.
    """
    if not geo_points:
        return FACTOR_INSIDE_METRO, {}

    classifications: dict[str, RegionClassification] = {}
    worst_factor = FACTOR_INSIDE_METRO

    for key, pt in geo_points.items():
        lat = pt.get("lat")
        lon = pt.get("lon")
        if lat is not None and lon is not None:
            cls = classify_point(lat, lon)
            classifications[key] = cls
            if cls.distance_factor > worst_factor:
                worst_factor = cls.distance_factor

    return worst_factor, classifications


# =========================================================================
# Phase 14: Nationwide text-based route classification
# =========================================================================

class RouteBand(str, Enum):
    """Route distance bands — determines pricing surcharge and minimums."""

    SAME_CITY = "same_city"
    SAME_METRO = "same_metro"
    SAME_REGION = "same_region"
    INTER_REGION_SHORT = "inter_region_short"
    INTER_REGION_LONG = "inter_region_long"
    EXTREME_DISTANCE = "extreme_distance"


@dataclass(frozen=True)
class RouteClassification:
    """Result of text-based route classification."""

    band: RouteBand
    from_locality: str | None    # matched city name (he) or None
    to_locality: str | None
    from_region: int | None      # CBS region code
    to_region: int | None


# ---------------------------------------------------------------------------
# Macro regions: CBS region_code -> macro region
# ---------------------------------------------------------------------------

MACRO_REGIONS: dict[int, str] = {
    # North
    21: "north", 22: "north", 23: "north",
    24: "north", 25: "north", 29: "north",
    # Haifa
    31: "haifa", 32: "haifa",
    # Center
    41: "center", 42: "center", 43: "center", 44: "center",
    51: "center", 52: "center", 53: "center",
    # Jerusalem
    11: "jerusalem",
    # South
    61: "south", 62: "south",
}

# ---------------------------------------------------------------------------
# Metro clusters: sets of CBS region_codes that form a metro area
# ---------------------------------------------------------------------------

METRO_CLUSTERS: dict[str, set[int]] = {
    "gush_dan": {51, 52, 53},        # Tel Aviv, Ramat Gan, Holon
    "haifa_krayot": {31},             # Haifa + Krayot
    "jerusalem_ring": {11},           # Jerusalem
    "beer_sheva_area": {62},          # Beer Sheva (Eilat excluded below)
}

# Eilat — special case: always extreme_distance
EILAT_CODE = 2600

# ---------------------------------------------------------------------------
# Long inter-region pairs (north<->south, north<->jerusalem, haifa<->south)
# ---------------------------------------------------------------------------

_LONG_PAIRS: set[frozenset[str]] = {
    frozenset({"north", "south"}),
    frozenset({"north", "jerusalem"}),
    frozenset({"haifa", "south"}),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _same_metro(region_a: int, region_b: int, code_a: int, code_b: int) -> bool:
    """Check if two localities are in the same metro cluster.

    Eilat (code 2600) is excluded from the Beer Sheva metro area.
    """
    for _cluster_name, region_codes in METRO_CLUSTERS.items():
        if region_a in region_codes and region_b in region_codes:
            # Beer Sheva cluster: exclude Eilat
            if _cluster_name == "beer_sheva_area":
                if code_a == EILAT_CODE or code_b == EILAT_CODE:
                    return False
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_route(addr_from: str, addr_to: str) -> RouteClassification:
    """Classify the route band between two address texts.

    Deterministic, offline, no external APIs.  Uses the CBS locality
    dataset to resolve city names and the macro-region / metro-cluster
    model to classify the route.

    Algorithm:
        1. Extract locality from each address text
        2. Either unknown -> ``inter_region_short`` (conservative)
        3. Same city_code -> ``same_city``
        4. Eilat involved -> ``extreme_distance``
        5. Same metro cluster -> ``same_metro``
        6. Same macro region -> ``same_region``
        7. Different macro regions in ``_LONG_PAIRS`` -> ``inter_region_long``
        8. Default -> ``inter_region_short``
    """
    from app.core.bots.moving_bot_v1.localities import find_locality

    loc_from = find_locality(addr_from)
    loc_to = find_locality(addr_to)

    from_name = loc_from.he if loc_from else None
    to_name = loc_to.he if loc_to else None
    from_region = loc_from.region if loc_from else None
    to_region = loc_to.region if loc_to else None

    def _result(band: RouteBand) -> RouteClassification:
        return RouteClassification(
            band=band,
            from_locality=from_name,
            to_locality=to_name,
            from_region=from_region,
            to_region=to_region,
        )

    # 1. Either locality unknown -> conservative fallback
    if loc_from is None or loc_to is None:
        return _result(RouteBand.INTER_REGION_SHORT)

    # 2. Same city
    if loc_from.code == loc_to.code:
        return _result(RouteBand.SAME_CITY)

    # 3. Eilat -> extreme distance
    if loc_from.code == EILAT_CODE or loc_to.code == EILAT_CODE:
        return _result(RouteBand.EXTREME_DISTANCE)

    # 4. Same metro cluster
    if _same_metro(loc_from.region, loc_to.region,
                   loc_from.code, loc_to.code):
        return _result(RouteBand.SAME_METRO)

    # 5. Same macro region
    macro_from = MACRO_REGIONS.get(loc_from.region)
    macro_to = MACRO_REGIONS.get(loc_to.region)

    if macro_from and macro_to and macro_from == macro_to:
        return _result(RouteBand.SAME_REGION)

    # 6. Long inter-region pairs
    if macro_from and macro_to:
        pair = frozenset({macro_from, macro_to})
        if pair in _LONG_PAIRS:
            return _result(RouteBand.INTER_REGION_LONG)

    # 7. Default: inter-region short
    return _result(RouteBand.INTER_REGION_SHORT)
