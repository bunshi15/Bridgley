# tests/test_notification.py
"""Tests for notification formatting in app/infra/notification_service.py."""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest


# ============================================================================
# _format_extras
# ============================================================================

class TestFormatExtras:
    def test_none_returns_net(self):
        from app.infra.notification_service import _format_extras
        assert _format_extras(None) == "нет"

    def test_empty_list(self):
        from app.infra.notification_service import _format_extras
        # Empty list should return "нет"
        assert _format_extras([]) == "нет"

    def test_single_known_extra(self):
        from app.infra.notification_service import _format_extras
        assert _format_extras(["loaders"]) == "грузчики"

    def test_multiple_known_extras(self):
        from app.infra.notification_service import _format_extras
        result = _format_extras(["loaders", "assembly"])
        assert "грузчики" in result
        assert "сборка/разборка" in result

    def test_unknown_extra_passthrough(self):
        from app.infra.notification_service import _format_extras
        result = _format_extras(["custom_service"])
        assert result == "custom_service"

    def test_none_value_filtered(self):
        from app.infra.notification_service import _format_extras
        # "none" should be filtered out
        result = _format_extras(["none"])
        assert result == ""  # Only "none" was filtered


# ============================================================================
# _format_time_window
# ============================================================================

class TestFormatTimeWindow:
    def test_today(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("today")
        assert "сегодня" in result
        # Should contain date in DD/MM/YYYY format
        assert "/" in result

    def test_tomorrow(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("tomorrow")
        assert result == "завтра"

    def test_soon(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("soon")
        assert result == "в ближайшие дни"

    def test_unknown_passthrough(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("next_week")
        assert result == "next_week"

    def test_none_returns_default(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window(None)
        assert result == "не указано"

    # Phase 2: new time slot values
    def test_morning(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("morning")
        assert "утро" in result
        assert "08:00" in result

    def test_afternoon(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("afternoon")
        assert "день" in result
        assert "12:00" in result

    def test_evening(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("evening")
        assert "вечер" in result
        assert "16:00" in result

    def test_flexible(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("flexible")
        assert "не определено" in result

    def test_exact_time_format(self):
        from app.infra.notification_service import _format_time_window
        result = _format_time_window("exact:14:30")
        assert "14:30" in result
        assert "точное время" in result


# ============================================================================
# format_lead_message
# ============================================================================

class TestFormatLeadMessage:
    def test_basic_payload(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "addresses": "ул. Ленина 5 → пр. Мира 10",
            "time_window": "today",
        }
        result = format_lead_message("+79991234567", payload)
        assert "Диван" in result
        assert "ул. Ленина 5" in result
        assert "сегодня" in result
        assert "+79991234567" in result

    def test_payload_with_sender_name(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Стол",
            "custom": {"sender_name": "Ivan Petrov (@ivan)"},
        }
        result = format_lead_message("12345", payload)
        assert "Ivan Petrov (@ivan)" in result
        # Should NOT show the chat_id since sender_name is present
        assert "12345" not in result

    def test_payload_with_whatsapp_chat_id(self):
        from app.infra.notification_service import format_lead_message
        payload = {"cargo_description": "Кресло"}
        result = format_lead_message("whatsapp:+79990001122", payload)
        assert "+79990001122" in result
        assert "whatsapp:" not in result

    def test_payload_with_addr_from_to(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Шкаф",
            "addr_from": "ул. Мира 1",
            "addr_to": "ул. Мира 2",
            "floor_from": "3",
            "floor_to": "5",
        }
        result = format_lead_message("+79990001122", payload)
        assert "ул. Мира 1" in result
        assert "этаж: 3" in result
        assert "ул. Мира 2" in result
        assert "этаж: 5" in result

    def test_payload_with_photos(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Коробки",
            "photo_count": 3,
        }
        result = format_lead_message("+79990001122", payload)
        assert "3 шт" in result

    def test_payload_with_details(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Вещи",
            "details_free": "Осторожно, хрупкое",
        }
        result = format_lead_message("+79990001122", payload)
        assert "Осторожно, хрупкое" in result

    def test_minimal_payload(self):
        from app.infra.notification_service import format_lead_message
        payload = {}
        result = format_lead_message("+79990001122", payload)
        # Should have defaults
        assert "не указано" in result
        assert "Новая заявка" in result

    def test_nested_data_key(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "data": {
                "cargo_description": "Пианино",
                "time_window": "tomorrow",
            }
        }
        result = format_lead_message("+79990001122", payload)
        assert "Пианино" in result
        assert "завтра" in result

    def test_payload_with_move_date(self):
        """Phase 2: move_date from custom dict is included in date line."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Стол",
            "time_window": "morning",
            "custom": {"move_date": "2026-03-15"},
        }
        result = format_lead_message("+79990001122", payload)
        assert "2026-03-15" in result
        assert "утро" in result

    def test_payload_with_exact_time(self):
        """Phase 2: exact:HH:MM format in time_window."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Коробки",
            "time_window": "exact:14:30",
            "custom": {"move_date": "2026-04-01"},
        }
        result = format_lead_message("+79990001122", payload)
        assert "2026-04-01" in result
        assert "14:30" in result
        assert "точное время" in result

    # Phase 3: pricing estimate in notification
    def test_payload_with_estimate(self):
        """Phase 3: estimate range shown in notification."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Шкаф и диван",
            "time_window": "morning",
            "custom": {
                "move_date": "2026-03-20",
                "estimate_min": 272,
                "estimate_max": 368,
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "272" in result
        assert "368" in result
        assert "₪" in result
        assert "Оценка" in result

    def test_payload_without_estimate(self):
        """Phase 3: no estimate → no estimate line."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Коробки",
            "custom": {},
        }
        result = format_lead_message("+79990001122", payload)
        assert "Оценка" not in result


# ============================================================================
# _mask_phone
# ============================================================================

class TestMaskPhone:
    def test_normal_phone(self):
        from app.infra.notification_service import _mask_phone
        result = _mask_phone("+79991234567")
        assert result.startswith("+799")
        assert result.endswith("4567")
        assert "***" in result

    def test_short_phone(self):
        from app.infra.notification_service import _mask_phone
        assert _mask_phone("12345") == "***"

    def test_empty_phone(self):
        from app.infra.notification_service import _mask_phone
        assert _mask_phone("") == "***"

    def test_whatsapp_prefix(self):
        from app.infra.notification_service import _mask_phone
        result = _mask_phone("whatsapp:+79991234567")
        assert "whatsapp" not in result
        assert "***" in result


class TestMaskCoordinates:
    """Test GPS coordinate masking for logs."""

    def test_masks_precision(self):
        from app.infra.logging_config import mask_coordinates
        result = mask_coordinates(32.794, 34.989)
        assert result == "32.8**, 35.0**"

    def test_does_not_expose_full_coords(self):
        from app.infra.logging_config import mask_coordinates
        result = mask_coordinates(32.81144, 34.99792)
        assert "32.811" not in result
        assert "34.997" not in result

    def test_negative_coords(self):
        from app.infra.logging_config import mask_coordinates
        result = mask_coordinates(-33.8688, 151.2093)
        assert result == "-33.9**, 151.2**"


# ============================================================================
# Tenant-aware notify_operator (v0.8.1)
# ============================================================================

class TestNotifyOperatorTenantAware:
    """Test that notify_operator passes tenant_id through the chain."""

    @pytest.mark.asyncio
    async def test_notify_operator_passes_tenant_id(self, monkeypatch):
        """tenant_id flows through to get_notification_channel."""
        from app.infra.notification_service import notify_operator

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")
        monkeypatch.setattr("app.config.settings.tenant_id", "global_t")

        mock_channel = MagicMock()
        mock_channel.name = "whatsapp"
        mock_channel.send = AsyncMock(return_value=True)

        with patch(
            "app.infra.notification_channels.get_notification_channel",
            return_value=mock_channel,
        ) as mock_get_ch:
            with patch(
                "app.infra.notification_service._get_photo_urls_for_lead",
                new_callable=AsyncMock,
                return_value=[],
            ):
                result = await notify_operator(
                    "lead1", "+79990001122",
                    {"cargo_description": "boxes"},
                    tenant_id="custom_tenant",
                )

        assert result is True
        mock_get_ch.assert_called_once_with(tenant_id="custom_tenant")
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_operator_tenant_disabled(self, monkeypatch):
        """Tenant with operator_notifications_enabled=False → skipped."""
        from app.infra.notification_service import notify_operator
        from app.infra.tenant_registry import TenantContext, reset_cache
        import app.infra.tenant_registry as reg

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")

        reg._cache = {
            "t_disabled": TenantContext(
                "t_disabled", "Disabled", True,
                config={"operator_notifications_enabled": False},
            ),
        }

        result = await notify_operator(
            "lead1", "+79990001122",
            {"cargo_description": "boxes"},
            tenant_id="t_disabled",
        )

        # Should return True (not an error, just disabled)
        assert result is True
        reset_cache()

    @pytest.mark.asyncio
    async def test_notify_operator_fallback_global(self, monkeypatch):
        """No tenant config → uses settings.* (global fallback)."""
        from app.infra.notification_service import notify_operator

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")
        monkeypatch.setattr("app.config.settings.tenant_id", "global_t")

        mock_channel = MagicMock()
        mock_channel.name = "whatsapp"
        mock_channel.send = AsyncMock(return_value=True)

        with patch(
            "app.infra.notification_channels.get_notification_channel",
            return_value=mock_channel,
        ) as mock_get_ch:
            with patch(
                "app.infra.notification_service._get_photo_urls_for_lead",
                new_callable=AsyncMock,
                return_value=[],
            ):
                result = await notify_operator(
                    "lead1", "+79990001122",
                    {"cargo_description": "boxes"},
                    # No tenant_id — defaults to None
                )

        assert result is True
        mock_get_ch.assert_called_once_with(tenant_id=None)


# ============================================================================
# Phase 4: Multi-pickup notification formatting
# ============================================================================

class TestMultiPickupNotification:
    """Test notification formatting with 1, 2, and 3 pickups."""

    def test_single_pickup_unchanged(self):
        """Single pickup (no pickups in custom or len<=1) → old format."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "addr_from": "Хайфа, Герцль 10",
            "floor_from": "3 этаж",
            "addr_to": "Тель-Авив, Дизенгоф 50",
            "floor_to": "5 этаж",
            "custom": {
                "pickups": [{"addr": "Хайфа, Герцль 10", "floor": "3 этаж"}],
            },
        }
        result = format_lead_message("+79990001122", payload)
        # Single pickup → old format "addr → addr"
        assert "Адрес:" in result
        assert "Адреса:" not in result
        assert "Хайфа, Герцль 10" in result
        assert "Тель-Авив, Дизенгоф 50" in result

    def test_two_pickups_multiline(self):
        """2 pickups → multi-line format with numbered pickups."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Шкаф",
            "addr_from": "Хайфа, Герцль 10",
            "floor_from": "3 этаж",
            "addr_to": "Тель-Авив, Дизенгоф 50",
            "floor_to": "2 этаж",
            "custom": {
                "pickups": [
                    {"addr": "Хайфа, Герцль 10", "floor": "3 этаж"},
                    {"addr": "Хайфа, Бен-Гурион 5", "floor": "1 этаж"},
                ],
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Адреса:" in result
        assert "Забор 1:" in result
        assert "Хайфа, Герцль 10" in result
        assert "Забор 2:" in result
        assert "Хайфа, Бен-Гурион 5" in result
        assert "Доставка:" in result
        assert "Тель-Авив, Дизенгоф 50" in result

    def test_three_pickups_multiline(self):
        """3 pickups → multi-line format."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Коробки",
            "addr_from": "Хайфа, Герцль 10",
            "addr_to": "Тель-Авив, Центр",
            "floor_to": "4 этаж",
            "custom": {
                "pickups": [
                    {"addr": "Хайфа, Герцль 10", "floor": "3 этаж"},
                    {"addr": "Хайфа, Бен-Гурион 5", "floor": "1 этаж"},
                    {"addr": "Кармиэль, центр", "floor": "2 этаж"},
                ],
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Адреса:" in result
        assert "Забор 1:" in result
        assert "Забор 2:" in result
        assert "Забор 3:" in result
        assert "Доставка:" in result
        assert "Кармиэль, центр" in result

    def test_no_pickups_in_custom_uses_old_format(self):
        """No pickups key in custom → old format (backward compat)."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Стол",
            "addr_from": "ул. Мира 1",
            "addr_to": "ул. Мира 2",
            "custom": {},
        }
        result = format_lead_message("+79990001122", payload)
        assert "Адрес:" in result
        assert "Адреса:" not in result
        assert "ул. Мира 1" in result

    def test_multi_pickup_with_estimate(self):
        """Multi-pickup + estimate both show in notification."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "addr_from": "Хайфа, Герцль 10",
            "addr_to": "Тель-Авив, Дизенгоф 50",
            "floor_to": "2 этаж",
            "custom": {
                "pickups": [
                    {"addr": "Хайфа, Герцль 10", "floor": "3 этаж"},
                    {"addr": "Хайфа, Бен-Гурион 5", "floor": "1 этаж"},
                ],
                "estimate_min": 331,
                "estimate_max": 449,
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Адреса:" in result
        assert "Забор 1:" in result
        assert "331" in result
        assert "449" in result
        assert "₪" in result


# ============================================================================
# Phase 5: Geo point notification formatting
# ============================================================================

class TestGeoPointNotification:
    """Test notification formatting with geo points."""

    def test_geo_points_shown_as_map_links(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "addr_from": "📍 32.79400, 34.98900",
            "floor_from": "3 этаж",
            "addr_to": "Тель-Авив, Дизенгоф 50",
            "floor_to": "2 этаж",
            "custom": {
                "pickups": [{"addr": "📍 32.79400, 34.98900", "floor": "3 этаж"}],
                "geo_points": {
                    "pickup_1": {"lat": 32.794, "lon": 34.989},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Геоточки:" in result
        assert "maps.google.com" in result
        assert "32.794" in result
        assert "34.989" in result

    def test_no_geo_points_no_section(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Стол",
            "addr_from": "Хайфа, Герцль 10",
            "addr_to": "Тель-Авив, Дизенгоф 50",
            "custom": {},
        }
        result = format_lead_message("+79990001122", payload)
        assert "Геоточки:" not in result
        assert "maps.google.com" not in result

    def test_mixed_geo_and_text(self):
        """One pickup with geo, delivery with text → only pickup geo shown."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Шкаф",
            "addr_from": "📍 32.79400, 34.98900",
            "addr_to": "Тель-Авив, Центр",
            "floor_to": "5 этаж",
            "custom": {
                "pickups": [{"addr": "📍 32.79400, 34.98900", "floor": "3 этаж"}],
                "geo_points": {
                    "pickup_1": {"lat": 32.794, "lon": 34.989},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Геоточки:" in result
        assert "Pickup 1:" in result
        # No delivery geo
        assert result.count("maps.google.com") == 1

    def test_multiple_geo_points(self):
        """Multiple geo points: pickup + delivery."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Коробки",
            "addr_from": "📍 32.79400, 34.98900",
            "addr_to": "📍 32.08000, 34.78000",
            "custom": {
                "pickups": [{"addr": "📍 32.79400, 34.98900", "floor": "1 этаж"}],
                "geo_points": {
                    "pickup_1": {"lat": 32.794, "lon": 34.989},
                    "delivery": {"lat": 32.080, "lon": 34.780},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Геоточки:" in result
        assert result.count("maps.google.com") == 2


# ============================================================================
# Reverse geocoding: enriched geo notification tests
# ============================================================================

class TestGeoWithAddress:
    """Test notification formatting when geo points have geocoded addresses."""

    def test_geo_with_address_shows_address_and_link(self):
        """Geocoded address appears above map link."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "addr_from": "📍 Herzl 10, Haifa",
            "addr_to": "Тель-Авив, Дизенгоф 50",
            "custom": {
                "pickups": [{"addr": "📍 Herzl 10, Haifa", "floor": "3 этаж"}],
                "geo_points": {
                    "pickup_1": {
                        "lat": 32.794, "lon": 34.989,
                        "address": "Herzl 10, Haifa",
                    },
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Геоточки:" in result
        assert "Herzl 10, Haifa" in result
        assert "maps.google.com" in result

    def test_geo_with_name_shows_name_and_link(self):
        """Name from adapter (e.g. Telegram venue) shown above map link."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Стол",
            "addr_from": "📍 Haifa Port",
            "addr_to": "Тель-Авив",
            "custom": {
                "pickups": [{"addr": "📍 Haifa Port", "floor": "1 этаж"}],
                "geo_points": {
                    "pickup_1": {
                        "lat": 32.820, "lon": 34.990,
                        "name": "Haifa Port",
                    },
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Haifa Port" in result
        assert "maps.google.com" in result

    def test_geo_without_address_shows_link_only(self):
        """No address/name → only map link (backward compat)."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Коробки",
            "addr_from": "📍 32.79400, 34.98900",
            "addr_to": "Тель-Авив",
            "custom": {
                "pickups": [{"addr": "📍 32.79400, 34.98900", "floor": "1 этаж"}],
                "geo_points": {
                    "pickup_1": {"lat": 32.794, "lon": 34.989},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Геоточки:" in result
        assert "maps.google.com" in result
        # No separate address line — just the link
        lines = result.split("\n")
        geo_line = [l for l in lines if "Pickup 1:" in l][0]
        assert "maps.google.com" in geo_line

    def test_mixed_geo_with_and_without_address(self):
        """Pickup has address, delivery doesn't → mixed display."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Шкаф",
            "addr_from": "📍 Herzl 10, Haifa",
            "addr_to": "📍 32.08000, 34.78000",
            "custom": {
                "pickups": [{"addr": "📍 Herzl 10, Haifa", "floor": "3 этаж"}],
                "geo_points": {
                    "pickup_1": {
                        "lat": 32.794, "lon": 34.989,
                        "address": "Herzl 10, Haifa",
                    },
                    "delivery": {"lat": 32.080, "lon": 34.780},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Herzl 10, Haifa" in result
        assert result.count("maps.google.com") == 2


# ============================================================================
# Phase 8: Region classification in notification
# ============================================================================


class TestRegionNotification:
    """Phase 8: region classification in operator notification."""

    def test_inside_metro_label(self):
        """All inside metro -> shows metro label."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "custom": {
                "region_classifications": {
                    "pickup_1": {"inside_metro": True, "distance_km": 3.0, "distance_factor": 1.0},
                    "delivery": {"inside_metro": True, "distance_km": 5.0, "distance_factor": 1.0},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "Агломерация большой Хайфы" in result
        assert "за пределами" not in result

    def test_outside_metro_warning(self):
        """Any outside metro -> shows warning."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Шкаф",
            "custom": {
                "region_classifications": {
                    "pickup_1": {"inside_metro": True, "distance_km": 3.0, "distance_factor": 1.0},
                    "delivery": {"inside_metro": False, "distance_km": 95.0, "distance_factor": 1.2},
                },
            },
        }
        result = format_lead_message("+79990001122", payload)
        assert "за пределами" in result

    def test_no_region_info_no_line(self):
        """No region_classifications -> no region line at all."""
        from app.infra.notification_service import format_lead_message
        payload = {"cargo_description": "Стол", "custom": {}}
        result = format_lead_message("+79990001122", payload)
        assert "Зона" not in result


# ============================================================================
# Notification provider switch: _normalize_whatsapp_number
# ============================================================================

class TestNormalizeWhatsAppNumber:
    """Tests for provider-specific number normalization."""

    def test_twilio_with_plus(self):
        from app.infra.notification_channels import _normalize_whatsapp_number
        result = _normalize_whatsapp_number("+972501234567", "twilio")
        assert result == "whatsapp:+972501234567"

    def test_twilio_without_plus(self):
        from app.infra.notification_channels import _normalize_whatsapp_number
        result = _normalize_whatsapp_number("972501234567", "twilio")
        assert result == "whatsapp:+972501234567"

    def test_twilio_with_whatsapp_prefix(self):
        from app.infra.notification_channels import _normalize_whatsapp_number
        result = _normalize_whatsapp_number("whatsapp:+972501234567", "twilio")
        assert result == "whatsapp:+972501234567"

    def test_meta_with_plus(self):
        from app.infra.notification_channels import _normalize_whatsapp_number
        result = _normalize_whatsapp_number("+972501234567", "meta")
        assert result == "972501234567"

    def test_meta_without_plus(self):
        from app.infra.notification_channels import _normalize_whatsapp_number
        result = _normalize_whatsapp_number("972501234567", "meta")
        assert result == "972501234567"

    def test_meta_with_whatsapp_prefix(self):
        from app.infra.notification_channels import _normalize_whatsapp_number
        result = _normalize_whatsapp_number("whatsapp:+972501234567", "meta")
        assert result == "972501234567"


# ============================================================================
# Notification provider switch: WhatsAppChannel.is_configured()
# ============================================================================

class TestWhatsAppChannelIsConfigured:
    """Tests for provider-dependent is_configured() logic."""

    def test_twilio_configured(self, monkeypatch):
        from app.infra.notification_channels import WhatsAppChannel
        monkeypatch.setattr("app.config.settings.twilio_phone_number", "+15551234567")
        monkeypatch.setattr("app.config.settings.twilio_account_sid", "ACxxx")
        monkeypatch.setattr("app.config.settings.twilio_auth_token", "tok123")
        ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="twilio")
        assert ch.is_configured() is True

    def test_twilio_not_configured(self, monkeypatch):
        from app.infra.notification_channels import WhatsAppChannel
        monkeypatch.setattr("app.config.settings.twilio_phone_number", "")
        monkeypatch.setattr("app.config.settings.twilio_account_sid", "")
        monkeypatch.setattr("app.config.settings.twilio_auth_token", "")
        ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="twilio")
        assert ch.is_configured() is False

    def test_meta_configured(self, monkeypatch):
        from app.infra.notification_channels import WhatsAppChannel
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
        assert ch.is_configured() is True

    def test_meta_not_configured_no_token(self, monkeypatch):
        from app.infra.notification_channels import WhatsAppChannel
        monkeypatch.setattr("app.config.settings.meta_access_token", "")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
        assert ch.is_configured() is False

    def test_meta_not_configured_no_phone_id(self, monkeypatch):
        from app.infra.notification_channels import WhatsAppChannel
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "")
        ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
        assert ch.is_configured() is False

    def test_no_operator_whatsapp(self, monkeypatch):
        from app.infra.notification_channels import WhatsAppChannel
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "")
        ch = WhatsAppChannel(operator_whatsapp="", provider="twilio")
        assert ch.is_configured() is False


# ============================================================================
# Notification provider switch: WhatsAppChannel.send() via Meta
# ============================================================================

class TestWhatsAppChannelSendMeta:
    """Tests for Meta provider send path."""

    @pytest.mark.asyncio
    async def test_send_meta_text_success(self, monkeypatch):
        """Meta send: text message delivered successfully."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_send_text = AsyncMock()
        mock_send_media = AsyncMock()

        with patch("app.transport.meta_sender.send_text_message", mock_send_text), \
             patch("app.transport.meta_sender.send_media_message", mock_send_media):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(
                lead_id="lead1", chat_id="chat1", body="Test notification",
            )
            result = await ch.send(notif)

        assert result is True
        mock_send_text.assert_called_once_with("972501234567", "Test notification")
        mock_send_media.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_meta_with_photos(self, monkeypatch):
        """Meta send: text + photos as separate media messages."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_send_text = AsyncMock()
        mock_send_media = AsyncMock()

        with patch("app.transport.meta_sender.send_text_message", mock_send_text), \
             patch("app.transport.meta_sender.send_media_message", mock_send_media):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(
                lead_id="lead1", chat_id="chat1", body="Text",
                photo_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
            )
            result = await ch.send(notif)

        assert result is True
        mock_send_text.assert_called_once()
        assert mock_send_media.call_count == 2
        mock_send_media.assert_any_call("972501234567", "image", "https://example.com/1.jpg")
        mock_send_media.assert_any_call("972501234567", "image", "https://example.com/2.jpg")

    @pytest.mark.asyncio
    async def test_send_meta_text_error_returns_false(self, monkeypatch):
        """Meta send: MetaSendError on text → returns False."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        from app.transport.meta_sender import MetaSendError
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_send_text = AsyncMock(side_effect=MetaSendError(401, 190, "token expired", retryable=False))

        with patch("app.transport.meta_sender.send_text_message", mock_send_text):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(
                lead_id="lead1", chat_id="chat1", body="Text",
            )
            result = await ch.send(notif)

        assert result is False

    @pytest.mark.asyncio
    async def test_send_meta_photo_error_continues(self, monkeypatch):
        """Meta send: photo failure does not fail entire notification."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_send_text = AsyncMock()
        mock_send_media = AsyncMock(side_effect=Exception("network error"))

        with patch("app.transport.meta_sender.send_text_message", mock_send_text), \
             patch("app.transport.meta_sender.send_media_message", mock_send_media):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(
                lead_id="lead1", chat_id="chat1", body="Text",
                photo_urls=["https://example.com/1.jpg"],
            )
            result = await ch.send(notif)

        # Text sent OK → result True, despite photo failure
        assert result is True


# ============================================================================
# Notification provider switch: WhatsAppChannel.send() via Twilio
# ============================================================================

class TestWhatsAppChannelSendTwilio:
    """Tests for Twilio provider send path (queue-based)."""

    @pytest.mark.asyncio
    async def test_send_twilio_enqueues(self, monkeypatch):
        """Twilio send: enqueues text + photo messages into outbound queue."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        monkeypatch.setattr("app.config.settings.twilio_phone_number", "+15551234567")
        monkeypatch.setattr("app.config.settings.twilio_account_sid", "ACxxx")
        monkeypatch.setattr("app.config.settings.twilio_auth_token", "tok123")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_queue = MagicMock()
        mock_queue.enqueue = AsyncMock()
        mock_queue.process_queue = AsyncMock()

        with patch("app.infra.outbound_queue.get_outbound_queue", return_value=mock_queue):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="twilio")
            notif = OperatorNotification(
                lead_id="lead1", chat_id="chat1", body="Test text",
                photo_urls=["https://example.com/1.jpg"],
            )
            result = await ch.send(notif)

        assert result is True
        # 1 text + 1 photo = 2 enqueue calls
        assert mock_queue.enqueue.call_count == 2

    @pytest.mark.asyncio
    async def test_send_twilio_not_configured_returns_false(self, monkeypatch):
        """Twilio send: missing creds → returns False."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        monkeypatch.setattr("app.config.settings.twilio_phone_number", "")
        monkeypatch.setattr("app.config.settings.twilio_account_sid", "")
        monkeypatch.setattr("app.config.settings.twilio_auth_token", "")

        ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="twilio")
        notif = OperatorNotification(
            lead_id="lead1", chat_id="chat1", body="Text",
        )
        result = await ch.send(notif)

        assert result is False


# ============================================================================
# Notification provider switch: get_notification_channel() factory
# ============================================================================

class TestGetNotificationChannelFactory:
    """Tests for factory provider passthrough."""

    def test_factory_passes_meta_provider(self, monkeypatch):
        from app.infra.notification_channels import get_notification_channel, WhatsAppChannel
        from app.infra.tenant_registry import TenantContext, reset_cache
        import app.infra.tenant_registry as reg

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+972501234567")
        monkeypatch.setattr("app.config.settings.operator_whatsapp_provider", "twilio")

        reg._cache = {
            "meta_tenant": TenantContext(
                "meta_tenant", "Meta Op", True,
                config={"operator_whatsapp_provider": "meta"},
            ),
        }

        ch = get_notification_channel(tenant_id="meta_tenant")
        assert isinstance(ch, WhatsAppChannel)
        assert ch._provider == "meta"
        reset_cache()

    def test_factory_defaults_to_twilio(self, monkeypatch):
        from app.infra.notification_channels import get_notification_channel, WhatsAppChannel

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+972501234567")
        monkeypatch.setattr("app.config.settings.operator_whatsapp_provider", "twilio")

        ch = get_notification_channel(tenant_id=None)
        assert isinstance(ch, WhatsAppChannel)
        assert ch._provider == "twilio"


# ============================================================================
# Phase 4: Operational Hardening — Meta retry & error classification
# ============================================================================

class TestMetaRetryBehavior:
    """Phase 4: retry logic in _send_via_meta."""

    @pytest.mark.asyncio
    async def test_retryable_error_retried_once(self, monkeypatch):
        """Retryable MetaSendError (429) → retried once, succeeds on 2nd attempt."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        from app.transport.meta_sender import MetaSendError
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")
        # Speed up test: no actual sleep
        monkeypatch.setattr("app.infra.notification_channels._META_RETRY_DELAY_S", 0)

        call_count = 0

        async def mock_send_text(to, text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise MetaSendError(429, 4, "rate limited", retryable=True)
            return {"messages": [{"id": "msg123"}]}

        with patch("app.transport.meta_sender.send_text_message", side_effect=mock_send_text):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(lead_id="lead1", chat_id="chat1", body="Hi")
            result = await ch.send(notif)

        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retryable_error_exhausts_attempts(self, monkeypatch):
        """Retryable error on all attempts → returns False."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        from app.transport.meta_sender import MetaSendError
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")
        monkeypatch.setattr("app.infra.notification_channels._META_RETRY_DELAY_S", 0)

        mock_send_text = AsyncMock(
            side_effect=MetaSendError(429, 4, "rate limited", retryable=True)
        )

        with patch("app.transport.meta_sender.send_text_message", mock_send_text):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(lead_id="lead1", chat_id="chat1", body="Hi")
            result = await ch.send(notif)

        assert result is False
        # 2 attempts total (_META_MAX_ATTEMPTS = 2)
        assert mock_send_text.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_retry(self, monkeypatch):
        """Non-retryable error (auth 401) → fails immediately, no retry."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        from app.transport.meta_sender import MetaSendError
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")
        monkeypatch.setattr("app.infra.notification_channels._META_RETRY_DELAY_S", 0)

        mock_send_text = AsyncMock(
            side_effect=MetaSendError(401, 190, "token expired", retryable=False)
        )

        with patch("app.transport.meta_sender.send_text_message", mock_send_text):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(lead_id="lead1", chat_id="chat1", body="Hi")
            result = await ch.send(notif)

        assert result is False
        # Only 1 call — no retry for non-retryable
        assert mock_send_text.call_count == 1

    @pytest.mark.asyncio
    async def test_unexpected_exception_no_retry(self, monkeypatch):
        """Generic Exception → fails immediately, no retry."""
        from app.infra.notification_channels import WhatsAppChannel, OperatorNotification
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_send_text = AsyncMock(side_effect=RuntimeError("unexpected"))

        with patch("app.transport.meta_sender.send_text_message", mock_send_text):
            ch = WhatsAppChannel(operator_whatsapp="+972501234567", provider="meta")
            notif = OperatorNotification(lead_id="lead1", chat_id="chat1", body="Hi")
            result = await ch.send(notif)

        assert result is False
        assert mock_send_text.call_count == 1


# ============================================================================
# Twilio WhatsApp Content Template Fallback (63016 — outside 24h window)
# ============================================================================


def _make_twilio_63016():
    """Create a mock Twilio exception with error code 63016."""
    exc = Exception("Failed to send freeform message because you are outside the allowed window.")
    exc.code = 63016
    return exc


def _make_outbound_message(*, body="Test body", media_urls=None, metadata=None):
    """Helper to create an OutboundMessage for template fallback tests."""
    from app.infra.outbound_queue import OutboundMessage
    return OutboundMessage(
        id="test-msg-001",
        to="whatsapp:+972501234567",
        body=body,
        media_urls=media_urls or [],
        metadata=metadata or {},
    )


class TestTwilioTemplateFallback:
    """Tests for 63016 template fallback in _send_twilio_message."""

    @pytest.mark.asyncio
    async def test_63016_triggers_template_fallback(self, monkeypatch):
        """Error 63016 → falls back to content template with content_sid."""
        from app.infra.notification_service import _send_twilio_message

        monkeypatch.setattr("app.config.settings.twilio_phone_number", "whatsapp:+15551234567")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_client = MagicMock()
        # First call: raise 63016, second call (template): succeed
        mock_result = MagicMock()
        mock_result.sid = "SM_template_001"
        mock_client.messages.create.side_effect = [
            _make_twilio_63016(),
            mock_result,
        ]

        msg = _make_outbound_message(
            body="Lead notification text",
            metadata={
                "twilio_content_sid": "HX_test_content_sid",
                "template_vars": {
                    "contact": "+972501234567",
                    "cargo": "Диван",
                    "addr_from": "Хайфа",
                    "addr_to": "Тель-Авив",
                    "estimate": "300–400 ₪",
                },
            },
        )

        with patch("app.infra.notification_service._get_twilio_client", return_value=mock_client):
            result = await _send_twilio_message(msg)

        assert result is True
        # Second call should use content_sid instead of body
        template_call = mock_client.messages.create.call_args_list[1]
        assert template_call.kwargs.get("content_sid") == "HX_test_content_sid"
        assert "body" not in template_call.kwargs
        assert "content_variables" in template_call.kwargs

    @pytest.mark.asyncio
    async def test_63016_no_template_sid_returns_true(self, monkeypatch):
        """Error 63016 + no TWILIO_CONTENT_SID → returns True (stops retries)."""
        from app.infra.notification_service import _send_twilio_message

        monkeypatch.setattr("app.config.settings.twilio_phone_number", "whatsapp:+15551234567")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _make_twilio_63016()

        msg = _make_outbound_message(
            body="Lead notification",
            metadata={},  # No twilio_content_sid
        )

        with patch("app.infra.notification_service._get_twilio_client", return_value=mock_client):
            result = await _send_twilio_message(msg)

        # Returns True to stop futile retries
        assert result is True
        # Only 1 call (the freeform attempt), no template call
        assert mock_client.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_63016_photo_only_skipped(self, monkeypatch):
        """Error 63016 on photo-only message → skip template, return True."""
        from app.infra.notification_service import _send_twilio_message

        monkeypatch.setattr("app.config.settings.twilio_phone_number", "whatsapp:+15551234567")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _make_twilio_63016()

        msg = _make_outbound_message(
            body="",  # Photo-only message
            media_urls=["https://example.com/photo.jpg"],
            metadata={"twilio_content_sid": "HX_test_sid"},
        )

        with patch("app.infra.notification_service._get_twilio_client", return_value=mock_client):
            result = await _send_twilio_message(msg)

        assert result is True
        # Only 1 call (the freeform photo attempt)
        assert mock_client.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_63016_template_also_fails(self, monkeypatch):
        """Error 63016 → template fallback also fails → returns False."""
        from app.infra.notification_service import _send_twilio_message

        monkeypatch.setattr("app.config.settings.twilio_phone_number", "whatsapp:+15551234567")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_client = MagicMock()
        # Both calls fail
        mock_client.messages.create.side_effect = [
            _make_twilio_63016(),
            Exception("Template SID invalid"),
        ]

        msg = _make_outbound_message(
            body="Lead text",
            metadata={
                "twilio_content_sid": "HX_bad_sid",
                "template_vars": {"contact": "test"},
            },
        )

        with patch("app.infra.notification_service._get_twilio_client", return_value=mock_client):
            result = await _send_twilio_message(msg)

        assert result is False
        assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_non_63016_unchanged(self, monkeypatch):
        """Non-63016 errors still follow existing retry path (return False)."""
        from app.infra.notification_service import _send_twilio_message

        monkeypatch.setattr("app.config.settings.twilio_phone_number", "whatsapp:+15551234567")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        mock_client = MagicMock()
        exc = Exception("Some transient error")
        exc.code = 99999
        mock_client.messages.create.side_effect = exc

        msg = _make_outbound_message(body="Test")

        with patch("app.infra.notification_service._get_twilio_client", return_value=mock_client):
            result = await _send_twilio_message(msg)

        assert result is False
        # No template fallback attempted
        assert mock_client.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_template_vars_populated(self, monkeypatch):
        """notify_operator() populates template_vars in notification metadata."""
        from app.infra.notification_service import notify_operator

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+972501234567")
        monkeypatch.setattr("app.config.settings.operator_whatsapp_provider", "twilio")
        monkeypatch.setattr("app.config.settings.twilio_content_sid", None)
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        captured_notification = {}

        async def mock_send(notification):
            captured_notification["metadata"] = notification.metadata
            return True

        mock_channel = MagicMock()
        mock_channel.name = "whatsapp"
        mock_channel.send = mock_send

        payload = {
            "data": {
                "cargo_description": "Диван и 5 коробок",
                "addr_from": "Хайфа, Герцль 10",
                "addr_to": "Тель-Авив, Дизенгоф 50",
                "custom": {
                    "estimate_min": 300,
                    "estimate_max": 400,
                },
            }
        }

        with patch("app.infra.notification_channels.get_notification_channel", return_value=mock_channel):
            result = await notify_operator("lead123", "whatsapp:+972507777777", payload, tenant_id="test_t")

        assert result is True
        tv = captured_notification["metadata"]["template_vars"]
        assert tv["contact"] == "+972507777777"
        assert tv["cargo"] == "Диван и 5 коробок"
        assert tv["addr_from"] == "Хайфа, Герцль 10"
        assert tv["addr_to"] == "Тель-Авив, Дизенгоф 50"
        assert tv["estimate"] == "300–400 ₪"
