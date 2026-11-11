"""Small, deterministic committed-source secret check; complements dependency/SAST checks."""

import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
excluded = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "work",
    "test-results",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}
patterns = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]
failures = []
for path in root.rglob("*"):
    if not path.is_file() or any(part in excluded for part in path.relative_to(root).parts):
        continue
    if path.name == ".env" or path.suffix in {".db", ".png", ".jpg", ".woff", ".pyc"}:
        continue
    try:
        content = path.read_text()
    except UnicodeError:
        continue
    if any(pattern.search(content) for pattern in patterns):
        failures.append(str(path.relative_to(root)))
if failures:
    raise SystemExit("Potential secret in: " + ", ".join(failures))
print("No private keys, cloud access keys, GitHub tokens or JWTs found in source.")
