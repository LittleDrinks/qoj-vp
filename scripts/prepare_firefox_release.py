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

ROOT = Path(__file__).resolve().parents[1]
SIGNATURE_FILES = {
    'META-INF/manifest.mf', 'META-INF/mozilla.sf', 'META-INF/mozilla.rsa',
    'META-INF/cose.manifest', 'META-INF/cose.sig',
}


def release_identity(root, tag=None):
    manifest = json.loads((root / 'extension/manifest.json').read_text())
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Release versions must use major.minor.patch')
    python_version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    helper_version = re.search(r'^__version__ = "([^"]+)"',
                               (root / 'qojvp/__init__.py').read_text(), re.MULTILINE)
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


def prepare_release(root, artifacts, output, commit, *, tag=None, signed_xpi=None):
    manifest = release_identity(root, tag)
    version = manifest['version']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Release requires a full Git commit SHA')
    unsigned = artifacts / f'qoj-vp-firefox-{version}-unsigned.xpi'
    verify_xpi(unsigned, root / 'extension', signed=False)
    source = artifacts / 'qoj-vp-mvp-source.tar.gz'
    with tarfile.open(source, 'r:gz') as archive:
        source_commit = archive.extractfile('qoj-vp/SOURCE_COMMIT').read().decode().strip()
        source_manifest = json.load(archive.extractfile('qoj-vp/extension/manifest.json'))
    if source_commit != commit or source_manifest != manifest:
        raise ValueError('Source archive does not describe this commit and manifest')
    wheels = list(artifacts.glob(f'qoj_vp_workbench-{version}-*.whl'))
    if len(wheels) != 1:
        raise ValueError('Expected exactly one matching native helper wheel')
    if signed_xpi:
        verify_xpi(signed_xpi, root / 'extension', signed=True)
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
    status = ('这是 Mozilla unlisted 签名版，可在 Firefox 正常安装，重启后保留。'
              if signed_xpi else
              '**这是未签名开发包，不能在正式版 Firefox 中长期安装。**\n'
              '请先配置 AMO 签名凭据，再运行 signed 发布；不要发布此草稿冒充签名版。')
    notes = f'''QOJ VP Workbench {version}

{status}

提交：`{commit}`。Firefox 140+，Linux Python 3.10+。

安装或升级：

1. 下载 `{xpi_name}` 和 `qoj-vp-mvp-source.tar.gz`。
2. 在运行 Firefox 的 Linux 中将源码包解压到长期保留的目录，按 `INSTALL.md` 安装/更新按需助手。
3. 签名版：Firefox `about:addons` → 齿轮 → 从文件安装附加组件，选择 XPI。
   未签名版只用于 `about:debugging` 临时加载解压后的 `extension/manifest.json`。

助手需与扩展一起更新；只下载 XPI 不会安装 Python 助手。
保持扩展 ID 和助手数据目录不变，直接覆盖升级，无需卸载扩展或删除比赛。
私有 GitHub 仓库需先登录才能下载；当前使用手动下载安装更新。
详细安装步骤见 `INSTALL.md`，文件校验见 `SHA256SUMS`。
'''
    (output / 'RELEASE_NOTES.md').write_text(notes)
    install = '''# Linux / Hydro Contest OS 安装

下载源码包和对应 XPI；在 Firefox 所在 Linux 操作，使用同一普通用户。
源码包已包含固定的 QOJ CLI，无需单独下载 submodule。

首次安装如缺少依赖：

```sh
sudo apt-get install python3-venv python3-dev libcurl4-openssl-dev libssl-dev
```

将本版本源码解压到一个长期保留的目录（例如 ~/.local/share/qoj-vp-app/版本号）：

```sh
tar -xzf qoj-vp-mvp-source.tar.gz
cd qoj-vp
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/python scripts/install_native.py
```

助手按需启动退出，不需要后台常驻。安装注册会指向此目录，安装后不要移动它。
数据在 ~/.local/share/qoj-vp；升级可解压到新版本目录，重复上面安装命令。
若原安装使用自定义 --state-dir，升级时继续指定同一路径。
Hydro 使用系统 Firefox；Snap/Flatpak 的 Native Messaging 沙箱未在本项目验证。

签名 XPI：在 Firefox about:addons → 齿轮 → 从文件安装附加组件。
临时开发版：about:debugging#/runtime/this-firefox → 临时载入附加组件，选择 extension/manifest.json。
现有临时版可先重启 Firefox 再安装签名版，不需要删除任何账本文件。
新版签名 XPI 沿用同一个扩展 ID，可直接覆盖安装；不先卸载，避免清空扩展存储。

在下载目录可运行 sha256sum --check SHA256SUMS 校验所有产物。
'''
    (output / 'INSTALL.md').write_text(install)
    checksums = '\n'.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}'
                          for p in sorted(output.iterdir()) if p.is_file()) + '\n'
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
        metadata = json.loads((ROOT / 'release/amo-metadata.json').read_text())
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
