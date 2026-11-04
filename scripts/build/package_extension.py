#!/usr/bin/env python3
"""Package only local extension resources; never include browser/user state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    extension = ROOT / 'src/firefox'
    required = ('engine.js', 'view.js', 'view.css', 'upstream.json',
                'standard-ranklist-utils.LICENSE', 'standard-ranklist-renderer-component.LICENSE')
    if any(not (extension / 'board/generated' / name).is_file() for name in required):
        raise SystemExit('Build the Board first: npm ci && npm run build:board')
    manifest = json.loads((extension / 'manifest.json').read_text())
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    target = out / f"qoj-vp-firefox-{manifest['version']}-unsigned.xpi"
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(extension.rglob('*')):
            if path.is_file() and path.name != '.amo-upload-uuid':
                # Source archives normalize mtimes to 1970, before ZIP's epoch.
                # A fixed ZIP timestamp also makes clean rebuilds reproducible.
                entry = zipfile.ZipInfo(str(path.relative_to(extension)))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, path.read_bytes())
    print(json.dumps({'path': str(target), 'bytes': target.stat().st_size,
                      'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'signed': False}, indent=2))


if __name__ == '__main__':
    main()
