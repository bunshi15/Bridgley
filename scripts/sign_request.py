#!/usr/bin/env python3
"""
Sign admin API requests using HMAC-SHA256.

The secret (ADMIN_TOKEN) never leaves your machine - only the signature is sent.

Usage:
    # Sign a GET request
    python scripts/sign_request.py GET /admin/sessions/cleanup

    # Sign a POST request with body
    python scripts/sign_request.py POST /admin/reset --body '{"confirm": true}'

    # Use with curl (copy-paste the output)
    python scripts/sign_request.py GET /admin/sessions/cleanup --curl

    # Full example with curl
    eval $(python scripts/sign_request.py GET /admin/sessions/cleanup --curl --host http://localhost:8099)

Environment:
    ADMIN_TOKEN: Your admin secret (required)

Output:
    X-Timestamp: 1699999999
    X-Signature: abc123...

    Or with --curl flag:
    curl -H "X-Timestamp: 1699999999" -H "X-Signature: abc123..." http://host/path
"""
import argparse
import hashlib
import hmac
import os
import sys
import time


def compute_signature(secret: str, timestamp: str, method: str, path: str, body: str = "") -> str:
    """Compute HMAC-SHA256 signature matching server's verify_request_signature."""
    body_bytes = body.encode() if body else b""
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    signing_string = f"{timestamp}.{method.upper()}.{path}.{body_hash}"

    signature = hmac.new(
        secret.encode(),
        signing_string.encode(),
        hashlib.sha256
    ).hexdigest()

    return signature


def main():
    parser = argparse.ArgumentParser(
        description="Sign admin API requests with HMAC-SHA256",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("method", help="HTTP method (GET, POST, PUT, DELETE)")
    parser.add_argument("path", help="Request path (e.g., /admin/sessions/cleanup)")
    parser.add_argument("--body", "-b", default="", help="Request body (for POST/PUT)")
    parser.add_argument("--curl", "-c", action="store_true", help="Output as curl command")
    parser.add_argument("--host", "-H", default="http://localhost:8099", help="Host URL for curl")
    parser.add_argument("--token", "-t", help="Admin token (or use ADMIN_TOKEN env var)")

    args = parser.parse_args()

    # Get token
    token = args.token or os.environ.get("ADMIN_TOKEN")
    if not token:
        print("Error: ADMIN_TOKEN environment variable not set", file=sys.stderr)
        print("Set it with: export ADMIN_TOKEN=your-secret-token", file=sys.stderr)
        sys.exit(1)

    # Generate timestamp and signature
    timestamp = str(int(time.time()))
    signature = compute_signature(token, timestamp, args.method, args.path, args.body)

    if args.curl:
        # Output as curl command
        cmd_parts = [
            "curl",
            f'-X {args.method.upper()}',
            f'-H "X-Timestamp: {timestamp}"',
            f'-H "X-Signature: {signature}"',
        ]

        if args.body:
            cmd_parts.append(f'-H "Content-Type: application/json"')
            cmd_parts.append(f"-d '{args.body}'")

        cmd_parts.append(f'"{args.host}{args.path}"')

        print(" \\\n  ".join(cmd_parts))
    else:
        # Output headers only
        print(f"X-Timestamp: {timestamp}")
        print(f"X-Signature: {signature}")
        print()
        print("# Add these headers to your request")
        print(f"# Valid for 5 minutes from: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(timestamp)))}")


if __name__ == "__main__":
    main()
