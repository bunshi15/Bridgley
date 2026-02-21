# app/core/engine/domain.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any, Dict


# ============================================================================
# UNIVERSAL STEP ENUM (base class for bot-specific steps)
# ============================================================================

class Step(str, Enum):
    """
    Universal base step enum. Bot-specific steps should inherit from this.
    This provides backward compatibility while allowing each bot to define its own steps.
    """
    WELCOME = "welcome"
    DONE = "done"


# ============================================================================
# UNIVERSAL LEAD DATA (flexible storage for any bot type)
# ============================================================================

@dataclass
class LeadData:
    """
    Universal lead data container that works for any bot type.
    Uses flexible key-value storage instead of hardcoded fields.

    For backward compatibility, we keep moving bot specific fields as defaults.
    New bots can use the 'custom' dict for their specific data.
    """
    # Common fields (used by moving bot, can be reused by others)
    cargo_description: Optional[str] = None
    addr_from: Optional[str] = None
    floor_from: Optional[str] = None
    addr_to: Optional[str] = None
    floor_to: Optional[str] = None
    time_window: Optional[str] = None
    has_photos: Optional[bool] = None
    photo_count: int = 0
    extras: list[str] = field(default_factory=list)
    details_free: Optional[str] = None

    # Flexible storage for bot-specific data (new bots should use this)
    custom: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """Set a custom field value"""
        self.custom[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a custom field value"""
        return self.custom.get(key, default)


# ============================================================================
# UNIVERSAL SESSION STATE
# ============================================================================

@dataclass
class SessionState:
    """
    Universal session state that works for any bot type.
    The step field now accepts any string value, allowing bot-specific steps.
    """
    tenant_id: str
    chat_id: str
    lead_id: str
    bot_type: str = "moving_bot_v1"  # Bot type identifier
    step: str = Step.WELCOME.value  # Changed from Step enum to string for flexibility
    data: LeadData = field(default_factory=LeadData)

    # Optional metadata
    language: str = "ru"  # User's preferred language
    metadata: Dict[str, Any] = field(default_factory=dict)  # Extra bot-specific metadata

    # Populated from DB on load (not serialized to state_json)
    updated_at: Optional[datetime] = field(default=None, repr=False)


@dataclass
class MediaItem:
    """Media attachment in a message.

    For most providers ``url`` is a direct download link.  Meta Cloud API
    delivers a **media ID** instead -- store it in ``provider_media_id``
    and leave ``url`` empty until the ID has been resolved to a temporary
    download URL via the Graph API.
    """
    url: str = ""
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    provider_media_id: Optional[str] = None  # Meta Cloud API media ID


@dataclass
class LocationData:
    """GPS coordinates shared by the user (Phase 5).

    All providers can deliver location messages — this normalizes them
    into a single domain object.
    """
    latitude: float
    longitude: float
    name: Optional[str] = None       # Place name (Meta, Telegram venue)
    address: Optional[str] = None    # Street address (Meta)


@dataclass
class InboundMessage:
    """
    Normalized inbound message from any provider.
    This is the domain model that represents an incoming message.
    """
    tenant_id: str
    provider: str  # "twilio", "dev", "whatsapp", "telegram", etc.
    chat_id: str  # phone number or user ID
    message_id: str  # unique message identifier
    text: Optional[str] = None
    media: list[MediaItem] = field(default_factory=list)

    # Optional sender info (mainly for Telegram where chat_id is not a phone number)
    sender_name: Optional[str] = None  # Display name: "Ivan Petrov" or "@username"

    # Phase 5: optional GPS location
    location: Optional[LocationData] = None

    def has_text(self) -> bool:
        """Check if message contains text"""
        return bool(self.text and self.text.strip())

    def has_media(self) -> bool:
        """Check if message contains media attachments"""
        return bool(self.media)

    def has_location(self) -> bool:
        """Check if message contains a GPS location"""
        return self.location is not None

    def is_photo(self) -> bool:
        """Check if message contains image media"""
        if not self.media:
            return False
        return any(
            item.content_type and item.content_type.startswith("image/")
            for item in self.media
        )
