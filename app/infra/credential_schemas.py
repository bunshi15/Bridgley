# app/infra/credential_schemas.py
"""
Provider-specific credential and config schemas.

Validates that channel binding payloads contain the required fields
and rejects unknown keys. This prevents:
- Accidentally storing secrets in config_json (non-encrypted)
- Missing required credentials that would cause silent failures
- Mixing up credential vs config fields
"""
from __future__ import annotations


class CredentialValidationError(Exception):
    """Raised when credential or config validation fails."""


# ---------------------------------------------------------------------------
# Schema definitions: (required_keys, optional_keys)
# ---------------------------------------------------------------------------

_CREDENTIAL_SCHEMAS: dict[str, tuple[set[str], set[str]]] = {
    "meta": (
        {"access_token"},                          # required
        {"app_secret"},                            # optional
    ),
    "telegram": (
        {"bot_token"},                             # required
        {"webhook_secret"},                        # optional
    ),
    "twilio": (
        {"account_sid", "auth_token"},             # required
        set(),                                     # optional
    ),
}

_CONFIG_SCHEMAS: dict[str, tuple[set[str], set[str]]] = {
    "meta": (
        {"phone_number_id"},                       # required
        {"waba_id", "webhook_verify_token", "graph_api_version"},
    ),
    "telegram": (
        set(),                                     # required (none)
        {"channel_mode"},                          # optional
    ),
    "twilio": (
        set(),                                     # required (none)
        {"phone_number", "webhook_url"},           # optional
    ),
}

# Fields that MUST be in credentials (encrypted), not in config (plaintext).
# This prevents accidental leakage of secrets into the unencrypted config_json.
_SECRET_FIELD_NAMES: set[str] = {
    "access_token", "app_secret", "bot_token", "webhook_secret",
    "account_sid", "auth_token", "token", "secret", "password", "key",
    "api_key", "api_secret",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_credentials(provider: str, credentials: dict) -> list[str]:
    """
    Validate credentials dict against provider schema.

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    schema = _CREDENTIAL_SCHEMAS.get(provider)
    if schema is None:
        errors.append(f"Unknown provider: {provider}")
        return errors

    required, optional = schema
    allowed = required | optional

    # Check required keys
    for key in required:
        if key not in credentials or not credentials[key]:
            errors.append(f"Missing required credential: {key}")

    # Check for unknown keys
    unknown = set(credentials.keys()) - allowed
    if unknown:
        errors.append(f"Unknown credential keys: {sorted(unknown)}")

    return errors


def validate_config(provider: str, config: dict) -> list[str]:
    """
    Validate config dict against provider schema.

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    schema = _CONFIG_SCHEMAS.get(provider)
    if schema is None:
        errors.append(f"Unknown provider: {provider}")
        return errors

    required, optional = schema
    allowed = required | optional

    # Check required keys
    for key in required:
        if key not in config or not config[key]:
            errors.append(f"Missing required config: {key}")

    # Check for unknown keys
    unknown = set(config.keys()) - allowed
    if unknown:
        errors.append(f"Unknown config keys: {sorted(unknown)}")

    # SECURITY: Check that no secret fields leaked into config
    leaked = set(config.keys()) & _SECRET_FIELD_NAMES
    if leaked:
        errors.append(
            f"Secret fields must be in 'credentials', not 'config': {sorted(leaked)}"
        )

    return errors


# ---------------------------------------------------------------------------
# Provider account ID extraction
# ---------------------------------------------------------------------------

# For each provider, the config key that uniquely identifies the account.
_PROVIDER_ACCOUNT_ID_KEYS: dict[str, str] = {
    "meta": "phone_number_id",
    "telegram": "bot_token",      # the bot token itself is the unique identifier
    "twilio": "phone_number",
}

# For telegram, the account ID comes from credentials, not config.
_PROVIDER_ACCOUNT_ID_FROM_CREDENTIALS: set[str] = {"telegram"}


def extract_provider_account_id(provider: str, credentials: dict, config: dict) -> str:
    """
    Extract the provider account identifier from credentials/config.

    Returns the provider-specific account ID (e.g., phone_number_id for Meta,
    bot token prefix for Telegram, phone_number for Twilio).

    Returns empty string if not determinable.
    """
    key = _PROVIDER_ACCOUNT_ID_KEYS.get(provider, "")
    if not key:
        return ""

    if provider in _PROVIDER_ACCOUNT_ID_FROM_CREDENTIALS:
        value = credentials.get(key, "")
        # For telegram bot_token, extract just the bot ID portion (before ':')
        if provider == "telegram" and ":" in str(value):
            return str(value).split(":")[0]
        return str(value)
    else:
        return str(config.get(key, ""))


def validate_channel_payload(provider: str, credentials: dict, config: dict) -> None:
    """
    Validate both credentials and config for a channel binding.

    Raises CredentialValidationError with all accumulated errors.
    """
    errors = validate_credentials(provider, credentials)
    errors.extend(validate_config(provider, config))

    if errors:
        raise CredentialValidationError("; ".join(errors))
