#!/usr/bin/env python3
"""Build the Hydro Contest OS 2026 package; no pip, daemon or user-home postinst."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def package_hydro(root, output, *, xpi=None, development=False, source_archive=None):
    root, output = Path(root), Path(output)
    manifest = json.loads((root / 'extension/manifest.json').read_text())
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid package version')
    if xpi is None and not development:
        raise ValueError('A signed extension is required for an installable package')
    # Release assembly verifies the signature envelope and exact payload first.
    if xpi is not None:
        from scripts.prepare_firefox_release import verify_xpi
        verify_xpi(xpi, root / 'extension', signed=not development)
    deb_version = version + ('~dev' if development else '')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hydro-package-', dir=output) as work:
        stage = Path(work)
        app = stage / 'usr/lib/qoj-vp'
        app.mkdir(parents=True)
        def copy_tree(source, target):
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc', '.pytest_cache'))
        copy_tree(root / 'qojvp', app / 'qojvp')
        copy_tree(root / 'vendor/qoj-submitter/qoj_submitter', app / 'vendor/qoj-submitter/qoj_submitter')
        for name in ['native-host','welcome.html']:
            shutil.copyfile(root / 'packaging/hydro' / name, app / name)
        (app / 'native-host').chmod(0o755)
        if xpi:
            shutil.copyfile(xpi, app / 'firefox.xpi')
        else:
            (app / 'welcome.html').write_text('<!doctype html><meta charset="utf-8"><h1>开发测试包</h1><p>此包不含签名扩展。</p>')
        def put(path, data, mode=0o644):
            target=stage/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(data);target.chmod(mode)
        put('usr/bin/qoj-vp',(root/'packaging/hydro/qoj-vp').read_text(),0o755)
        put('usr/share/applications/qoj-vp.desktop',(root/'packaging/hydro/qoj-vp.desktop').read_text())
        icon=stage/'usr/share/icons/hicolor/32x32/apps/qoj-vp.png';icon.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/'extension/icons/domjudge-32.png',icon)
        put('usr/lib/mozilla/native-messaging-hosts/org.littledrinks.qoj_vp.json',json.dumps({
            'name':'org.littledrinks.qoj_vp','description':'QOJ VP Workbench owned one-shot native helper',
            'path':'/usr/lib/qoj-vp/native-host','type':'stdio','allowed_extensions':[manifest['browser_specific_settings']['gecko']['id']]},indent=2)+'\n')
        put('usr/share/doc/qoj-vp/copyright',(root/'LICENSE').read_text())
        for name in ['qoj-submitter','standard-ranklist-utils','standard-ranklist-renderer-component']:
            license_file=root/'vendor'/name/'LICENSE'
            if license_file.exists():put('usr/share/doc/qoj-vp/'+name+'.LICENSE',license_file.read_text())
        if source_archive:
            shutil.copyfile(source_archive,stage/'usr/share/doc/qoj-vp/source.tar.gz')
        size=sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())//1024+1
        put('DEBIAN/control',f'''Package: qoj-vp
Version: {deb_version}
Section: education
Priority: optional
Architecture: amd64
Maintainer: LittleDrinks <littledrinks@users.noreply.github.com>
Depends: python3 (>= 3.12), python3 (<< 3.13), python3-requests (>= 2.31), python3-bs4 (>= 4.12), python3-pycurl (>= 7.45), firefox-esr (>= 140), zenity
Installed-Size: {size}
Homepage: https://github.com/LittleDrinks/qoj-vp
Description: QOJ Workbench for Hydro Contest OS 2026
 DOMjudge team pages and local ranklist replay for QOJ practice.
 Tested target: Hydro Contest OS 2026, Ubuntu 24.04 amd64, Firefox ESR.
''')
        put('DEBIAN/preinst',(root/'packaging/hydro/preinst').read_text(),0o755)
        target=output/f'qoj-vp_{deb_version}_amd64.deb'
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(target)],check=True,capture_output=True)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--signed-xpi',type=Path)
    parser.add_argument('--development',action='store_true')
    args=parser.parse_args()
    print(package_hydro(ROOT,args.output,xpi=args.signed_xpi,development=args.development))

if __name__=='__main__':main()
