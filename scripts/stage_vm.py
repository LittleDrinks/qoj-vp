#!/usr/bin/env python3
"""Build a reproducible VM test payload without project/user runtime state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    entries = ['extension', 'qojvp', 'vendor/qoj-submitter', 'scripts', 'pyproject.toml', 'LICENSE',
               'docs/ARCHITECTURE.md', 'docs/UI_UPSTREAM.md', 'preflight/vendor_py',
               'preflight/tools/geckodriver', 'preflight/fixtures', 'preflight/rankland-fixtures',
               'preflight/fixture_server.py', 'preflight/mvp_fixture_server.py',
               'preflight/guest_preflight.py', 'preflight/guest_mvp.py', 'preflight/mvp_ui_probe.py',
               'preflight/job-mvp.sh']
    target = ROOT / 'artifacts/mvp-payload.tar.gz'
    target.parent.mkdir(exist_ok=True)
    files = []
    for entry in entries:
        path = ROOT / entry
        if not path.exists():
            raise SystemExit('Missing payload source: ' + entry)
        for member in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if not member.is_file() or any(part in {'.git', '__pycache__'} for part in member.relative_to(ROOT).parts):
                continue
            files.append(member)
    records = []
    with tarfile.open(target, 'w:gz') as archive:
        for path in files:
            name = str(path.relative_to(ROOT))
            archive.add(path, arcname=name, recursive=False)
            records.append({'path': name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    metadata = {'archive': target.name, 'bytes': target.stat().st_size,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'files': records}
    (ROOT / 'artifacts/mvp-payload.json').write_text(json.dumps(metadata, indent=2) + '\n')
    shared = Path('/mnt/e/shared/qoj-vp-preflight-stage')
    if shared.is_dir():
        shutil.copy2(target, shared / target.name)
    print(json.dumps({key: value for key, value in metadata.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()
