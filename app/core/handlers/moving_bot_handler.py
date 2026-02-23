# app/core/handlers/moving_bot_handler.py
"""
Moving Bot Handler - implements the moving/delivery bot conversation flow.
This is a refactored version of the original engine.py logic, now as a pluggable handler.

Phase 1 refactor: reads all texts, choices, and validators from bot-local
modules instead of the global app_constants_v2 shim.

Phase 2: structured scheduling — DATE → (SPECIFIC_DATE) → TIME_SLOT → (EXACT_TIME)
replaces the old permissive TIME step.

Phase 3: pricing estimate shown before confirmation (EXTRAS → ESTIMATE → DONE).

Phase 4: multi-pickup (1–3 locations) — CARGO → PICKUP_COUNT → addr/floor loop.

Phase 5: optional geo point support — address steps accept GPS location as
alternative to text input.
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import asdict
from datetime import date, timedelta, datetime as _dt
from typing import Tuple, Optional

logger = logging.getLogger(__name__)
from zoneinfo import ZoneInfo

from app.core.domain import SessionState
from app.core.bot_handler import BotHandler
from app.core.bots.moving_bot_config import MOVING_BOT_CONFIG
from app.core.bots.moving_bot_texts import get_text
from app.core.bots.moving_bot_choices import (
    TIME_CHOICES_DICT, EXTRA_OPTIONS, VALUE_NONE,
    DATE_CHOICES_DICT, TIME_SLOT_CHOICES_DICT,
    VOLUME_CHOICES_DICT,
)
from app.core.bots.moving_bot_validators import (
    norm, lower, looks_too_short, parse_extras_input, detect_intent,
    parse_date, parse_exact_time, parse_floor_info, extract_items,
    detect_volume_from_rooms, detect_volume_from_items,
    sanitize_text, parse_landing_prefill, LandingPrefill,
    detect_language,
)
from app.core.bots.moving_bot_pricing import estimate_price, PricingConfig
from app.core.bots.moving_bot_geo import classify_geo_points, classify_route
from app.infra.tenant_registry import get_operator_config
from app.config import settings as _app_settings


_TZ = ZoneInfo("Asia/Jerusalem")

# Minimum confidence to switch session language on subsequent inputs
_LANG_CONFIDENCE_THRESHOLD = 0.5

# Steps where user provides free-text → eligible for language detection.
# Button-only steps (pickup_count, volume, date, time_slot, photo_menu,
# estimate, confirm_addresses) are excluded — numeric input is ambiguous.
_FREE_TEXT_STEPS = frozenset({
    "welcome", "cargo", "addr_from", "floor_from",
    "addr_from_2", "floor_from_2", "addr_from_3", "floor_from_3",
    "addr_to", "floor_to", "extras", "specific_date",
})

_VALID_PICKUP_COUNTS = {"1", "2", "3"}

# Steps that accept a GPS location as an alternative to text address
_ADDRESS_STEPS = {"addr_from", "addr_from_2", "addr_from_3", "addr_to"}


def _format_geo_addr(latitude: float, longitude: float, name: str | None = None) -> str:
    """Build a short text representation of a geo point for address fields.

    When a reverse-geocoded address (or adapter-provided name) is available,
    show it as the primary text.  Raw coordinates are always preserved in
    ``custom["geo_points"]`` and the notification's Google Maps links.
    """
    if name:
        return f"📍 {name}"
    return f"📍 {latitude:.5f}, {longitude:.5f}"


def _resolve_date_choice(choice: str) -> str:
    """Convert a date-choice enum value to an ISO ``YYYY-MM-DD`` string."""
    today = _dt.now(_TZ).date()
    if choice == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if choice == "2_3_days":
        return (today + timedelta(days=2)).isoformat()
    if choice == "this_week":
        return (today + timedelta(days=3)).isoformat()
    return ""  # "specific" — filled in the specific_date step


def _get_pickup_count(state) -> int:
    """Return the pickup count from custom dict, defaulting to 1."""
    return state.data.custom.get("pickup_count", 1)


def _compute_estimate(state) -> dict:
    """Build a price estimate from the collected session data."""
    pickups = state.data.custom.get("pickups", [])
    pickup_count = _get_pickup_count(state)

    # Build pickup floors list from all pickups
    pickup_floors = []
    if pickups:
        for p in pickups:
            floor_num, has_elev = parse_floor_info(p.get("floor", ""))
            pickup_floors.append((floor_num, has_elev))
    else:
        # Fallback: single pickup from legacy fields
        floor_num, has_elev = parse_floor_info(state.data.floor_from or "")
        pickup_floors.append((floor_num, has_elev))

    floor_to_num, has_elev_to = parse_floor_info(state.data.floor_to or "")

    # Map extras service names to pricing adjustment keys
    extras_for_pricing = list(state.data.extras) if state.data.extras else []

    # Phase 8: Regional classification — determine distance_factor from geo
    geo_points = state.data.custom.get("geo_points")
    distance_factor, region_info = classify_geo_points(geo_points)

    if region_info:
        state.data.custom["region_classifications"] = {
            k: {
                "inside_metro": v.inside_metro,
                "distance_km": v.distance_km,
                "distance_factor": v.distance_factor,
            }
            for k, v in region_info.items()
        }

    pricing_cfg = PricingConfig(distance_factor=distance_factor) if distance_factor != 1.0 else None

    # Phase 9: volume category
    volume_category = state.data.custom.get("volume_category")

    # Phase 10: extracted cargo items
    cargo_items = state.data.custom.get("cargo_items") or None

    # Phase 14: text-based route band classification
    route_band = None
    addr_from_text = state.data.addr_from or ""
    addr_to_text = state.data.addr_to or ""
    if addr_from_text and addr_to_text:
        route_cls = classify_route(addr_from_text, addr_to_text)
        route_band = route_cls.band.value
        state.data.custom["route_classification"] = {
            "band": route_band,
            "from_locality": route_cls.from_locality,
            "to_locality": route_cls.to_locality,
            "from_region": route_cls.from_region,
            "to_region": route_cls.to_region,
            "from_names": route_cls.from_names,
            "to_names": route_cls.to_names,
        }

    return estimate_price(
        pickup_floors=pickup_floors,
        floor_to=floor_to_num,
        has_elevator_to=has_elev_to,
        extra_pickups=max(0, pickup_count - 1),
        extras=extras_for_pricing,
        volume_category=volume_category,
        items=cargo_items,
        pricing=pricing_cfg,
        route_band=route_band,
    )


def _pickup_question(key: str, n: int, lang: str) -> str:
    """Format a numbered pickup question (replaces {n} placeholder)."""
    return get_text(key, lang).replace("{n}", str(n))


def _build_welcome_block(lang: str, tenant_id: str) -> str:
    """Build the full welcome message: welcome + optional contact + hint + cargo question.

    Resolves operator phone per-tenant via ``get_operator_config()``.
    If no phone is configured, the contact line is omitted.
    """
    parts = [get_text("welcome", lang)]

    op_cfg = get_operator_config(tenant_id)
    phone = op_cfg.get("operator_whatsapp")
    if phone:
        parts.append(get_text("welcome_contact", lang).format(phone=phone))

    parts.append(get_text("hint_can_reset", lang))
    parts.append("")  # blank line before cargo question
    parts.append(get_text("q_cargo", lang))

    return "\n".join(parts)


def _photo_menu_text(state: SessionState, lang: str) -> str:
    """Return photo menu question — stronger wording for room-based moves."""
    if state.data.custom.get("volume_from_rooms"):
        return get_text("q_photo_menu_rooms", lang)
    return get_text("q_photo_menu", lang)


class MovingBotHandler:
    """Handler for moving/delivery bot conversations"""

    def __init__(self):
        self._config = MOVING_BOT_CONFIG

    @property
    def config(self):
        return self._config

    def new_session(self, tenant_id: str, chat_id: str, language: str = "ru") -> SessionState:
        """Create a new moving bot session"""
        lead_id = uuid.uuid4().hex[:12]
        return SessionState(
            tenant_id=tenant_id,
            chat_id=chat_id,
            lead_id=lead_id,
            bot_type="moving_bot_v1",
            step="welcome",
            language=language
        )

    def handle_text(
        self,
        state: SessionState,
        text: str
    ) -> Tuple[SessionState, str, bool]:
        """
        Process text input for moving bot.
        This is the core logic from the original engine.py
        """
        lang = state.language
        try:
            msg = sanitize_text(text, max_length=2000)
        except ValueError:
            return state, get_text("err_rejected_input", lang), False
        intent = detect_intent(msg)

        # --- Language detection (auto-switch from free-text inputs) ---
        if state.step in _FREE_TEXT_STEPS:
            detected_lang, confidence = detect_language(msg)
            if detected_lang and confidence >= _LANG_CONFIDENCE_THRESHOLD:
                state.language = detected_lang
                lang = detected_lang

        # Handle reset intent
        if intent == "reset":
            st = self.new_session(state.tenant_id, state.chat_id, state.language)
            st.step = "cargo"
            return st, _build_welcome_block(lang, st.tenant_id), False

        # Step: WELCOME
        if state.step == "welcome":
            prefill = parse_landing_prefill(msg)
            if prefill is not None:
                return self._apply_prefill(state, prefill, lang)
            state.step = "cargo"
            return state, _build_welcome_block(lang, state.tenant_id), False

        # Step: CARGO
        if state.step == "cargo":
            if looks_too_short(msg, 5):
                return state, get_text("err_cargo_too_short", lang), False
            state.data.cargo_description = msg
            # Phase 10: extract structured items for pricing
            state.data.custom["cargo_raw"] = msg
            cargo_items = extract_items(msg)
            state.data.custom["cargo_items"] = cargo_items
            # Phase 12: auto-detect volume from room descriptions
            room_volume = detect_volume_from_rooms(msg)
            if room_volume:
                state.data.custom["volume_category"] = room_volume
                state.data.custom["volume_from_rooms"] = True
                state.step = "pickup_count"
                return state, get_text("q_pickup_count", lang), False
            # Infer volume from recognised items so G6 complexity guard
            # can fire even when volume wasn't asked explicitly.
            if cargo_items:
                inferred_vol = detect_volume_from_items(cargo_items)
                if inferred_vol:
                    state.data.custom["volume_category"] = inferred_vol
                    state.data.custom["volume_from_items"] = True
                state.step = "pickup_count"
                return state, get_text("q_pickup_count", lang), False
            # No rooms, no items → ask volume explicitly
            state.step = "volume"
            return state, get_text("q_volume", lang), False

        # Step: VOLUME (Phase 9 — move size category)
        if state.step == "volume":
            t = lower(msg)
            if t not in VOLUME_CHOICES_DICT:
                return state, get_text("err_volume_choice", lang), False
            state.data.custom["volume_category"] = VOLUME_CHOICES_DICT[t]
            state.step = "pickup_count"
            return state, get_text("q_pickup_count", lang), False

        # Step: CONFIRM_ADDRESSES (landing prefill — ask to extend city-only addresses)
        if state.step == "confirm_addresses":
            t = lower(msg)
            if t == "1":
                # User wants to provide full addresses → normal address flow
                state.data.custom["pickup_count"] = 1
                state.data.custom["pickups"] = []
                state.step = "pickup_count"
                return state, get_text("q_pickup_count", lang), False
            if t == "2":
                # User skips address details → keep landing addresses, skip to scheduling
                state.data.custom["pickup_count"] = 1
                state.data.custom["pickups"] = [
                    {"addr": state.data.addr_from, "floor": "—"}
                ]
                state.data.custom["landing_addresses_kept"] = True
                # If date was already parsed from landing → skip date, ask time only
                if state.data.custom.get("landing_date_parsed"):
                    state.step = "time_slot"
                    return state, get_text("q_time_slot", lang), False
                state.step = "date"
                return state, get_text("q_date", lang), False
            return state, get_text("err_confirm_addresses", lang), False

        # ===================================================================
        # Phase 4: multi-pickup (1–3 locations)
        # ===================================================================

        # Step: PICKUP_COUNT
        if state.step == "pickup_count":
            t = lower(msg)
            if t not in _VALID_PICKUP_COUNTS:
                return state, get_text("err_pickup_count", lang), False
            count = int(t)
            state.data.custom["pickup_count"] = count
            state.data.custom["pickups"] = []
            state.step = "addr_from"
            return state, get_text("q_addr_from", lang), False

        # Step: ADDR_FROM (first pickup address)
        if state.step == "addr_from":
            if looks_too_short(msg, 5):
                return state, get_text("err_addr_too_short", lang), False
            state.data.addr_from = msg
            state.step = "floor_from"
            return state, get_text("q_floor_from", lang), False

        # Step: FLOOR_FROM (first pickup floor & elevator)
        if state.step == "floor_from":
            if looks_too_short(msg, 2):
                return state, get_text("err_floor_too_short", lang), False
            state.data.floor_from = msg
            # Store first pickup in pickups list
            pickups = state.data.custom.get("pickups", [])
            if len(pickups) == 0:
                pickups.append({"addr": state.data.addr_from, "floor": msg})
                state.data.custom["pickups"] = pickups
            count = _get_pickup_count(state)
            if count >= 2:
                state.step = "addr_from_2"
                return state, _pickup_question("q_addr_from_n", 2, lang), False
            state.step = "addr_to"
            return state, get_text("q_addr_to", lang), False

        # Step: ADDR_FROM_2 (second pickup address)
        if state.step == "addr_from_2":
            if looks_too_short(msg, 5):
                return state, get_text("err_addr_too_short", lang), False
            state.data.custom.setdefault("pickups", [])
            # Store addr temporarily; will be committed with floor
            state.data.custom["_pending_addr_2"] = msg
            state.step = "floor_from_2"
            return state, _pickup_question("q_floor_from_n", 2, lang), False

        # Step: FLOOR_FROM_2 (second pickup floor & elevator)
        if state.step == "floor_from_2":
            if looks_too_short(msg, 2):
                return state, get_text("err_floor_too_short", lang), False
            addr = state.data.custom.pop("_pending_addr_2", "")
            state.data.custom["pickups"].append({"addr": addr, "floor": msg})
            count = _get_pickup_count(state)
            if count >= 3:
                state.step = "addr_from_3"
                return state, _pickup_question("q_addr_from_n", 3, lang), False
            state.step = "addr_to"
            return state, get_text("q_addr_to", lang), False

        # Step: ADDR_FROM_3 (third pickup address)
        if state.step == "addr_from_3":
            if looks_too_short(msg, 5):
                return state, get_text("err_addr_too_short", lang), False
            state.data.custom["_pending_addr_3"] = msg
            state.step = "floor_from_3"
            return state, _pickup_question("q_floor_from_n", 3, lang), False

        # Step: FLOOR_FROM_3 (third pickup floor & elevator)
        if state.step == "floor_from_3":
            if looks_too_short(msg, 2):
                return state, get_text("err_floor_too_short", lang), False
            addr = state.data.custom.pop("_pending_addr_3", "")
            state.data.custom["pickups"].append({"addr": addr, "floor": msg})
            state.step = "addr_to"
            return state, get_text("q_addr_to", lang), False

        # Step: ADDR_TO (delivery address)
        if state.step == "addr_to":
            if looks_too_short(msg, 5):
                return state, get_text("err_addr_too_short", lang), False
            state.data.addr_to = msg
            state.step = "floor_to"
            return state, get_text("q_floor_to", lang), False

        # Step: FLOOR_TO (delivery floor & elevator)
        if state.step == "floor_to":
            if looks_too_short(msg, 2):
                return state, get_text("err_floor_too_short", lang), False
            state.data.floor_to = msg
            # Landing prefill: date already parsed → skip date, ask time only
            if state.data.custom.get("landing_date_parsed"):
                state.step = "time_slot"
                return state, get_text("q_time_slot", lang), False
            state.step = "date"
            return state, get_text("q_date", lang), False

        # ===================================================================
        # Phase 2: structured scheduling steps
        # ===================================================================

        # Step: DATE (date selection — no same-day)
        if state.step == "date":
            t = lower(msg)
            if t in DATE_CHOICES_DICT:
                choice = DATE_CHOICES_DICT[t]
                state.data.custom["move_date_label"] = choice
                state.data.custom["timezone"] = "Asia/Jerusalem"

                if choice == "specific":
                    state.step = "specific_date"
                    return state, get_text("q_specific_date", lang), False

                # Resolve to ISO date
                state.data.custom["move_date"] = _resolve_date_choice(choice)
                state.step = "time_slot"
                return state, get_text("q_time_slot", lang), False

            # Phase 15: try natural date parsing as fallback
            try:
                parsed = parse_date(msg)
                state.data.custom["move_date"] = parsed.isoformat()
                state.data.custom["move_date_label"] = "natural"
                state.data.custom["timezone"] = "Asia/Jerusalem"
                state.step = "time_slot"
                return state, get_text("q_time_slot", lang), False
            except ValueError:
                return state, get_text("err_date_choice", lang), False

        # Step: SPECIFIC_DATE (user enters DD.MM or DD.MM.YYYY)
        if state.step == "specific_date":
            try:
                parsed = parse_date(msg)
                state.data.custom["move_date"] = parsed.isoformat()
                state.step = "time_slot"
                return state, get_text("q_time_slot", lang), False
            except ValueError as e:
                err_code = str(e)
                error_map = {
                    "format": "err_date_format",
                    "invalid_date": "err_date_invalid",
                    "too_soon": "err_date_too_soon",
                    "too_far": "err_date_too_far",
                }
                key = error_map.get(err_code, "err_date_format")
                return state, get_text(key, lang), False

        # Step: TIME_SLOT (time-of-day window)
        if state.step == "time_slot":
            t = lower(msg)

            if t == "4":
                # User wants to enter exact time
                state.step = "exact_time"
                return state, get_text("q_exact_time", lang), False

            if t not in TIME_SLOT_CHOICES_DICT:
                return state, get_text("err_time_slot_choice", lang), False

            slot = TIME_SLOT_CHOICES_DICT[t]
            state.data.custom["time_slot"] = slot
            state.data.custom["exact_time"] = None
            state.data.time_window = slot  # backward compat
            state.step = "photo_menu"
            return state, _photo_menu_text(state, lang), False

        # Step: EXACT_TIME (user enters HH:MM)
        if state.step == "exact_time":
            try:
                time_str = parse_exact_time(msg)
                state.data.custom["time_slot"] = "exact"
                state.data.custom["exact_time"] = time_str
                state.data.time_window = f"exact:{time_str}"  # backward compat
                state.step = "photo_menu"
                return state, _photo_menu_text(state, lang), False
            except ValueError:
                return state, get_text("err_exact_time_format", lang), False

        # ===================================================================
        # Legacy TIME step (kept for sessions mid-flow at deploy time)
        # ===================================================================
        if state.step == "time":
            t = lower(msg)
            if t in TIME_CHOICES_DICT:
                state.data.time_window = TIME_CHOICES_DICT[t]
            else:
                if looks_too_short(msg, 3):
                    return state, get_text("err_time_format", lang), False
                state.data.time_window = msg
            state.step = "photo_menu"
            return state, _photo_menu_text(state, lang), False

        # Step: PHOTO_MENU
        if state.step == "photo_menu":
            t = lower(msg)
            if t == "1":
                state.data.has_photos = True
                state.step = "photo_wait"
                return state, get_text("q_photo_wait", lang), False
            if t == "2" or intent == "no":
                state.data.has_photos = False
                state.step = "extras"
                return state, get_text("q_extras", lang), False
            return state, get_text("err_photo_menu", lang), False

        # Step: PHOTO_WAIT
        if state.step == "photo_wait":
            if intent == "done_photos":
                if state.data.photo_count == 0:
                    state.data.has_photos = True
                state.step = "extras"
                return state, get_text("q_extras", lang), False
            return state, get_text("info_photo_wait", lang), False

        # Step: EXTRAS
        # Supports multiple input formats:
        # 1. Numbers only: "1 3" -> services: loaders, packing
        # 2. Text only: "5 этаж без лифта" -> details_free
        # 3. Numbers + text: "1 3 + 5 этаж" -> services AND details
        #    Separators: "+", ",", "и", "and", "также"
        if state.step == "extras":
            choices, details = parse_extras_input(msg)

            if choices:
                if "4" in choices:
                    # "4" means "none of these"
                    state.data.extras = []
                    if not details:
                        state.data.details_free = VALUE_NONE
                else:
                    for c in sorted(choices):
                        if c in EXTRA_OPTIONS and EXTRA_OPTIONS[c] not in state.data.extras:
                            state.data.extras.append(EXTRA_OPTIONS[c])

                # Save details if provided along with choices
                if details:
                    state.data.details_free = details

                return self._transition_to_estimate(state, lang)

            # No numeric choices found - treat entire input as free text
            if looks_too_short(msg, 2):
                if intent == "no":
                    state.data.details_free = VALUE_NONE
                    return self._transition_to_estimate(state, lang)
                return state, get_text("err_extras_empty", lang), False

            state.data.details_free = msg
            return self._transition_to_estimate(state, lang)

        # ===================================================================
        # Phase 3: pricing estimate confirmation step
        # ===================================================================

        # Step: ESTIMATE (show price range, user confirms or restarts)
        if state.step == "estimate":
            t = lower(msg)
            if t == "1" or intent == "done_photos":
                # Confirm — finalize the lead
                state.data.custom["session_language"] = lang
                state.step = "done"
                return state, get_text("done", lang), True
            if t == "2" or intent == "reset":
                # Start over
                st = self.new_session(state.tenant_id, state.chat_id, state.language)
                st.step = "cargo"
                return st, _build_welcome_block(lang, st.tenant_id), False
            return state, get_text("err_estimate_choice", lang), False

        # Step: DONE (already completed)
        return state, get_text("info_already_done", lang), False

    def _transition_to_estimate(
        self,
        state: SessionState,
        lang: str,
    ) -> Tuple[SessionState, str, bool]:
        """Compute the price estimate, store it, and show the summary."""
        est = _compute_estimate(state)

        # Parsing quality check: if user wrote a lot but we extracted
        # nothing/very little, the estimate is unreliable — suppress it.
        cargo_raw = state.data.custom.get("cargo_raw", "")
        cargo_items = state.data.custom.get("cargo_items") or []
        estimate_suppressed = (
            len(cargo_raw) > 30
            and len(cargo_items) == 0
            and not state.data.custom.get("volume_category")
        )

        if estimate_suppressed:
            state.data.custom["estimate_suppressed"] = True
            # Still store breakdown for operator debugging, but no price for user
            state.data.custom["estimate_breakdown"] = est["breakdown"]

            # Phase 15: structured observability log
            breakdown = est["breakdown"]
            log_data = {
                "event": "estimate_suppressed",
                "lead_id": state.lead_id,
                "tenant_id": state.tenant_id,
                "cargo_raw_len": len(cargo_raw),
                "items_count": 0,
                "volume_category": None,
                "source": state.data.custom.get("source", "chat"),
            }
            logger.info("estimate_suppressed", extra=log_data)

            state.step = "estimate"
            return state, get_text("estimate_no_price", lang), False

        # Normal path — store estimate and show to user
        state.data.custom["estimate_min"] = est["estimate_min"]
        state.data.custom["estimate_max"] = est["estimate_max"]
        state.data.custom["estimate_currency"] = est["currency"]
        state.data.custom["estimate_breakdown"] = est["breakdown"]

        # Phase 15: structured observability log
        breakdown = est["breakdown"]
        log_data = {
            "event": "estimate_computed",
            "lead_id": state.lead_id,
            "tenant_id": state.tenant_id,
            "estimate_min": est["estimate_min"],
            "estimate_max": est["estimate_max"],
            "volume_category": state.data.custom.get("volume_category"),
            "route_band": breakdown.get("route_band"),
            "route_fee": breakdown.get("route_fee", 0),
            "route_minimum": breakdown.get("route_minimum", 0),
            "minimum_applied": breakdown.get("minimum_applied", False),
            "guards_applied": breakdown.get("guards_applied", []),
            "floor_surcharge": breakdown.get("floor_surcharge", 0),
            "volume_surcharge": breakdown.get("volume_surcharge", 0),
            "extras_adjustment": breakdown.get("extras_adjustment", 0),
            "items_count": len(cargo_items),
            "pickup_count": state.data.custom.get("pickup_count", 1),
            "source": state.data.custom.get("source", "chat"),
            "complexity_score": breakdown.get("complexity_score", 0),
            "complexity_triggers": breakdown.get("complexity_triggers", []),
            "complexity_applied": breakdown.get("complexity_applied", False),
        }
        logger.info("estimate_computed", extra=log_data)

        # Global display toggle: operator still sees estimate_min/max,
        # but user and crew get the no-price message.
        if not _app_settings.estimate_display_enabled:
            state.data.custom["estimate_display_disabled"] = True
            state.step = "estimate"
            return state, get_text("estimate_no_price", lang), False

        summary = get_text("estimate_summary", lang).format(
            min_price=est["estimate_min"],
            max_price=est["estimate_max"],
        )
        state.step = "estimate"
        return state, summary, False

    def _apply_prefill(
        self,
        state: SessionState,
        prefill: LandingPrefill,
        lang: str,
    ) -> Tuple[SessionState, str, bool]:
        """Apply landing page pre-fill data and skip to first unanswered step.

        Fills ``cargo_description`` from the *details* field (or
        *move_type* as fallback).  Addresses and date are stored as
        operator-visible hints but the structured steps still run
        (landing data is approximate — city names, not full addresses).
        """
        state.data.custom["source"] = "landing_prefill"

        # 1. Fill cargo from details or move_type
        if prefill.details:
            state.data.cargo_description = prefill.details
            state.data.custom["cargo_raw"] = prefill.details
            state.data.custom["cargo_items"] = extract_items(prefill.details)
            room_vol = detect_volume_from_rooms(prefill.details)
            if room_vol:
                state.data.custom["volume_category"] = room_vol
                state.data.custom["volume_from_rooms"] = True
            else:
                inferred_vol = detect_volume_from_items(
                    state.data.custom.get("cargo_items") or []
                )
                if inferred_vol:
                    state.data.custom["volume_category"] = inferred_vol
                    state.data.custom["volume_from_items"] = True
        elif prefill.move_type:
            state.data.cargo_description = prefill.move_type
            state.data.custom["cargo_raw"] = prefill.move_type

        # 2. Store addresses and date as operator context
        if prefill.addr_from:
            state.data.addr_from = prefill.addr_from
        if prefill.addr_to:
            state.data.addr_to = prefill.addr_to
        if prefill.date_text:
            state.data.custom["landing_date_hint"] = prefill.date_text
            # Phase 15: attempt structured date parsing
            try:
                parsed_date = parse_date(prefill.date_text)
                state.data.custom["move_date"] = parsed_date.isoformat()
                state.data.custom["landing_date_parsed"] = True
            except ValueError:
                state.data.custom["landing_date_parsed"] = False
        if prefill.move_type:
            state.data.custom["landing_move_type"] = prefill.move_type

        # Phase 15: attempt route classification from addresses
        if prefill.addr_from and prefill.addr_to:
            route_cls = classify_route(prefill.addr_from, prefill.addr_to)
            state.data.custom["route_classification"] = {
                "band": route_cls.band.value,
                "from_locality": route_cls.from_locality,
                "to_locality": route_cls.to_locality,
                "from_region": route_cls.from_region,
                "to_region": route_cls.to_region,
                "from_names": route_cls.from_names,
                "to_names": route_cls.to_names,
            }

        ack = get_text("ack_landing_prefill", lang)

        # 3. Decide first unanswered step
        if not state.data.cargo_description:
            state.step = "cargo"
            return state, f"{ack}\n\n{get_text('q_cargo', lang)}", False

        # Cargo filled — skip volume when we have enough info
        has_volume = bool(state.data.custom.get("volume_category"))
        has_items = bool(state.data.custom.get("cargo_items"))
        if not has_volume and not has_items:
            # No rooms, no items → ask volume explicitly
            state.step = "volume"
            return state, f"{ack}\n\n{get_text('q_volume', lang)}", False

        # Volume known or items listed — check if we have landing addresses
        has_addrs = bool(prefill.addr_from and prefill.addr_to)
        if has_addrs:
            # City-level addresses from landing — ask user to confirm/extend
            state.step = "confirm_addresses"
            q = get_text("q_confirm_addresses", lang).format(
                addr_from=state.data.addr_from,
                addr_to=state.data.addr_to,
            )
            return state, f"{ack}\n\n{q}", False

        # No landing addresses → normal flow: pickup count
        state.data.custom["pickup_count"] = 1
        state.data.custom["pickups"] = []
        state.step = "pickup_count"
        return state, f"{ack}\n\n{get_text('q_pickup_count', lang)}", False

    def handle_media(self, state: SessionState) -> Tuple[SessionState, Optional[str]]:
        """Process media input for moving bot"""
        lang = state.language
        if state.step == "photo_wait":
            state.data.has_photos = True
            state.data.photo_count += 1
            if state.data.photo_count == 1:
                return state, get_text("info_photo_received_first", lang)
            return state, None

        state.data.has_photos = True
        state.data.photo_count += 1
        return state, get_text("info_photo_received_late", lang)

    def handle_location(
        self,
        state: SessionState,
        latitude: float,
        longitude: float,
        name: str | None = None,
        address: str | None = None,
    ) -> Tuple[SessionState, str, bool]:
        """
        Accept GPS location during address steps (Phase 5).

        When the user shares a geo pin instead of typing an address, we:
        1. Store coordinates in ``custom`` (for operator / future geo pricing)
        2. Generate a text representation for the address field
        3. Advance to the next step (floor question)

        Non-address steps return a polite "not supported here" message.
        """
        lang = state.language

        if state.step not in _ADDRESS_STEPS:
            return state, get_text("info_location_ignored", lang), False

        geo_addr = _format_geo_addr(latitude, longitude, name or address)
        geo_data = {"lat": latitude, "lon": longitude}
        if name:
            geo_data["name"] = name
        if address:
            geo_data["address"] = address

        # --- ADDR_FROM (first pickup) ---
        if state.step == "addr_from":
            state.data.addr_from = geo_addr
            state.data.custom.setdefault("geo_points", {})
            state.data.custom["geo_points"]["pickup_1"] = geo_data
            state.step = "floor_from"
            reply = f"{get_text('info_location_saved', lang)}\n\n{get_text('q_floor_from', lang)}"
            return state, reply, False

        # --- ADDR_FROM_2 (second pickup) ---
        if state.step == "addr_from_2":
            state.data.custom.setdefault("pickups", [])
            state.data.custom["_pending_addr_2"] = geo_addr
            state.data.custom.setdefault("geo_points", {})
            state.data.custom["geo_points"]["pickup_2"] = geo_data
            state.step = "floor_from_2"
            reply = f"{get_text('info_location_saved', lang)}\n\n{_pickup_question('q_floor_from_n', 2, lang)}"
            return state, reply, False

        # --- ADDR_FROM_3 (third pickup) ---
        if state.step == "addr_from_3":
            state.data.custom["_pending_addr_3"] = geo_addr
            state.data.custom.setdefault("geo_points", {})
            state.data.custom["geo_points"]["pickup_3"] = geo_data
            state.step = "floor_from_3"
            reply = f"{get_text('info_location_saved', lang)}\n\n{_pickup_question('q_floor_from_n', 3, lang)}"
            return state, reply, False

        # --- ADDR_TO (delivery) ---
        if state.step == "addr_to":
            state.data.addr_to = geo_addr
            state.data.custom.setdefault("geo_points", {})
            state.data.custom["geo_points"]["delivery"] = geo_data
            state.step = "floor_to"
            reply = f"{get_text('info_location_saved', lang)}\n\n{get_text('q_floor_to', lang)}"
            return state, reply, False

        # Fallback (should not reach here given the _ADDRESS_STEPS guard)
        return state, get_text("info_location_ignored", lang), False

    def get_payload(self, state: SessionState) -> dict:
        """Generate payload for moving bot lead"""
        return {
            "tenant_id": state.tenant_id,
            "lead_id": state.lead_id,
            "chat_id": state.chat_id,
            "bot_type": state.bot_type,
            "step": state.step,
            "data": asdict(state.data),
        }
