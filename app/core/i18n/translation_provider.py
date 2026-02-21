# app/core/i18n/translation_provider.py
"""
External translation providers for operator lead translation.

Only used for translating the **final operator lead payload** — not for
UX bot messages (those use static ``get_text()`` translations).

Supported providers:
- DeepL API (free/pro)
- Google Cloud Translation v2
- OpenAI ChatCompletion (gpt-4o-mini)

Architecture:
- All providers are async (httpx-based) — no heavy ML libs.
- Strict timeouts, retries with exponential backoff, rate limiting.
- API key loaded from env only (never logged).
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language code mapping (internal → provider-specific)
# ---------------------------------------------------------------------------

# _DEEPL_LANG_MAP = {"ru": "RU", "en": "EN", "he": "HE"}
_DEEPL_LANG_MAP = {"ru": "RU", "he": "HE"}  # DeepL Free
_GOOGLE_LANG_MAP = {"ru": "ru", "en": "en", "he": "iw"}  # Google uses "iw" for Hebrew
_OPENAI_LANG_NAMES = {"ru": "Russian", "en": "English", "he": "Hebrew"}


# ---------------------------------------------------------------------------
# Rate limiter (in-memory token bucket)
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Simple in-memory token bucket for rate limiting."""

    def __init__(self, rate_per_minute: int):
        self._rate = rate_per_minute
        self._tokens = float(rate_per_minute)
        self._max = float(rate_per_minute)
        self._last = time.monotonic()

    def acquire(self) -> bool:
        """Try to acquire one token.  Returns False if rate-limited."""
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self._max, self._tokens + elapsed * (self._rate / 60.0))
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class TranslationProvider(ABC):
    """Abstract base for external translation API providers."""

    def __init__(
        self,
        api_key: str,
        timeout: int = 10,
        retries: int = 2,
        rate_limit_per_minute: int = 60,
    ):
        self._api_key = api_key
        self._timeout = timeout
        self._retries = retries
        self._bucket = _TokenBucket(rate_limit_per_minute)

    @abstractmethod
    async def _call_api(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        """Provider-specific API call.  Must return translated texts
        in the same order as *texts*."""
        ...

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Translate a single text string."""
        results = await self.translate_batch(
            {"_single": text}, source_lang, target_lang,
        )
        return results.get("_single", text)

    async def translate_batch(
        self,
        fields: dict[str, str],
        source_lang: str,
        target_lang: str,
    ) -> dict[str, str]:
        """Translate multiple fields in one API call (or minimal calls).

        Returns a dict with the same keys and translated values.
        On failure, returns the original values for failed fields.
        """
        if not fields:
            return {}

        # Skip if source == target
        if source_lang == target_lang:
            return dict(fields)

        # Rate limit check
        if not self._bucket.acquire():
            logger.warning("Translation rate limit reached, returning originals")
            return dict(fields)

        keys = list(fields.keys())
        texts = [fields[k] for k in keys]

        # Retry with exponential backoff (only for transient errors)
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                translated = await self._call_api(texts, source_lang, target_lang)
                return dict(zip(keys, translated))
            except httpx.HTTPStatusError as exc:
                last_error = exc
                # 401/403 = auth error → no point retrying
                if exc.response.status_code in (401, 403):
                    logger.error(
                        "Translation API auth error (HTTP %d), not retrying",
                        exc.response.status_code,
                    )
                    break
                if attempt < self._retries:
                    wait = (attempt + 1) * 2
                    logger.warning(
                        "Translation API attempt %d/%d failed (HTTP %d), retrying in %ds",
                        attempt + 1, self._retries + 1,
                        exc.response.status_code, wait,
                    )
                    await asyncio.sleep(wait)
            except Exception as exc:
                last_error = exc
                if attempt < self._retries:
                    wait = (attempt + 1) * 2
                    logger.warning(
                        "Translation API attempt %d/%d failed (%s), retrying in %ds",
                        attempt + 1, self._retries + 1,
                        type(exc).__name__, wait,
                    )
                    await asyncio.sleep(wait)

        logger.error(
            "Translation API failed after %d attempts: %s",
            self._retries + 1, type(last_error).__name__,
        )
        return dict(fields)  # Return originals on failure


# ---------------------------------------------------------------------------
# DeepL provider
# ---------------------------------------------------------------------------

class DeepLProvider(TranslationProvider):
    """DeepL API translation provider (free + pro)."""

    # DeepL free uses api-free.deepl.com; pro uses api.deepl.com.
    # We auto-detect from the key suffix (:fx = free).
    def _base_url(self) -> str:
        if self._api_key.endswith(":fx"):
            return "https://api-free.deepl.com/v2/translate"
        return "https://api.deepl.com/v2/translate"

    async def _call_api(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        src = _DEEPL_LANG_MAP.get(source_lang, source_lang.upper())
        tgt = _DEEPL_LANG_MAP.get(target_lang, target_lang.upper())

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._base_url(),
                headers={
                    "Authorization": f"DeepL-Auth-Key {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "text": texts,
                    "source_lang": src,
                    "target_lang": tgt,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            translations = data.get("translations", [])
            return [t["text"] for t in translations]


# ---------------------------------------------------------------------------
# Google Cloud Translation v2 provider
# ---------------------------------------------------------------------------

class GoogleTranslateProvider(TranslationProvider):
    """Google Cloud Translation API v2 provider."""

    _URL = "https://translation.googleapis.com/language/translate/v2"

    async def _call_api(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        src = _GOOGLE_LANG_MAP.get(source_lang, source_lang)
        tgt = _GOOGLE_LANG_MAP.get(target_lang, target_lang)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._URL,
                params={"key": self._api_key},
                json={
                    "q": texts,
                    "source": src,
                    "target": tgt,
                    "format": "text",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            translations = data["data"]["translations"]
            return [t["translatedText"] for t in translations]


# ---------------------------------------------------------------------------
# OpenAI provider (gpt-4o-mini — cheap, fast)
# ---------------------------------------------------------------------------

class OpenAITranslateProvider(TranslationProvider):
    """OpenAI ChatCompletion translation provider (gpt-4o-mini)."""

    _URL = "https://api.openai.com/v1/chat/completions"
    _MODEL = "gpt-4o-mini"

    async def _call_api(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        src_name = _OPENAI_LANG_NAMES.get(source_lang, source_lang)
        tgt_name = _OPENAI_LANG_NAMES.get(target_lang, target_lang)

        # Build a numbered list so we can parse results reliably
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
        system_prompt = (
            f"You are a professional translator. Translate the following "
            f"numbered texts from {src_name} to {tgt_name}. "
            f"Return ONLY the translations as a numbered list (same format). "
            f"Preserve addresses, proper nouns, and numbers as-is. "
            f"Do not add explanations."
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._MODEL,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": numbered},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse_numbered(content, len(texts))

    @staticmethod
    def _parse_numbered(content: str, expected: int) -> list[str]:
        """Parse a numbered list response from OpenAI."""
        import re
        lines = content.strip().split("\n")
        results: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Strip "N. " or "N) " prefix
            m = re.match(r"^\d+[.)]\s*(.+)$", line)
            if m:
                results.append(m.group(1))
            else:
                results.append(line)
        # Pad or trim to expected length
        while len(results) < expected:
            results.append("")
        return results[:expected]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[TranslationProvider]] = {
    "deepl": DeepLProvider,
    "google": GoogleTranslateProvider,
    "openai": OpenAITranslateProvider,
}


def get_translation_provider() -> TranslationProvider | None:
    """Create a translation provider from app config.

    Returns ``None`` if translation is disabled or not configured.
    """
    from app.config import settings

    if not settings.operator_lead_translation_enabled:
        return None

    provider_name = settings.translation_provider
    if provider_name == "none" or provider_name not in _PROVIDERS:
        return None

    api_key = settings.translation_api_key
    if not api_key:
        logger.error(
            "Translation provider '%s' configured but TRANSLATION_API_KEY is not set",
            provider_name,
        )
        return None

    cls = _PROVIDERS[provider_name]
    return cls(
        api_key=api_key,
        timeout=settings.translation_timeout_seconds,
        retries=settings.translation_retries,
        rate_limit_per_minute=settings.translation_rate_limit_per_minute,
    )
