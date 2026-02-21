# tests/test_moving_bot_geo.py
"""
Tests for Phase 8 — Regional Classification (Haifa Metro).

Covers:
- haversine_km()         — great-circle distance
- classify_point()       — single-point inside/outside classification
- classify_geo_points()  — multi-point worst-case factor
"""
from __future__ import annotations

import pytest
from app.core.bots.moving_bot_geo import (
    haversine_km,
    classify_point,
    classify_geo_points,
    RegionClassification,
    HAIFA_CENTER_LAT,
    HAIFA_CENTER_LON,
    HAIFA_METRO_RADIUS_KM,
    FACTOR_INSIDE_METRO,
    FACTOR_OUTSIDE_METRO,
    # Phase 14: route band classification
    RouteBand,
    RouteClassification,
    classify_route,
    MACRO_REGIONS,
    METRO_CLUSTERS,
    EILAT_CODE,
)


# ============================================================================
# TestHaversineKm
# ============================================================================

class TestHaversineKm:
    """Tests for the Haversine distance calculation."""

    def test_same_point_is_zero(self):
        assert haversine_km(32.794, 34.989, 32.794, 34.989) == 0.0

    def test_haifa_to_tel_aviv(self):
        # Haifa center → Tel Aviv center, ~82-95 km
        dist = haversine_km(32.794, 34.989, 32.080, 34.780)
        assert 75 < dist < 100

    def test_haifa_to_kiryat_bialik(self):
        # ~5 km north
        dist = haversine_km(32.794, 34.989, 32.833, 35.085)
        assert 5 < dist < 12

    def test_haifa_to_nazareth(self):
        # ~30 km east
        dist = haversine_km(32.794, 34.989, 32.700, 35.300)
        assert 25 < dist < 40

    def test_symmetry(self):
        d1 = haversine_km(32.794, 34.989, 32.080, 34.780)
        d2 = haversine_km(32.080, 34.780, 32.794, 34.989)
        assert abs(d1 - d2) < 0.001


# ============================================================================
# TestClassifyPoint
# ============================================================================

class TestClassifyPoint:
    """Tests for single-point classification."""

    def test_haifa_center_is_inside(self):
        cls = classify_point(HAIFA_CENTER_LAT, HAIFA_CENTER_LON)
        assert cls.inside_metro is True
        assert cls.distance_km == 0.0
        assert cls.distance_factor == FACTOR_INSIDE_METRO

    def test_kiryat_motzkin_is_inside(self):
        # ~9 km north of center
        cls = classify_point(32.837, 35.077)
        assert cls.inside_metro is True
        assert cls.distance_km < HAIFA_METRO_RADIUS_KM

    def test_kiryat_ata_is_inside(self):
        # ~11 km northeast
        cls = classify_point(32.810, 35.106)
        assert cls.inside_metro is True

    def test_tirat_carmel_is_inside(self):
        # ~4 km south
        cls = classify_point(32.760, 34.972)
        assert cls.inside_metro is True

    def test_nesher_is_inside(self):
        # ~5.5 km east
        cls = classify_point(32.771, 35.041)
        assert cls.inside_metro is True

    def test_tel_aviv_is_outside(self):
        cls = classify_point(32.080, 34.780)
        assert cls.inside_metro is False
        assert cls.distance_factor == FACTOR_OUTSIDE_METRO

    def test_nazareth_is_outside(self):
        cls = classify_point(32.700, 35.300)
        assert cls.inside_metro is False

    def test_akko_is_outside(self):
        # ~17 km north
        cls = classify_point(32.927, 35.084)
        assert cls.inside_metro is False

    def test_return_type_is_frozen_dataclass(self):
        cls = classify_point(32.794, 34.989)
        assert isinstance(cls, RegionClassification)
        with pytest.raises(AttributeError):
            cls.inside_metro = False  # frozen

    def test_distance_km_is_rounded(self):
        cls = classify_point(32.800, 35.000)
        # Should be rounded to 2 decimal places
        assert cls.distance_km == round(cls.distance_km, 2)


# ============================================================================
# TestClassifyGeoPoints
# ============================================================================

class TestClassifyGeoPoints:
    """Tests for multi-point classification (worst-case logic)."""

    def test_none_returns_default(self):
        factor, info = classify_geo_points(None)
        assert factor == FACTOR_INSIDE_METRO
        assert info == {}

    def test_empty_dict_returns_default(self):
        factor, info = classify_geo_points({})
        assert factor == FACTOR_INSIDE_METRO
        assert info == {}

    def test_all_inside_returns_1_0(self):
        geo = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},
            "delivery": {"lat": 32.810, "lon": 35.010},
        }
        factor, info = classify_geo_points(geo)
        assert factor == FACTOR_INSIDE_METRO
        assert len(info) == 2
        assert all(c.inside_metro for c in info.values())

    def test_one_outside_returns_outside_factor(self):
        geo = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},  # inside
            "delivery": {"lat": 32.080, "lon": 34.780},  # Tel Aviv
        }
        factor, info = classify_geo_points(geo)
        assert factor == FACTOR_OUTSIDE_METRO
        assert info["pickup_1"].inside_metro is True
        assert info["delivery"].inside_metro is False

    def test_all_outside_returns_outside_factor(self):
        geo = {
            "pickup_1": {"lat": 32.080, "lon": 34.780},
            "delivery": {"lat": 31.250, "lon": 34.790},
        }
        factor, info = classify_geo_points(geo)
        assert factor == FACTOR_OUTSIDE_METRO

    def test_missing_lat_lon_skipped(self):
        geo = {
            "pickup_1": {"name": "Some place"},  # no lat/lon
        }
        factor, info = classify_geo_points(geo)
        assert factor == FACTOR_INSIDE_METRO
        assert len(info) == 0

    def test_mixed_valid_and_invalid(self):
        geo = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},  # valid, inside
            "delivery": {"name": "No coords"},            # invalid
        }
        factor, info = classify_geo_points(geo)
        assert factor == FACTOR_INSIDE_METRO
        assert len(info) == 1
        assert "pickup_1" in info

    def test_classifications_dict_keys_match_input(self):
        geo = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},
            "pickup_2": {"lat": 32.810, "lon": 35.010},
            "delivery": {"lat": 32.080, "lon": 34.780},
        }
        factor, info = classify_geo_points(geo)
        assert set(info.keys()) == {"pickup_1", "pickup_2", "delivery"}


# ============================================================================
# Phase 14: Text-based route classification
# ============================================================================

class TestRouteBandEnum:
    """Sanity checks for the RouteBand enum."""

    def test_all_bands_are_strings(self):
        for band in RouteBand:
            assert isinstance(band.value, str)

    def test_six_bands(self):
        assert len(RouteBand) == 6


class TestMacroRegions:
    """Verify macro region mapping completeness."""

    def test_all_main_regions_mapped(self):
        """All CBS region codes used in the dataset should be mapped."""
        expected = {11, 21, 22, 23, 24, 25, 29, 31, 32, 41, 42, 43, 44, 51, 52, 53, 61, 62}
        for code in expected:
            assert code in MACRO_REGIONS, f"Region {code} not in MACRO_REGIONS"

    def test_north_regions(self):
        for code in (21, 22, 23, 24, 25, 29):
            assert MACRO_REGIONS[code] == "north"

    def test_haifa_regions(self):
        for code in (31, 32):
            assert MACRO_REGIONS[code] == "haifa"

    def test_center_regions(self):
        for code in (41, 42, 43, 44, 51, 52, 53):
            assert MACRO_REGIONS[code] == "center"

    def test_jerusalem_region(self):
        assert MACRO_REGIONS[11] == "jerusalem"

    def test_south_regions(self):
        for code in (61, 62):
            assert MACRO_REGIONS[code] == "south"


class TestClassifyRoute:
    """Tests for the classify_route() function."""

    # --- same_city ---

    def test_same_city_haifa_to_haifa(self):
        cls = classify_route("Хайфа", "Haifa")
        assert cls.band == RouteBand.SAME_CITY
        assert cls.from_region == 31
        assert cls.to_region == 31

    def test_same_city_tel_aviv(self):
        cls = classify_route("Тель-Авив", "Tel Aviv")
        assert cls.band == RouteBand.SAME_CITY

    # --- same_metro ---

    def test_same_metro_tel_aviv_to_ramat_gan(self):
        """Gush Dan: Tel Aviv (51) → Ramat Gan (52)."""
        cls = classify_route("Тель-Авив", "Рамат-Ган")
        assert cls.band == RouteBand.SAME_METRO

    def test_same_metro_tel_aviv_to_holon(self):
        """Gush Dan: Tel Aviv (51) → Holon (53)."""
        cls = classify_route("Тель-Авив", "Холон")
        assert cls.band == RouteBand.SAME_METRO

    def test_same_metro_holon_to_bat_yam(self):
        """Gush Dan: Holon (53) → Bat Yam (53) — same region = same metro."""
        cls = classify_route("Холон", "Бат-Ям")
        assert cls.band == RouteBand.SAME_METRO

    def test_same_metro_kiryat_ata_to_haifa(self):
        """Haifa metro: Kiryat Ata (31) → Haifa (31)."""
        cls = classify_route("Кирьят-Ата", "Хайфа")
        assert cls.band == RouteBand.SAME_METRO

    # --- same_region ---

    def test_same_region_haifa_to_hadera(self):
        """Haifa macro: Haifa (31) → Hadera (32)."""
        cls = classify_route("Хайфа", "Хадера")
        assert cls.band == RouteBand.SAME_REGION

    def test_same_region_tel_aviv_to_netanya(self):
        """Center: Tel Aviv (51) → Netanya (41)."""
        cls = classify_route("Тель-Авив", "Нетания")
        assert cls.band == RouteBand.SAME_REGION

    def test_same_region_tel_aviv_to_rehovot(self):
        """Center: Tel Aviv (51) → Rehovot (44)."""
        cls = classify_route("Тель-Авив", "Реховот")
        assert cls.band == RouteBand.SAME_REGION

    def test_same_region_north_nahariya_to_carmiel(self):
        """North: Nahariya (24) → Carmiel (24)."""
        cls = classify_route("Нагария", "Кармиэль")
        assert cls.band in (RouteBand.SAME_CITY, RouteBand.SAME_METRO, RouteBand.SAME_REGION)

    # --- inter_region_short ---

    def test_inter_region_short_tel_aviv_to_jerusalem(self):
        """Center → Jerusalem = short."""
        cls = classify_route("Тель-Авив", "Иерусалим")
        assert cls.band == RouteBand.INTER_REGION_SHORT

    def test_inter_region_short_haifa_to_tel_aviv(self):
        """Haifa → Center = short."""
        cls = classify_route("Хайфа", "Тель-Авив")
        assert cls.band == RouteBand.INTER_REGION_SHORT

    def test_inter_region_short_jerusalem_to_center(self):
        """Jerusalem → Center = short."""
        cls = classify_route("Иерусалим", "Реховот")
        assert cls.band == RouteBand.INTER_REGION_SHORT

    # --- inter_region_long ---

    def test_inter_region_long_haifa_to_beer_sheva(self):
        """Haifa → South = long."""
        cls = classify_route("Хайфа", "Беэр-Шева")
        assert cls.band == RouteBand.INTER_REGION_LONG

    def test_inter_region_long_north_to_south(self):
        """North → South = long."""
        cls = classify_route("Нагария", "Ашдод")
        assert cls.band == RouteBand.INTER_REGION_LONG

    def test_inter_region_long_north_to_jerusalem(self):
        """North → Jerusalem = long."""
        cls = classify_route("Кармиэль", "Иерусалим")
        assert cls.band == RouteBand.INTER_REGION_LONG

    # --- extreme_distance ---

    def test_extreme_distance_haifa_to_eilat(self):
        cls = classify_route("Хайфа", "Эйлат")
        assert cls.band == RouteBand.EXTREME_DISTANCE

    def test_extreme_distance_tel_aviv_to_eilat(self):
        cls = classify_route("Тель-Авив", "Эйлат")
        assert cls.band == RouteBand.EXTREME_DISTANCE

    def test_extreme_distance_eilat_to_eilat(self):
        cls = classify_route("Эйлат", "Эйлат")
        assert cls.band == RouteBand.SAME_CITY  # same city takes priority

    def test_extreme_distance_eilat_to_beer_sheva(self):
        """Eilat → Beer Sheva = extreme despite same region."""
        cls = classify_route("Эйлат", "Беэр-Шева")
        assert cls.band == RouteBand.EXTREME_DISTANCE

    # --- fallback: unknown localities ---

    def test_unknown_from_returns_inter_region_short(self):
        cls = classify_route("Неизвестный город", "Хайфа")
        assert cls.band == RouteBand.INTER_REGION_SHORT
        assert cls.from_locality is None
        assert cls.to_locality is not None

    def test_both_unknown_returns_inter_region_short(self):
        cls = classify_route("Город X", "Город Y")
        assert cls.band == RouteBand.INTER_REGION_SHORT
        assert cls.from_locality is None
        assert cls.to_locality is None

    # --- result structure ---

    def test_result_has_region_codes(self):
        cls = classify_route("Хайфа", "Тель-Авив")
        assert cls.from_region == 31
        assert cls.to_region == 51

    def test_result_has_locality_names(self):
        cls = classify_route("Хайфа", "Тель-Авив")
        assert cls.from_locality == "חיפה"
        assert cls.to_locality == "תל אביב - יפו"

    def test_result_is_frozen(self):
        cls = classify_route("Хайфа", "Хайфа")
        with pytest.raises(AttributeError):
            cls.band = RouteBand.EXTREME_DISTANCE

    # --- English names ---

    def test_english_haifa_to_jerusalem(self):
        cls = classify_route("Haifa", "Jerusalem")
        assert cls.band == RouteBand.INTER_REGION_SHORT

    def test_english_tel_aviv_to_haifa(self):
        cls = classify_route("Tel Aviv", "Haifa")
        assert cls.band == RouteBand.INTER_REGION_SHORT
