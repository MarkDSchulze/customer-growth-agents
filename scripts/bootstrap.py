"""Create local secrets once; never overwrite a developer's configuration."""

import json
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values

path = Path(".env")
if not path.exists():
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write("GROWTH_AUTH_SECRET=" + secrets.token_urlsafe(48) + "\n")
        file.write("GROWTH_DB_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
        file.write("GROWTH_APP_DB_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
    print("Created private .env for synthetic local development.")
else:
    print("Kept existing .env.")

# Add newly introduced local-only credentials without changing any existing value.

values = dotenv_values(path)
if not values.get("GROWTH_SANDBOX_BINDINGS"):
    binding = {"tenant-demo": {"region": "us-east-1", "token": secrets.token_urlsafe(40)}}
    with path.open("a") as file:
        file.write("GROWTH_SANDBOX_BINDINGS='" + json.dumps(binding, separators=(",", ":")) + "'\n")
    print("Added private synthetic connector binding.")
