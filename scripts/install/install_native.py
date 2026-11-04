#!/usr/bin/env python3
"""Install the one-shot native helper for Firefox on Linux; no daemon."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import sys

HOST = 'org.littledrinks.qoj_vp'
EXTENSION = 'qoj-vp@littledrinks.local'
DESCRIPTION = 'QOJ VP Workbench owned one-shot native helper'
ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, help='Defaults to the existing owned installation state directory')
    parser.add_argument('--qoj-path', type=Path, default=ROOT / 'vendor/qoj-submitter')
    parser.add_argument('--dependencies', type=Path, help='Optional isolated installed Python dependencies')
    parser.add_argument('--uninstall', action='store_true', help='Remove this registration; retain VP records')
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('This installer currently targets Linux Firefox (including the Hydro test VM).')
    manifest = Path.home() / '.mozilla/native-messaging-hosts' / (HOST + '.json')
    previous = None
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        if previous.get('description') != DESCRIPTION or previous.get('name') != HOST:
            parser.error('A registration with this name belongs to another installation; it was preserved.')
    if args.uninstall:
        manifest.unlink(missing_ok=True)
        print('Native helper registration removed. VP records were retained.')
        return
    qoj = args.qoj_path.expanduser().resolve()
    if not (qoj / 'qoj_submitter/client.py').is_file():
        parser.error('Initialize the pinned QOJ submodule: git submodule update --init')
    dependencies = args.dependencies.expanduser().resolve() if args.dependencies else None
    if dependencies:
        sys.path.insert(0, str(dependencies))
    missing = [name for name in ('requests', 'bs4', 'pycurl') if importlib.util.find_spec(name) is None]
    if missing:
        parser.error('Install project dependencies in this Python environment first: ' + ', '.join(missing))
    default_state = Path.home() / '.local/share/qoj-vp'
    if previous and Path(previous.get('path', '')).name == 'native-launcher.sh':
        default_state = Path(previous['path']).parent
    state = (args.state_dir or default_state).expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    launcher = state / 'native-launcher.sh'
    paths = [str(ROOT / 'src'), str(qoj)] + ([str(dependencies)] if dependencies else [])
    content = '#!/bin/sh\n' + '\n'.join([
        'unset QOJ_VP_FIXTURE_ORIGIN',
        'export PYTHONPATH=' + shlex.quote(':'.join(paths)),
        'export QOJ_VP_QOJ_PATH=' + shlex.quote(str(qoj)),
        'export QOJ_VP_STATE_DIR=' + shlex.quote(str(state)),
        'exec ' + shlex.quote(str(Path(sys.executable).absolute())) + ' -m qojvp.native_host', ''])
    launcher.write_text(content)
    launcher.chmod(0o700)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({'name': HOST, 'description': DESCRIPTION, 'path': str(launcher),
                                    'type': 'stdio', 'allowed_extensions': [EXTENSION]}, indent=2) + '\n')
    manifest.chmod(0o600)
    print('Installed Firefox native helper:', manifest)
    print('VP records:', state)
    print('The helper starts for an operation and exits afterward.')


if __name__ == '__main__':
    main()
