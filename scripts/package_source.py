#!/usr/bin/env python3
"""Archive committed sources and exact gitlink contents without local state."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SUBMODULE = 'vendor/qoj-submitter'
EXCLUDED_ROOTS = {'artifacts', 'state', 'results', 'dist', 'build', '.scratch', '.git'}


def git(repository, *arguments):
    return subprocess.check_output(['git', '-C', str(repository), *arguments])


def committed_files(repository, revision, prefix=''):
    exported = git(repository, 'archive', '--format=tar', revision)
    files = []
    with tarfile.open(fileobj=io.BytesIO(exported), mode='r:') as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            name = PurePosixPath(prefix + member.name)
            if not member.isfile() or name.is_absolute() or '..' in name.parts:
                raise ValueError('Only regular source files are supported: ' + str(name))
            if name.parts[0] in EXCLUDED_ROOTS or '.git' in name.parts or '.env' in name.parts:
                raise ValueError('Local state must not be tracked in a release: ' + str(name))
            files.append((str(name), archive.extractfile(member).read(), member.mode & 0o777))
    return files


def package_source(repository=ROOT, output_directory=None):
    repository = Path(repository).resolve()
    output_directory = Path(output_directory or repository / 'dist').resolve()
    commit = git(repository, 'rev-parse', 'HEAD').decode().strip()
    gitlink = git(repository, 'ls-tree', commit, '--', SUBMODULE).decode().strip().split()
    if len(gitlink) != 4 or gitlink[:2] != ['160000', 'commit'] or gitlink[3] != SUBMODULE:
        raise ValueError('The QOJ CLI must be a pinned submodule')
    submodules = {}
    files = committed_files(repository, commit)
    # Include every pinned gitlink, not only the original Python CLI.
    for entry in git(repository, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, revision = metadata.decode().split()
        if mode == '160000' and kind == 'commit':
            path = name.decode()
            submodules[path] = revision
            files.extend(committed_files(repository / path, revision, path + '/'))
    files.append(('SOURCE_COMMIT', (commit + '\n').encode(), 0o644))
    files.sort()
    if len({name for name, _, _ in files}) != len(files):
        raise ValueError('Duplicate source archive paths')
    manifest = {'schema': 'qoj-vp-source-v1', 'commit': commit,
                'submodules': submodules,
                'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data, _ in files]}
    files.append(('SOURCE_MANIFEST.json', (json.dumps(manifest, indent=2) + '\n').encode(), 0o644))
    output_directory.mkdir(parents=True, exist_ok=True)
    target = output_directory / 'qoj-vp-mvp-source.tar.gz'
    with target.open('wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|') as archive:
                for name, data, mode in files:
                    member = tarfile.TarInfo('qoj-vp/' + name)
                    member.size, member.mode, member.mtime = len(data), mode, 0
                    archive.addfile(member, io.BytesIO(data))
    return {'filename': target.name, 'bytes': target.stat().st_size,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'commit': commit,
            'submodules': manifest['submodules'], 'fileCount': len(manifest['files'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(package_source(output_directory=args.output_dir), indent=2))


if __name__ == '__main__':
    main()
