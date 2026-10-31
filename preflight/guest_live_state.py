#!/usr/bin/env python3
"""Read-only live Firefox/display discovery; never reads cookies or page tokens."""
import configparser
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

root = Path(__file__).resolve().parents[1]
out = root / 'results/live-session'
out.mkdir(parents=True, exist_ok=True)
report = {'observedAt': time.time(), 'firefox': [], 'profiles': [], 'tools': {}, 'qaProcesses': []}
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args = [x.decode(errors='replace') for x in (proc / 'cmdline').read_bytes().split(b'\0') if x]
        if any(str(root / 'preflight/guest_a11y_probe.py') == arg for arg in args):
            report['qaProcesses'].append({'pid': int(proc.name), 'name': 'guest_a11y_probe.py'})
        if not args or Path(args[0]).name not in ('firefox', 'firefox-esr') or '-contentproc' in args:
            continue
        env = dict(item.split(b'=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
        row = {'pid': int(proc.name), 'binary': args[0],
               'headless': any('headless' in x for x in args),
               'display': {k: env[k.encode()].decode(errors='replace') for k in
                           ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE',
                            'XDG_CURRENT_DESKTOP', 'DBUS_SESSION_BUS_ADDRESS') if k.encode() in env}}
        for flag in ('-profile', '--profile', '--start-debugger-server', '-marionette'):
            if flag in args:
                index = args.index(flag)
                row[flag] = args[index + 1] if index + 1 < len(args) else True
        report['firefox'].append(row)
    except OSError:
        continue
for base in (Path.home() / '.mozilla/firefox-esr', Path.home() / '.mozilla/firefox'):
    config = configparser.ConfigParser()
    if not (base / 'profiles.ini').is_file():
        continue
    config.read(base / 'profiles.ini')
    for section in config.sections():
        if config.has_option(section, 'Path'):
            path = Path(config[section]['Path'])
            if config[section].get('IsRelative', '1') == '1':
                path = base / path
            report['profiles'].append({'name': config[section].get('Name'), 'path': str(path),
                                       'locked': (path / '.parentlock').exists()})
for tool in ('xdotool', 'wmctrl', 'gdbus', 'xprop', 'xclip', 'ydotool'):
    report['tools'][tool] = shutil.which(tool)
report['pythonGiAvailable'] = importlib.util.find_spec('gi') is not None
report['pythonDbusAvailable'] = importlib.util.find_spec('dbus') is not None
for firefox in report['firefox']:
    if firefox['headless'] or not report['tools']['xdotool']:
        continue
    env = {**os.environ, **firefox['display']}
    result = subprocess.run(['xdotool', 'getwindowfocus', 'getwindowname'], env=env,
                            capture_output=True, text=True, timeout=5)
    report['focusedGuestWindow'] = result.stdout.strip() if result.returncode == 0 else 'unavailable'
    break
(out / 'status.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
