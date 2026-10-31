#!/usr/bin/env python3
"""Inspect only acceptance-created Clone-Ranran.pdf and samples-C*.zip.

PDF verification uses parsed pdfinfo URI annotations. URI values and unrelated
Firefox preference values are never reported; cookies/history are not read.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, unquote, urlsplit
import zipfile

PREF_KEYS = {'browser.download.dir', 'browser.download.lastDir', 'browser.download.folderList',
             'browser.download.useDownloadDir'}
INPUT = b'5\n1 1 1\n2 3 3\n9 9 9\n3 26 47\n1064 822 1048576\n'
ANSWER = b'1\n7\n45\n44\n21860\n'


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sensitive_query(uri):
    """Return a boolean only; never expose URI or key values in diagnostics."""
    parsed = urlsplit(uri)
    if parsed.username is not None or parsed.password is not None:
        return True
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        for _ in range(3):
            decoded = unquote(key)
            if decoded == key:
                break
            key = decoded
        normalized = re.sub(r'[^a-z0-9]', '', key.casefold())
        if ('token' in normalized or normalized in {'password', 'passwd', 'authorization', 'auth', 'apikey',
                'session', 'sessionid', 'sid', 'secret', 'signature', 'sig', 'credential', 'credentials'}):
            return True
    return False


def inspect_pdf(path):
    result = {'exists': path.is_file(), 'verification': 'unverified', 'safeForExport': False,
              'uriValuesReported': False}
    if not result['exists']:
        result['reason'] = 'owned-pdf-not-found'
        return result
    result.update(filename=path.name, bytes=path.stat().st_size, sha256=file_hash(path))
    try:
        with path.open('rb') as stream:
            result['validHeader'] = stream.read(5) == b'%PDF-'
        completed = subprocess.run(['pdfinfo', '-url', str(path)], capture_output=True, timeout=30)
        if completed.returncode != 0 or completed.stderr.strip() or not result['validHeader']:
            result['reason'] = 'pdfinfo-uri-extraction-failed-or-warned'
            return result
        lines = completed.stdout.decode('utf-8', errors='strict').splitlines()
        header = next((i for i, line in enumerate(lines) if re.fullmatch(r'\s*Page\s+Type\s+URL\s*', line)), None)
        if header is None:
            result['reason'] = 'pdfinfo-uri-format-not-recognized'
            return result
        count = unsafe = 0
        for line in lines[header + 1:]:
            if not line.strip():
                continue
            match = re.fullmatch(r'\s*\d+\s+\S+\s+(.+?)\s*', line)
            if not match:
                result['reason'] = 'pdfinfo-uri-row-not-parsed'
                return result
            count += 1
            unsafe += int(sensitive_query(match[1]))
        result.update(parsedUriCount=count, sensitiveUriCount=unsafe, sensitiveQueryDetected=bool(unsafe))
        if unsafe:
            result['reason'] = 'sensitive-query-key-or-userinfo-detected'
        else:
            result.update(verification='verified', safeForExport=True, verificationMethod='pdfinfo -url parsed annotations')
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
        result.update(reason='pdf-uri-verification-unavailable', errorType=type(exc).__name__)
    return result


def download_directories(home):
    """Read only four explicit prefs; never log prefs.js or other settings."""
    directories, seen, matched_profiles = [], set(), 0

    def add(path, source):
        candidate = Path(path).expanduser()
        if candidate.is_absolute() and str(candidate) not in seen:
            seen.add(str(candidate))
            directories.append((candidate, source))

    for base in (home / '.mozilla/firefox-esr', home / '.mozilla/firefox'):
        for prefs_file in sorted(base.glob('*/prefs.js')):
            prefs = {}
            try:
                with prefs_file.open(encoding='utf-8') as stream:
                    for line in stream:
                        if not any('"' + key + '"' in line for key in PREF_KEYS):
                            continue
                        match = re.fullmatch(r'\s*user_pref\("([^"\\]+)",\s*(.*?)\);\s*', line)
                        if match and match[1] in PREF_KEYS:
                            prefs[match[1]] = json.loads(match[2])
            except (OSError, ValueError, UnicodeError):
                continue
            matched_profiles += bool(prefs)
            for key in ('browser.download.dir', 'browser.download.lastDir'):
                if isinstance(prefs.get(key), str):
                    add(prefs[key], 'firefox-' + key.rsplit('.', 1)[-1])
            if prefs.get('browser.download.folderList') == 0:
                add(home / 'Desktop', 'firefox-folderList-desktop')
    for kind in ('DOWNLOAD', 'DESKTOP'):
        try:
            resolved = subprocess.run(['xdg-user-dir', kind], capture_output=True, text=True, timeout=5)
            if resolved.returncode == 0 and resolved.stdout.strip():
                add(resolved.stdout.strip(), 'xdg-' + kind.lower())
        except (OSError, subprocess.TimeoutExpired):
            pass
    add(home / 'Downloads', 'home-downloads-fallback')
    return directories, {'allowedPreferenceKeys': sorted(PREF_KEYS), 'matchingProfileCount': matched_profiles,
                         'candidateDirectoryCount': len(directories), 'cookiesOrHistoryRead': False,
                         'unrelatedPreferenceValuesReported': False}


def inspect_samples(path, source):
    result = {'filename': path.name, 'path': str(path), 'directorySource': source,
              'bytes': path.stat().st_size, 'sha256': file_hash(path), 'verification': 'unverified'}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            safe_names = [name for name in names if re.fullmatch(r'samples-C/\d+\.(in|ans)', name)]
            result.update(members=safe_names, nonstandardMemberCount=len(names) - len(safe_names), memberCount=len(names))
            expected_members = sorted(names) == ['samples-C/1.ans', 'samples-C/1.in']
            bounded = len(infos) <= 1000 and sum(item.file_size for item in infos) <= 1024 * 1024
            result['exactStandardMembers'] = expected_members
            if not bounded:
                result['reason'] = 'archive-size-not-expected-for-owned-samples'
                return result
            input_matches = expected_members and archive.read('samples-C/1.in') == INPUT
            answer_matches = expected_members and archive.read('samples-C/1.ans') == ANSWER
            result.update(inputMatchesExpected=input_matches, answerMatchesExpected=answer_matches,
                          standardSamplePairMatches=bool(expected_members and input_matches and answer_matches))
            if result['standardSamplePairMatches']:
                result['verification'] = 'verified'
            else:
                result['reason'] = 'standard-sample-members-or-content-differ'
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        result.update(reason='owned-sample-archive-could-not-be-verified', errorType=type(exc).__name__)
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / 'results/live-session'
    out.mkdir(parents=True, exist_ok=True)
    result = {'pdf': inspect_pdf(out / 'Clone-Ranran.pdf'), 'samples': []}
    directories, metadata = download_directories(Path.home())
    result['downloadLocationInspection'] = metadata
    seen = set()
    for directory, source in directories:
        for path in sorted(directory.glob('samples-C*.zip')):
            if not path.is_file() or path.is_symlink():
                continue
            identity = path.resolve()
            if identity in seen:
                continue
            seen.add(identity)
            result['samples'].append(inspect_samples(path, source))
    result['status'] = ('verified' if result['pdf']['verification'] == 'verified' and
                        any(item['verification'] == 'verified' for item in result['samples']) else 'unverified')
    report = out / 'artifact-status.json'
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'report': str(report)}))


if __name__ == '__main__':
    main()
