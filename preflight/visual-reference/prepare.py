#!/usr/bin/env python3
"""Create only this isolated reference's ignored credentials, without printing."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent
private = root / "private"
private.mkdir(mode=0o700, exist_ok=True)
private.chmod(0o700)
for name in ("database-password", "database-root-password"):
    path = private / name
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_urlsafe(32) + "\n")
    path.chmod(0o600)
print("Private reference credentials prepared; values omitted.")
