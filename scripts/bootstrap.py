"""Create local secrets once; never overwrite a developer's configuration."""

import os
import secrets
from pathlib import Path

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
