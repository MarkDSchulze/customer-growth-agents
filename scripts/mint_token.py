"""Mint short-lived local demo tokens; production uses configured OIDC."""

import argparse
from datetime import UTC, datetime, timedelta

import jwt

from growth.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("--tenant", default="tenant-demo")
parser.add_argument(
    "--role", choices=["admin", "operator", "viewer", "producer", "platform_admin"], default="admin"
)
args = parser.parse_args()
config = settings()
if len(config.auth_secret) < 32 or config.oidc_issuer:
    raise SystemExit("Local auth secret unavailable or OIDC is configured.")
now = datetime.now(UTC)
print(
    jwt.encode(
        {
            "sub": "local-operator",
            "identityType": "human",
            "tenant": args.tenant,
            "region": "us-east-1",
            "role": args.role,
            "purposes": ["cart_recovery"],
            "iat": now,
            "exp": now + timedelta(hours=2),
            "iss": "growth-local",
            "aud": "growth-api",
        },
        config.auth_secret,
        algorithm="HS256",
    )
)
