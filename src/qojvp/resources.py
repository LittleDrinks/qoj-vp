"""Account-scoped resource objects and atomic manifests; no HTTP or timers."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

from .transport import BASE

MAX_RESOURCE_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024
MAX_ENTRY_BYTES = 256 * 1024
MAX_MANIFEST_RESULT_BYTES = 900 * 1024
MAX_ARCHIVE_FILES = 2000
MAX_EXPANDED_BYTES = 2 * MAX_RESOURCE_BYTES
MAX_MANUAL_BYTES = 8 * 1024 * 1024
MAX_MANUAL_FILE_BYTES = 4 * 1024 * 1024
MAX_MANUAL_FILES = 1000


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


def manual_sample_files(args, label):
    """Validate an import without extracting paths or interpreting its bytes."""
    if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', label):
        raise ResourceError('VALIDATION_ERROR', 'The cached problem label is invalid')
    if ('files' in args) == ('zipBase64' in args):
        raise ResourceError('VALIDATION_ERROR', 'Provide either a ZIP or individual sample files')

    def decode(value, limit):
        if not isinstance(value, str) or len(value) > 4 * ((limit + 2) // 3):
            raise ResourceError('SAMPLES_TOO_LARGE', 'The imported samples exceed their size limit')
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ResourceError('VALIDATION_ERROR', 'A sample file has invalid base64 encoding') from exc
        if len(data) > limit:
            raise ResourceError('SAMPLES_TOO_LARGE', 'The imported samples exceed their size limit')
        return data

    seen, raw_files = set(), {}

    def valid_name(name, *, directory=False):
        if (not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name or ':' in name
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or PurePosixPath(name).is_absolute()
                or any(part in {'', '.', '..'} for part in (name[:-1] if directory else name).split('/'))
                or name in seen):
            raise ResourceError('INVALID_SAMPLES', 'The import contains unsafe or duplicate file paths')
        seen.add(name)

    if 'files' in args:
        records = args['files']
        if not isinstance(records, list) or not 0 < len(records) <= MAX_MANUAL_FILES:
            raise ResourceError('INVALID_SAMPLES', 'Import between 1 and 1000 sample files')
        for record in records:
            if not isinstance(record, dict) or set(record) != {'name', 'base64'}:
                raise ResourceError('VALIDATION_ERROR', 'Each sample file requires name and base64')
            valid_name(record['name'])
            raw_files[record['name']] = decode(record['base64'], MAX_MANUAL_FILE_BYTES)
            if sum(map(len, raw_files.values())) > MAX_MANUAL_BYTES:
                raise ResourceError('SAMPLES_TOO_LARGE', 'Imported samples exceed 8 MiB in total')
    else:
        payload = decode(args['zipBase64'], MAX_MANUAL_BYTES)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = archive.infolist()
                if not 0 < len(members) <= MAX_MANUAL_FILES or sum(item.file_size for item in members) > MAX_MANUAL_BYTES:
                    raise ResourceError('SAMPLES_TOO_LARGE', 'The ZIP exceeds the file count or 8 MiB extraction limit')
                for member in members:
                    valid_name(member.filename, directory=member.is_dir())
                    mode = member.external_attr >> 16
                    if (member.filename != member.orig_filename or stat.S_ISLNK(mode) or member.flag_bits & 1
                            or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                            or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                        raise ResourceError('INVALID_SAMPLES', 'The ZIP contains an unsupported or unsafe member')
                    if member.is_dir():
                        continue
                    if member.file_size > MAX_MANUAL_FILE_BYTES:
                        raise ResourceError('SAMPLES_TOO_LARGE', 'A sample file exceeds 4 MiB')
                    with archive.open(member) as stream:
                        data = stream.read(MAX_MANUAL_FILE_BYTES + 1)
                    if len(data) != member.file_size or len(data) > MAX_MANUAL_FILE_BYTES:
                        raise ResourceError('SAMPLES_TOO_LARGE', 'A sample file exceeds its declared limit')
                    raw_files[member.filename] = data
        except (ValueError, OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
            raise ResourceError('INVALID_SAMPLES', 'The imported ZIP could not be verified') from exc
    pairs = {}
    for name, data in raw_files.items():
        match = re.fullmatch(r'(.+)\.(in|ans|out)', name, flags=re.IGNORECASE)
        if not match:
            raise ResourceError('INVALID_SAMPLES', 'Sample imports may only contain .in and .ans or .out files')
        stem, kind = match[1], 'in' if match[2].lower() == 'in' else 'ans'
        pair = pairs.setdefault(stem, {})
        if kind in pair:
            raise ResourceError('INVALID_SAMPLES', 'A sample has more than one input or expected output')
        pair[kind] = data
    if not pairs or any(set(pair) != {'in', 'ans'} for pair in pairs.values()):
        raise ResourceError('INVALID_SAMPLES', 'Every sample needs one .in and one matching .ans or .out file')
    order = lambda name: [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r'(\d+)', name)]
    return {f'samples-{label}/{index}.{kind}': pairs[stem][kind]
            for index, stem in enumerate(sorted(pairs, key=order), 1) for kind in ('in', 'ans')}


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
        payload = self.entry_payload(session, pid, entry)
        self.atomic_write(self.scope_path(session, pid) / 'manifest.json', payload)

    def entry_payload(self, session, pid, entry):
        payload = encoded({'schema': 1, 'scope': self.scope(session, pid), 'entry': entry})
        if len(payload) > MAX_ENTRY_BYTES:
            raise ResourceError('RESOURCE_METADATA_TOO_LARGE', 'Resource file metadata exceeds the manifest limit')
        return payload

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

    @staticmethod
    def archive_files(stream, entry):
        try:
            metadata = entry['files']
            if not isinstance(metadata, list) or not 0 < len(metadata) <= MAX_ARCHIVE_FILES:
                raise ValueError()
            expected = {item['name']: item for item in metadata}
            if len(expected) != len(metadata):
                raise ValueError()
            files = {}
            with zipfile.ZipFile(stream) as archive:
                members = archive.infolist()
                if len(members) > MAX_ARCHIVE_FILES or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
                    raise ValueError()
                for member in members:
                    name = member.filename
                    path = PurePosixPath(name)
                    if (name != member.orig_filename or '\\' in name or ':' in name or path.is_absolute()
                            or any(part in {'', '.', '..'} for part in name.rstrip('/').split('/'))
                            or any(ord(character) < 32 or ord(character) == 127 for character in name)
                            or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1):
                        raise ValueError()
                    if member.is_dir():
                        continue
                    if name in files or name not in expected:
                        raise ValueError()
                    record = expected[name]
                    if isinstance(record['bytes'], bool) or not isinstance(record['bytes'], int) or record['bytes'] != member.file_size:
                        raise ValueError()
                    contents = archive.read(member)
                    if hashlib.sha256(contents).hexdigest() != record['sha256']:
                        raise ValueError()
                    files[name] = contents
            if set(files) != set(expected):
                raise ValueError()
            return files
        except (KeyError, TypeError, ValueError, OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
            raise ResourceError('CACHE_CORRUPT', 'The cached archive paths, members or file hashes could not be verified') from exc

    @staticmethod
    def download_parts(entry, files):
        label = entry.get('problemLabel')
        if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', label):
            raise ResourceError('CACHE_CORRUPT', 'The resource problem label is invalid')
        sample_prefix, attachment_prefix = f'samples-{label}/', f'attachment-extras/problem-{label}/'
        if any(not name.startswith((sample_prefix, attachment_prefix)) for name in files):
            raise ResourceError('CACHE_CORRUPT', 'The resource files do not match their problem label')
        inputs = {name[:-3] for name in files if name.startswith(sample_prefix) and name.endswith('.in')}
        answers = {name[:-4] for name in files if name.startswith(sample_prefix) and name.endswith('.ans')}
        paired = inputs & answers
        sample_names = {stem + suffix for stem in paired for suffix in ('.in', '.ans')}
        samples = {name: value for name, value in files.items() if name in sample_names}
        attachments = {name: value for name, value in files.items() if name not in sample_names}
        return [(kind, part) for kind, part in [('samples', samples), ('attachment', attachments)] if part]

    @staticmethod
    def archive_bytes(files):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, contents in sorted(files.items()):
                member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                member.external_attr = 0o100600 << 16
                archive.writestr(member, contents, compress_type=zipfile.ZIP_DEFLATED)
        payload = output.getvalue()
        if not payload or len(payload) > MAX_RESOURCE_BYTES:
            raise ResourceError('ARTIFACT_TOO_LARGE', 'The resource archive exceeds the 64 MiB cache limit')
        return payload

    def build_downloads(self, entry, files):
        parts = self.download_parts(entry, files)
        downloads, objects = [], {}
        for kind, contents in parts:
            if len(parts) == 1:
                digest, total = entry['resourceId'], entry['totalBytes']
            else:
                payload = self.archive_bytes(contents)
                digest, total = hashlib.sha256(payload).hexdigest(), len(payload)
                objects[digest] = payload
            pairs = len(contents) // 2 if kind == 'samples' else 0
            downloads.append({key: entry.get(key) for key in ('problemId', 'problemLabel', 'sampleSource', 'preparedAt', 'interactiveHint')} |
                {'status': 'ready', 'kind': kind, 'filename': f"{'samples' if kind == 'samples' else 'attachments'}-{entry['problemLabel']}.zip",
                 'resourceId': digest, 'sha256': digest, 'totalBytes': total, 'sampleCount': pairs, 'pairCount': pairs,
                 'files': [{'name': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                           for name, value in contents.items()], 'extraFiles': list(contents) if kind == 'attachment' else []})
        return {**entry, 'downloads': downloads}, objects

    def bound_downloads(self, session, pid, entry):
        downloads = entry.get('downloads')
        if not isinstance(downloads, list) or not 0 < len(downloads) <= 2:
            raise ResourceError('CACHE_CORRUPT', 'The resource download list is invalid')
        kinds = []
        for descriptor in downloads:
            if (not isinstance(descriptor, dict) or descriptor.get('status') != 'ready'
                    or descriptor.get('problemId') != entry['problemId']
                    or descriptor.get('problemLabel') != entry.get('problemLabel')
                    or descriptor.get('kind') not in {'samples', 'attachment'} or descriptor['kind'] in kinds):
                raise ResourceError('CACHE_CORRUPT', 'The resource download is not bound to this problem')
            kinds.append(descriptor['kind'])
            expected_filename = f"{'samples' if descriptor['kind'] == 'samples' else 'attachments'}-{entry['problemLabel']}.zip"
            if descriptor.get('filename') != expected_filename:
                raise ResourceError('CACHE_CORRUPT', 'The resource download filename is invalid')
            self.object_path(session, pid, descriptor)
        return downloads

    def ensure_downloads(self, session, pid, entry):
        with self.verified_object(session, pid, entry) as stream:
            files = self.archive_files(stream, entry)
        if 'downloads' not in entry:
            entry, objects = self.build_downloads(entry, files)
            manifest = self.entry_payload(session, pid, entry)
            for descriptor in entry['downloads']:
                if descriptor['resourceId'] in objects:
                    self.atomic_write(self.object_path(session, pid, descriptor), objects[descriptor['resourceId']])
            self.atomic_write(self.scope_path(session, pid) / 'manifest.json', manifest)
            return entry
        parts = dict(self.download_parts(entry, files))
        descriptors = self.bound_downloads(session, pid, entry)
        if {descriptor['kind'] for descriptor in descriptors} != set(parts):
            raise ResourceError('CACHE_CORRUPT', 'The resource download kinds do not match the cached files')
        for descriptor in descriptors:
            with self.verified_object(session, pid, descriptor) as stream:
                if self.archive_files(stream, descriptor) != parts[descriptor['kind']]:
                    raise ResourceError('CACHE_CORRUPT', 'The resource download contents do not match the cached files')
        return entry

    def manual_entry(self, session, pid):
        if not session.get('account'):
            return None
        entry = self.read_entry(session, pid)
        if not entry or entry.get('status') != 'ready' or entry.get('manualSamples') is not True:
            return None
        with self.locked(self.scope_path(session, pid)):
            entry = self.read_entry(session, pid)
            return self.ensure_downloads(session, pid, entry) if entry and entry.get('manualSamples') is True else None

    def import_samples(self, session, pid, label, args, at):
        if 'confirmedReplace' in args and not isinstance(args['confirmedReplace'], bool):
            raise ResourceError('VALIDATION_ERROR', 'confirmedReplace must be a boolean')
        samples = manual_sample_files(args, label)
        with self.locked(self.scope_path(session, pid)):
            old = self.read_entry(session, pid)
            attachments, attachment = {}, None
            if old and old['status'] == 'ready':
                old = self.ensure_downloads(session, pid, old)
                if old.get('problemLabel') != label:
                    raise ResourceError('CACHE_CORRUPT', 'The cached resource label no longer matches this contest')
                if any(item['kind'] == 'samples' for item in old['downloads']) and args.get('confirmedReplace') is not True:
                    raise ResourceError('CONFIRMATION_REQUIRED', 'Confirm replacement of the already prepared samples')
                attachment = next((item for item in old['downloads'] if item['kind'] == 'attachment'), None)
                if attachment:
                    with self.verified_object(session, pid, attachment) as stream:
                        attachments = self.archive_files(stream, attachment)
            if set(samples) & set(attachments):
                # A legacy incomplete sample may belong to the attachment
                # download. Keep it byte-for-byte and number imported pairs
                # around its names instead of overwriting or dropping it.
                renamed, index = {}, 1
                for source_index in range(1, len(samples) // 2 + 1):
                    while any(f'samples-{label}/{index}.{kind}' in attachments for kind in ('in', 'ans')):
                        index += 1
                    for kind in ('in', 'ans'):
                        renamed[f'samples-{label}/{index}.{kind}'] = samples[f'samples-{label}/{source_index}.{kind}']
                    index += 1
                samples = renamed
            files = {**samples, **attachments}
            payload = self.archive_bytes(files)
            digest = hashlib.sha256(payload).hexdigest()
            metadata = {'problemId': pid, 'problemLabel': label, 'status': 'ready', 'manualSamples': True,
                        'sampleSource': 'manual', 'interactiveHint': False, 'warnings': [],
                        'kind': 'attachment' if attachments else 'samples',
                        'filename': f"{'attachments' if attachments else 'samples'}-{label}.zip",
                        'sampleCount': len(samples) // 2, 'pairCount': len(samples) // 2,
                        'files': [{'name': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                                  for name, value in files.items()],
                        'extraFiles': list(attachments), 'resourceId': digest, 'sha256': digest,
                        'totalBytes': len(payload), 'preparedAt': at, 'lastAttempt': {'status': 'ready', 'at': at}}
            self.archive_files(io.BytesIO(payload), metadata)
            entry, objects = self.build_downloads(metadata, files)
            if attachment:
                # Keep the old attachment object and its source metadata. The
                # user's sample replacement must not rewrite tool resources.
                entry['downloads'] = [item if item['kind'] == 'samples' else attachment for item in entry['downloads']]
            manifest = self.entry_payload(session, pid, entry)
            self.atomic_write(self.object_path(session, pid, entry), payload)
            for item in entry['downloads']:
                if item['resourceId'] in objects:
                    self.atomic_write(self.object_path(session, pid, item), objects[item['resourceId']])
            self.atomic_write(self.scope_path(session, pid) / 'manifest.json', manifest)
            return entry

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
                    old = self.ensure_downloads(session, pid, old)
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
        files = self.archive_files(io.BytesIO(payload), entry)
        entry, objects = self.build_downloads(entry, files)
        manifest = self.entry_payload(session, pid, entry)
        path = self.scope_path(session, pid)
        with self.locked(path):
            previous = self.read_entry(session, pid)
            if previous and previous.get('status') == 'ready' and previous.get('manualSamples') is True:
                return self.ensure_downloads(session, pid, previous)
            self.atomic_write(self.object_path(session, pid, entry), payload)
            for descriptor in entry['downloads']:
                if descriptor['resourceId'] in objects:
                    self.atomic_write(self.object_path(session, pid, descriptor), objects[descriptor['resourceId']])
            self.atomic_write(path / 'manifest.json', manifest)
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
                with self.locked(self.scope_path(session, pid)):
                    entry = self.read_entry(session, pid)
                    if entry['status'] == 'ready':
                        try:
                            entry = self.ensure_downloads(session, pid, entry)
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
        with self.locked(self.scope_path(session, pid)):
            entry = self.read_entry(session, pid)
            if not entry or entry['status'] != 'ready':
                raise ResourceError('RESOURCE_NOT_FOUND', 'This resource is not prepared for the session account and contest')
            if 'downloads' not in entry:
                entry = self.ensure_downloads(session, pid, entry)
            downloads = self.bound_downloads(session, pid, entry)
            entry = next((candidate for candidate in [entry, *downloads] if candidate.get('resourceId') == rid), None)
            if entry is None:
                raise ResourceError('RESOURCE_NOT_FOUND', 'This resource is not prepared for the session account and contest')
        if offset > entry['totalBytes']:
            raise ResourceError('VALIDATION_ERROR', 'Chunk offset is outside the resource')
        with self.verified_object(session, pid, entry) as stream:
            # Member validation happens when storing, listing or migrating the
            # manifest. The bound object's size and digest verify the same ZIP
            # bytes here without decompressing every member for every chunk.
            stream.seek(offset)
            data = stream.read(count)
        return {'problemId': pid, 'resourceId': rid, 'offset': offset,
                'bytesBase64': base64.b64encode(data).decode('ascii'), 'nextOffset': offset + len(data),
                'eof': offset + len(data) == entry['totalBytes'], 'totalBytes': entry['totalBytes'],
                'sha256': entry['sha256'], 'chunkSha256': hashlib.sha256(data).hexdigest()}
