#!/usr/bin/env python3
"""Validate a CI build and assemble a Firefox release without user state."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import tomllib
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build.package_hydro import package_hydro
SIGNATURE_FILES = {
    'META-INF/manifest.mf', 'META-INF/mozilla.sf', 'META-INF/mozilla.rsa',
    'META-INF/cose.manifest', 'META-INF/cose.sig',
}


def release_identity(root, tag=None):
    manifest = json.loads((root / 'src/firefox/manifest.json').read_text())
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Release versions must use major.minor.patch')
    python_version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    helper_version = re.search(r'^__version__ = "([^"]+)"',
                               (root / 'src/qojvp/__init__.py').read_text(), re.MULTILINE)
    if python_version != version or not helper_version or helper_version[1] != version:
        raise ValueError('Extension and native helper versions must agree')
    if tag and tag != 'v' + version:
        raise ValueError(f'Tag {tag} does not match manifest version {version}')
    return manifest


def canonical_manifest(contents):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('XPI manifest contains duplicate fields')
            result[key] = value
        return result
    # Compare typed JSON values, not Python dict equality (where True == 1).
    return json.dumps(json.loads(contents, object_pairs_hook=unique_object),
                      sort_keys=True, separators=(',', ':'), allow_nan=False)


def verify_xpi(path, extension, *, signed):
    expected = {str(p.relative_to(extension)): p.read_bytes()
                for p in sorted(extension.rglob('*')) if p.is_file()
                and p.name != '.amo-upload-uuid'}
    with zipfile.ZipFile(path) as archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError('XPI contains duplicate paths')
        actual = {entry.filename: archive.read(entry) for entry in entries}
    signatures = {name: actual.pop(name) for name in SIGNATURE_FILES if name in actual}
    # The signing pipeline reformats manifest.json. Only that file may differ
    # in JSON formatting; never rewrite the downloaded, signed ZIP itself.
    if signed and 'manifest.json' in actual and 'manifest.json' in expected:
        if canonical_manifest(actual['manifest.json']) == canonical_manifest(expected['manifest.json']):
            actual['manifest.json'] = expected['manifest.json']
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        changed = sorted(name for name in actual.keys() & expected.keys() if actual[name] != expected[name])
        raise ValueError(f'XPI payload differs from the tested extension: missing={missing}, extra={extra}, changed={changed}')
    has_signature = (
        all(signatures.get(name) for name in ('META-INF/mozilla.rsa', 'META-INF/mozilla.sf', 'META-INF/manifest.mf'))
        or all(signatures.get(name) for name in ('META-INF/cose.sig', 'META-INF/cose.manifest'))
    )
    if signed and not has_signature:
        raise ValueError('AMO output has no Firefox signature files')
    if not signed and signatures:
        raise ValueError('Expected the original unsigned CI package')
    # This checks presence and unchanged payload, not cryptographic authenticity.
    # Signing provenance is web-ext -> AMO over HTTPS; Firefox verifies the signature.


def release_notes(version, signed):
    base = f'https://github.com/LittleDrinks/qoj-vp/releases/download/v{version}'
    status = ('已签名，可在 Firefox 安装并保留。' if signed else
              '**未签名开发包，仅用于 Firefox 临时调试，重启后失效。**')
    if not signed:
        return status + '\n\n开发包用于 `about:debugging` 临时加载。\n'
    return f'''{status}

**[下载]({base}/qoj-vp_{version}_amd64.deb)** · Hydro Contest OS 2026

```sh
sudo apt install ./qoj-vp_{version}_amd64.deb
```

安装后从应用菜单打开 **QOJ Workbench**，在 Firefox 确认添加扩展。升级安装新版即可，比赛记录保留。
'''



def prepare_release(root, artifacts, output, commit, *, tag=None, signed_xpi=None):
    manifest = release_identity(root, tag)
    version = manifest['version']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Release requires a full Git commit SHA')
    unsigned = artifacts / f'qoj-vp-firefox-{version}-unsigned.xpi'
    verify_xpi(unsigned, root / 'src/firefox', signed=False)
    source = artifacts / 'qoj-vp-mvp-source.tar.gz'
    with tarfile.open(source, 'r:gz') as archive:
        source_commit = archive.extractfile('qoj-vp/SOURCE_COMMIT').read().decode().strip()
        source_manifest = json.load(archive.extractfile('qoj-vp/src/firefox/manifest.json'))
    if source_commit != commit or source_manifest != manifest:
        raise ValueError('Source archive does not describe this commit and manifest')
    wheels = list(artifacts.glob(f'qoj_vp_workbench-{version}-*.whl'))
    if len(wheels) != 1:
        raise ValueError('Expected exactly one matching native helper wheel')
    if signed_xpi:
        verify_xpi(signed_xpi, root / 'src/firefox', signed=True)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Release output must be empty')
    output.mkdir(parents=True, exist_ok=True)
    suffix = 'signed' if signed_xpi else 'unsigned'
    xpi_name = f'qoj-vp-firefox-{version}-{suffix}.xpi'
    shutil.copyfile(signed_xpi or unsigned, output / xpi_name)
    for path in (source, wheels[0]):
        shutil.copyfile(path, output / path.name)
    metadata = {'version': version, 'tag': 'v' + version, 'commit': commit,
                'extensionId': manifest['browser_specific_settings']['gecko']['id'],
                'mozillaSigned': bool(signed_xpi), 'xpi': xpi_name}
    (output / 'release.json').write_text(json.dumps(metadata, indent=2) + '\n')
    bundle = package_hydro(root, output, xpi=signed_xpi, development=not bool(signed_xpi), source_archive=source)
    bundle_name = bundle.name
    notes = release_notes(version, bool(signed_xpi))
    (output / 'RELEASE_NOTES.md').write_text(notes)
    checksums = '\n'.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}'
                          for p in (output / xpi_name, output / bundle_name)) + '\n'
    (output / 'SHA256SUMS').write_text(checksums)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag')
    parser.add_argument('--commit')
    parser.add_argument('--artifacts', type=Path, default=ROOT / 'dist')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--signed-xpi', type=Path)
    parser.add_argument('--check-version', action='store_true')
    parser.add_argument('--amo-metadata', type=Path)
    args = parser.parse_args()
    if args.amo_metadata:
        metadata = json.loads((ROOT / 'scripts/release/amo-metadata.json').read_text())
        # AMO's predefined GPL-2.0-only slug would narrow this project's license.
        metadata['version']['custom_license'] = {
            'name': {'en-US': 'GNU General Public License v2.0 or later'},
            'text': {'en-US': 'QOJ VP Workbench is licensed under GPL-2.0-or-later.\n\n'
                     + (ROOT / 'LICENSE').read_text()}}
        args.amo_metadata.write_text(json.dumps(metadata, indent=2) + '\n')
    elif args.check_version:
        print(release_identity(ROOT, args.tag)['version'])
    else:
        print(json.dumps(prepare_release(ROOT, args.artifacts, args.output, args.commit or '',
                                         tag=args.tag, signed_xpi=args.signed_xpi), indent=2))


if __name__ == '__main__':
    main()
