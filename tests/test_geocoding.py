# tests/test_geocoding.py
"""
Tests for the Nominatim reverse geocoding service.

All tests mock the HTTP layer — no actual Nominatim API calls.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.infra.geocoding import reverse_geocode, _format_address


# ============================================================================
# _format_address() unit tests
# ============================================================================

class TestFormatAddress:
    """Tests for the address formatting helper."""

    def test_road_and_city(self):
        data = {
            "address": {
                "road": "Herzl Street",
                "house_number": "10",
                "city": "Haifa",
                "country": "Israel",
            },
            "display_name": "10, Herzl Street, Hadar, Haifa, Israel",
        }
        assert _format_address(data) == "Herzl Street 10, Haifa"

    def test_road_without_house_number(self):
        data = {
            "address": {
                "road": "Ben Gurion Boulevard",
                "city": "Haifa",
            },
        }
        assert _format_address(data) == "Ben Gurion Boulevard, Haifa"

    def test_city_only(self):
        data = {
            "address": {
                "city": "Haifa",
                "country": "Israel",
            },
        }
        assert _format_address(data) == "Haifa"

    def test_town_instead_of_city(self):
        data = {
            "address": {
                "road": "Main St",
                "town": "Kiryat Ata",
            },
        }
        assert _format_address(data) == "Main St, Kiryat Ata"

    def test_village(self):
        data = {
            "address": {
                "road": "HaShalom",
                "village": "Daliyat al-Karmel",
            },
        }
        assert _format_address(data) == "HaShalom, Daliyat al-Karmel"

    def test_municipality_fallback(self):
        data = {
            "address": {
                "road": "Industrial Rd",
                "municipality": "Krayot",
            },
        }
        assert _format_address(data) == "Industrial Rd, Krayot"

    def test_suburb_fallback(self):
        """When no city/town/village/municipality, suburb is used."""
        data = {
            "address": {
                "road": "Derekh HaYam",
                "suburb": "Bat Galim",
            },
        }
        assert _format_address(data) == "Derekh HaYam, Bat Galim"

    def test_pedestrian_road(self):
        data = {
            "address": {
                "pedestrian": "Midrahov Ben Gurion",
                "city": "Haifa",
            },
        }
        assert _format_address(data) == "Midrahov Ben Gurion, Haifa"

    def test_no_structured_address_uses_display_name(self):
        data = {
            "address": {},
            "display_name": "Haifa, Haifa District, Israel",
        }
        assert _format_address(data) == "Haifa, Haifa District, Israel"

    def test_long_display_name_truncated(self):
        long_name = "A" * 100
        data = {
            "address": {},
            "display_name": long_name,
        }
        result = _format_address(data)
        assert len(result) == 80
        assert result.endswith("...")

    def test_display_name_under_80_not_truncated(self):
        name = "Short address, City, Country"
        data = {
            "address": {},
            "display_name": name,
        }
        assert _format_address(data) == name

    def test_empty_data_returns_none(self):
        assert _format_address({}) is None

    def test_no_address_no_display_name(self):
        data = {"address": {}}
        assert _format_address(data) is None


# ============================================================================
# reverse_geocode() async tests
# ============================================================================

def _make_mock_response(status=200, json_data=None):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    # Make it usable as async context manager
    return resp


def _make_mock_session(response):
    """Create a mock session whose .get() returns the given response."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


class TestReverseGeocode:
    """Tests for the async reverse_geocode() function."""

    @pytest.mark.asyncio
    async def test_success_with_structured_address(self):
        """Successful geocoding returns formatted address."""
        json_data = {
            "address": {
                "road": "Herzl Street",
                "house_number": "10",
                "city": "Haifa",
            },
            "display_name": "10, Herzl Street, Hadar, Haifa, Israel",
        }
        mock_resp = _make_mock_response(200, json_data)
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            result = await reverse_geocode(32.794, 34.989)

        assert result == "Herzl Street 10, Haifa"

    @pytest.mark.asyncio
    async def test_success_with_display_name_only(self):
        """When no structured address, falls back to display_name."""
        json_data = {
            "address": {},
            "display_name": "Haifa, Haifa District, Israel",
        }
        mock_resp = _make_mock_response(200, json_data)
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            result = await reverse_geocode(32.794, 34.989)

        assert result == "Haifa, Haifa District, Israel"

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """HTTP 500 → None (graceful degradation)."""
        mock_resp = _make_mock_response(500)
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            result = await reverse_geocode(32.794, 34.989)

        assert result is None

    @pytest.mark.asyncio
    async def test_http_404_returns_none(self):
        """HTTP 404 → None."""
        mock_resp = _make_mock_response(404)
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            result = await reverse_geocode(32.794, 34.989)

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """Timeout → None (don't block the user)."""
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        ctx.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.get = MagicMock(return_value=ctx)

        with patch("app.infra.geocoding.get_default_session", return_value=session):
            result = await reverse_geocode(32.794, 34.989)

        assert result is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        """aiohttp.ClientError → None."""
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        ctx.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.get = MagicMock(return_value=ctx)

        with patch("app.infra.geocoding.get_default_session", return_value=session):
            result = await reverse_geocode(32.794, 34.989)

        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        """Invalid JSON → None."""
        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(side_effect=ValueError("Invalid JSON"))

        mock_session = _make_mock_session(resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            result = await reverse_geocode(32.794, 34.989)

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_json_returns_none(self):
        """Empty JSON response → None."""
        mock_resp = _make_mock_response(200, {})
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            result = await reverse_geocode(32.794, 34.989)

        assert result is None

    @pytest.mark.asyncio
    async def test_passes_correct_params(self):
        """Verify Nominatim API params are correct."""
        json_data = {
            "address": {"road": "Test", "city": "City"},
            "display_name": "Test, City",
        }
        mock_resp = _make_mock_response(200, json_data)
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            await reverse_geocode(32.794, 34.989)

        # Check the call was made with correct params
        call_args = mock_session.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["lat"] == "32.794"
        assert params["lon"] == "34.989"
        assert params["format"] == "json"
        assert params["addressdetails"] == "1"
        assert params["zoom"] == "18"

        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert "Stage0Bot" in headers["User-Agent"]

    @pytest.mark.asyncio
    async def test_custom_accept_language(self):
        """Custom accept_language is passed to Nominatim."""
        json_data = {"address": {"city": "Haifa"}}
        mock_resp = _make_mock_response(200, json_data)
        mock_session = _make_mock_session(mock_resp)

        with patch("app.infra.geocoding.get_default_session", return_value=mock_session):
            await reverse_geocode(32.794, 34.989, accept_language="en")

        call_args = mock_session.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params")
        assert params["accept-language"] == "en"
