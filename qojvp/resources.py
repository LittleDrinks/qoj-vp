"""Account-scoped resource objects and atomic manifests; no HTTP or timers."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .transport import BASE

MAX_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024
MAX_ENTRY_BYTES = 256 * 1024
MAX_MANIFEST_RESULT_BYTES = 900 * 1024


class ResourceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def problem_id(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,20}', str(value)):
        raise ResourceError('VALIDATION_ERROR', 'Expected a numeric resource problem ID')
    return str(value)


class ResourceCache:
    def __init__(self, directory):
        self.directory = Path(directory) / 'resources'

    def scope(self, session, pid=None):
        account = session.get('account')
        if not account:
            return None
        scope = {'origin': BASE, 'account': account.casefold(), 'contestId': str(session['contestId'])}
        if pid is not None:
            scope['problemId'] = problem_id(pid)
        return scope

    def scope_path(self, session, pid=None):
        outer = self.scope(session)
        if outer is None:
            raise ResourceError('RESOURCE_NOT_FOUND', 'No resource account is bound to this session')
        path = self.directory / hashlib.sha256(encoded(outer)).hexdigest()
        if pid is not None:
            path = path / hashlib.sha256(encoded(self.scope(session, pid))).hexdigest()
        # No caller-supplied path components are used. Refuse local symlinks
        # instead of letting a cache lookup walk into unrelated local files.
        for part in [self.directory, *path.relative_to(self.directory).parents, path]:
            candidate = part if part.is_absolute() else self.directory / part
            if candidate.is_symlink():
                raise ResourceError('CACHE_CORRUPT', 'Resource cache contains an unexpected link')
        return path

    @staticmethod
    def atomic_write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.resource-write-')
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                os.chmod(temporary, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def locked(self, path):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def read_entry(self, session, pid):
        path = self.scope_path(session, pid) / 'manifest.json'
        if not path.exists():
            return None
        try:
            if path.is_symlink() or path.stat().st_size > MAX_ENTRY_BYTES:
                raise ValueError()
            data = json.loads(path.read_bytes())
            if data['schema'] != 1 or data['scope'] != self.scope(session, pid):
                raise ValueError()
            entry = data['entry']
            if entry['problemId'] != problem_id(pid) or entry['status'] not in {'ready', 'unknown'}:
                raise ValueError()
            return entry
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise ResourceError('CACHE_CORRUPT', 'The resource manifest could not be verified') from exc

    def write_entry(self, session, pid, entry):
        payload = encoded({'schema': 1, 'scope': self.scope(session, pid), 'entry': entry})
        if len(payload) > MAX_ENTRY_BYTES:
            raise ResourceError('RESOURCE_METADATA_TOO_LARGE', 'Resource file metadata exceeds the manifest limit')
        self.atomic_write(self.scope_path(session, pid) / 'manifest.json', payload)

    def object_path(self, session, pid, entry):
        rid = entry.get('resourceId')
        if (not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{64}', rid)
                or entry.get('sha256') != rid):
            raise ResourceError('CACHE_CORRUPT', 'Resource object identity is invalid')
        path = self.scope_path(session, pid) / 'objects' / (rid + '.zip')
        if path.parent.is_symlink() or path.is_symlink():
            raise ResourceError('CACHE_CORRUPT', 'Resource object contains an unexpected link')
        return path

    @contextmanager
    def verified_object(self, session, pid, entry):
        path = self.object_path(session, pid, entry)
        try:
            stream = path.open('rb')
        except OSError as exc:
            raise ResourceError('CACHE_CORRUPT', 'The cached resource object is missing') from exc
        with stream:
            total = entry.get('totalBytes')
            if isinstance(total, bool) or not isinstance(total, int) or not 0 < total <= MAX_RESOURCE_BYTES:
                raise ResourceError('CACHE_CORRUPT', 'Resource object size metadata is invalid')
            before = os.fstat(stream.fileno())
            digest, count = hashlib.sha256(), 0
            while True:
                chunk = stream.read(MAX_CHUNK_BYTES)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_RESOURCE_BYTES:
                    raise ResourceError('CACHE_CORRUPT', 'Resource object exceeds its allowed size')
                digest.update(chunk)
            if count != total or before.st_size != total or digest.hexdigest() != entry['sha256']:
                raise ResourceError('CACHE_CORRUPT', 'The cached resource size or SHA-256 does not match')
            yield stream
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ResourceError('CACHE_CORRUPT', 'The cached resource changed during reading')

    def unknown(self, session, pid, code, at, *, label=None, interactive_hint=False):
        pid = problem_id(pid)
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', code):
            code = 'QOJ_ERROR'
        attempt = {'status': 'unknown', 'code': code, 'at': at, 'interactiveHint': interactive_hint}
        empty = {'problemId': pid, 'status': 'unknown', 'lastAttempt': attempt}
        if label:
            empty['problemLabel'] = label
        if not session.get('account'):
            return empty
        path = self.scope_path(session, pid)
        with self.locked(path):
            try:
                old = self.read_entry(session, pid)
                if old and old['status'] == 'ready':
                    with self.verified_object(session, pid, old):
                        pass
                    entry = {**old, 'lastAttempt': attempt}
                else:
                    entry = empty
            except ResourceError:
                entry = empty
            self.write_entry(session, pid, entry)
        return entry

    def store(self, session, pid, metadata, payload, at):
        if not payload or len(payload) > MAX_RESOURCE_BYTES:
            raise ResourceError('ARTIFACT_TOO_LARGE', 'The resource archive exceeds the 64 MiB cache limit')
        pid = problem_id(pid)
        digest = hashlib.sha256(payload).hexdigest()
        entry = {**metadata, 'problemId': pid, 'status': 'ready', 'resourceId': digest,
                 'totalBytes': len(payload), 'sha256': digest, 'preparedAt': at,
                 'lastAttempt': {'status': 'ready', 'at': at}}
        # Validate metadata size before creating an otherwise unreachable object.
        if len(encoded({'schema': 1, 'scope': self.scope(session, pid), 'entry': entry})) > MAX_ENTRY_BYTES:
            raise ResourceError('RESOURCE_METADATA_TOO_LARGE', 'Resource file metadata exceeds the manifest limit')
        path = self.scope_path(session, pid)
        with self.locked(path):
            self.atomic_write(self.object_path(session, pid, entry), payload)
            self.write_entry(session, pid, entry)
        return entry

    def manifest(self, session):
        result = {'origin': BASE, 'account': session.get('account'), 'contestId': str(session['contestId']), 'problems': []}
        if not session.get('account'):
            return result
        path = self.scope_path(session)
        if not path.exists():
            return result
        for manifest in sorted(path.glob('*/manifest.json')):
            try:
                if manifest.parent.is_symlink() or manifest.is_symlink() or manifest.stat().st_size > MAX_ENTRY_BYTES:
                    raise ValueError()
                record = json.loads(manifest.read_bytes())
                pid = problem_id(record['scope']['problemId'])
                if manifest.parent != self.scope_path(session, pid):
                    raise ValueError()
                entry = self.read_entry(session, pid)
                if entry['status'] == 'ready':
                    try:
                        with self.verified_object(session, pid, entry):
                            pass
                    except ResourceError:
                        entry = {'problemId': pid, 'status': 'unknown',
                                 'lastAttempt': {'status': 'unknown', 'code': 'CACHE_CORRUPT', 'at': None}}
                result['problems'].append(entry)
            except (ResourceError, ValueError, KeyError, TypeError, OSError):
                result.setdefault('warnings', []).append({'code': 'CACHE_CORRUPT'})
            if len(encoded(result)) > MAX_MANIFEST_RESULT_BYTES:
                raise ResourceError('RESOURCE_MANIFEST_TOO_LARGE', 'The cached resource listing exceeds the native message limit')
        result['problems'].sort(key=lambda entry: int(entry['problemId']))
        return result

    def chunk(self, session, args):
        pid = problem_id(args.get('problemId'))
        rid = args.get('resourceId')
        offset, count = args.get('offset'), args.get('maxBytes', MAX_CHUNK_BYTES)
        if (not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{64}', rid)
                or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
                or isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= MAX_CHUNK_BYTES):
            raise ResourceError('VALIDATION_ERROR', 'Invalid resource identity or chunk range')
        entry = self.read_entry(session, pid)
        if not entry or entry['status'] != 'ready' or entry.get('resourceId') != rid:
            raise ResourceError('RESOURCE_NOT_FOUND', 'This resource is not prepared for the session account and contest')
        if offset > entry['totalBytes']:
            raise ResourceError('VALIDATION_ERROR', 'Chunk offset is outside the resource')
        with self.verified_object(session, pid, entry) as stream:
            stream.seek(offset)
            data = stream.read(count)
        return {'problemId': pid, 'resourceId': rid, 'offset': offset,
                'bytesBase64': base64.b64encode(data).decode('ascii'), 'nextOffset': offset + len(data),
                'eof': offset + len(data) == entry['totalBytes'], 'totalBytes': entry['totalBytes'],
                'sha256': entry['sha256'], 'chunkSha256': hashlib.sha256(data).hexdigest()}
