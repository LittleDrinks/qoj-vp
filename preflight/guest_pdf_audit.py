#!/usr/bin/env python3
"""Read the installed Firefox PDF API implementation, without browser startup."""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/pdf-audit'
OUT.mkdir(parents=True, exist_ok=True)
report = {'browserStarted': False, 'archives': [], 'sources': []}
for archive in sorted(Path('/usr/lib/firefox-esr').rglob('omni.ja')):
    report['archives'].append(str(archive))
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            if not (name.endswith('/ext-tabs.js') or name.endswith('/schemas/tabs.json')):
                continue
            source = zipped.read(name).decode('utf-8')
            start = source.find('saveAsPDF')
            if start < 0:
                continue
            snippet = source[max(0, start - 120):start + 14000]
            path = OUT / (str(len(report['sources'])) + '-' + Path(name).name)
            path.write_text(snippet)
            report['sources'].append({'archive': str(archive), 'entry': name, 'artifact': str(path)})
(OUT / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
