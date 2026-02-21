#!/usr/bin/env python3
"""Generate a Fernet encryption key for TENANT_ENCRYPTION_KEY.

Usage:
    python scripts/generate_encryption_key.py

The output is a URL-safe base64-encoded 32-byte key suitable for
the TENANT_ENCRYPTION_KEY environment variable.
"""
from cryptography.fernet import Fernet


def main() -> None:
    key = Fernet.generate_key().decode("ascii")
    print("# Add this to your .env file:")
    print(f"TENANT_ENCRYPTION_KEY={key}")


if __name__ == "__main__":
    main()
