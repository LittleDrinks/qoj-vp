#!/usr/bin/env python3
"""Package only local extension resources; never include browser/user state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    extension = ROOT / 'extension'
    manifest = json.loads((extension / 'manifest.json').read_text())
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    target = out / f"qoj-vp-firefox-{manifest['version']}.xpi"
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(extension.rglob('*')):
            if path.is_file():
                archive.write(path, str(path.relative_to(extension)))
    print(json.dumps({'path': str(target), 'bytes': target.stat().st_size,
                      'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'signed': False}, indent=2))


if __name__ == '__main__':
    main()
