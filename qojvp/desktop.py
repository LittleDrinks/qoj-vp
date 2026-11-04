"""User-session setup for the Hydro system package; never run by dpkg as root."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .native_host import read_frame, write_frame

HOST = 'org.littledrinks.qoj_vp'
DESCRIPTION = 'QOJ VP Workbench owned one-shot native helper'
ROOT = Path(__file__).resolve().parents[1]


def migrate_registration(home: Path, config_home: Path):
    """Remove only our legacy per-user override; retain data and a recoverable copy."""
    manifest = home / '.mozilla/native-messaging-hosts' / (HOST + '.json')
    settings = config_home / 'qoj-vp/runtime.json'
    if not manifest.exists():
        return {'migrated': False}
    original = manifest.read_bytes()
    old = json.loads(original)
    if old.get('name') != HOST or old.get('description') != DESCRIPTION:
        raise ValueError('已有浏览器连接配置属于另一安装，请保留并检查。')
    launcher = Path(old.get('path', ''))
    if not launcher.is_absolute() or launcher.name != 'native-launcher.sh':
        raise ValueError('无法确认旧版数据目录，原配置已保留。')
    # install_native.py keeps its launcher directly in the chosen state directory.
    state = launcher.parent
    if settings.exists():
        saved = json.loads(settings.read_text())
        if saved.get('stateDir') != str(state):
            raise ValueError('新旧安装的数据目录不同，原配置已保留。')
    else:
        settings.parent.mkdir(parents=True, exist_ok=True)
        temporary = settings.with_name('runtime.' + uuid.uuid4().hex + '.tmp')
        with open(temporary, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
            json.dump({'stateDir': str(state)}, out)
        temporary.replace(settings)
    backup = manifest.with_name(manifest.name + '.before-deb-' + uuid.uuid4().hex)
    if manifest.read_bytes() != original:
        raise ValueError('配置已被其他程序修改，请重试。')
    manifest.rename(backup)
    return {'migrated': True, 'backup': str(backup), 'stateDir': str(state)}


def check_connection():
    request = io.BytesIO()
    write_frame(request, {'type': 'task', 'id': 'desktop-check', 'method': 'hello', 'args': {}})
    result = subprocess.run([str(ROOT / 'native-host')], input=request.getvalue(), capture_output=True, timeout=20)
    reply = read_frame(io.BytesIO(result.stdout)) if result.stdout else None
    if result.returncode or not reply or not reply.get('ok'):
        raise RuntimeError('连接检查失败，请重新安装本版本。')
    return reply['result']


def configure(home: Path, config_home: Path, check=None):
    """Keep the legacy connection usable if the new system host cannot start."""
    migration = migrate_registration(home, config_home)
    try:
        return migration, (check or check_connection)()
    except Exception:
        if migration.get('migrated'):
            backup = Path(migration['backup'])
            manifest = home / '.mozilla/native-messaging-hosts' / (HOST + '.json')
            # Never overwrite a concurrent installer. Hard-link is exclusive.
            try:
                os.link(backup, manifest)
            except FileExistsError:
                pass
            else:
                backup.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description='Configure QOJ Workbench for Hydro Contest OS')
    parser.add_argument('--check', action='store_true', help='Configure and check without opening Firefox')
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error('请以桌面登录用户运行 QOJ Workbench。')
    try:
        migration, hello = configure(Path.home(), Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')))
        if args.check:
            print(json.dumps({'ok': True, 'version': hello['version'], 'stateDir': hello['stateDir'], **migration}))
        else:
            subprocess.Popen(['/usr/bin/firefox-esr', '--new-tab', (ROOT / 'welcome.html').as_uri()],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        if args.check:
            print(json.dumps({'ok': False, 'error': str(error)})); return 1
        subprocess.run(['zenity', '--error', '--title=QOJ Workbench', '--text=' + str(error)], check=False)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
