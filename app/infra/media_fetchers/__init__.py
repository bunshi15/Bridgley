# app/infra/media_fetchers/__init__.py
"""
Provider-specific media fetchers.

Strategy pattern: each provider can have a dedicated fetcher that uses
the provider's official API, eliminating CDN redirect and auth issues.
A generic HTTP fetcher serves as a universal fallback.
"""
from app.infra.media_fetchers.base import (
    FetchResult,
    MediaFetchError,
    MediaFetcher,
)
from app.infra.media_fetchers.http_fetcher import HttpMediaFetcher
from app.infra.media_fetchers.twilio_fetcher import TwilioMediaFetcher
from app.infra.media_fetchers.meta_fetcher import MetaMediaFetcher

__all__ = [
    "FetchResult",
    "MediaFetchError",
    "MediaFetcher",
    "HttpMediaFetcher",
    "TwilioMediaFetcher",
    "MetaMediaFetcher",
]
