"""Open the native QOJ start page and inject the isolated readiness UI prototype."""
from pathlib import Path
import base64
import gzip
import io
import json
import re
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[2]
contest = sys.argv[1] if len(sys.argv) > 1 else "4686"
if not contest.isdigit():
    raise SystemExit("Usage: npm run preview:ready -- <contest ID>")
subprocess.run(["opencli", "browser", "ready-ui", "open",
                f"https://qoj.ac/contest/{contest}/virtual/register", "--window", "foreground"], check=True)
subprocess.run(["opencli", "browser", "ready-ui", "wait", "selector", "#form-register_vp"], check=True)
ui = root / "src/firefox"
html = (ui / "ui.html").read_text()
code = (ui / "ui.js").read_text()

def modal(name, next_name):
    return '<div id="' + name + '-modal"' + html.split('<div id="' + name + '-modal"', 1)[1].split('<div id="' + next_name + '-modal"', 1)[0]

def function(name):
    start = re.search(r'^  function ' + re.escape(name) + r'\(', code, re.M)
    if start is None:
        raise RuntimeError('Workbench function missing: ' + name)
    end = re.search(r'^  (?:async )?function ', code[start.end():], re.M)
    return code[start.start():start.end() + end.start()]

functions = '\n'.join(function(name) for name in [
    'node', 'icon', 'button', 'showMessage', 'hideMessage', 'badge',
    'humanReadableBytes', 'interactiveResource', 'validReadyResource',
    'resourceDescriptors', 'readyResources', 'resourceDownloadKey',
    'renderResourceModal', 'renderManualMode', 'openManualSamples',
])
archive = io.BytesIO()
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as sample:
    sample.writestr('example.in', '1 2\n')
    sample.writestr('example.ans', '3\n')
sample_zip = base64.b64encode(archive.getvalue()).decode()
styles = '\n'.join((ui / name).read_text() for name in [
    'assets/bootstrap/bootstrap.min.css', 'assets/domjudge/style_domjudge.css', 'ui.css'
])
frame = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>' + styles + '\nbody{background:transparent;padding:0}</style><body>'
frame += modal('resources', 'rankland') + modal('rankland', 'manual-samples') + modal('manual-samples', 'delete-contest')
frame += '<script>' + (ui / 'assets/bootstrap/bootstrap.bundle.min.js').read_text() + '\n</script>'
frame += '<script>const EXAMPLE_SAMPLE_ZIP=' + json.dumps(sample_zip) + ';\n' + functions + '\n'
frame += (ui / 'qoj-ready-workbench-prototype.js').read_text() + '\n</script></body></html>'
compressed = base64.b64encode(gzip.compress(frame.encode())).decode()
source = (ui / "qoj-ready-prototype.js").read_text().replace('/* WORKBENCH_FRAME */null', json.dumps(compressed))
raise SystemExit(subprocess.run(["opencli", "browser", "ready-ui", "eval", source]).returncode)
