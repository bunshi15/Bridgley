#!/usr/bin/env python3
"""
Generate cryptographically secure tokens for configuration.

Usage:
    python scripts/generate_token.py              # Generate default 32-byte token
    python scripts/generate_token.py 48           # Generate 48-byte token
    python scripts/generate_token.py --env        # Output as .env format

Example output:
    ADMIN_TOKEN=Yx8kL2mN9pQ4rS6tU0vW3xZ5aB7cD1eF
    METRICS_TOKEN=fG2hJ4kL6mN8pQ0rS2tU4vW6xZ8aB0cD
"""
import secrets
import sys


def generate_token(length: int = 32) -> str:
    """Generate a URL-safe random token."""
    return secrets.token_urlsafe(length)


def main():
    # Parse args
    length = 32
    env_format = False

    for arg in sys.argv[1:]:
        if arg == "--env":
            env_format = True
        elif arg.isdigit():
            length = int(arg)
        elif arg in ("--help", "-h"):
            print(__doc__)
            return

    if env_format:
        print(f"ADMIN_TOKEN={generate_token(length)}")
        print(f"METRICS_TOKEN={generate_token(length)}")
    else:
        print(generate_token(length))


if __name__ == "__main__":
    main()
