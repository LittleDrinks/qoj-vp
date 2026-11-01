"""One durable application interface behind the Firefox and native entrypoints."""
from __future__ import annotations

import base64
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import uuid

from bs4 import BeautifulSoup

from . import __version__
from .account import current_account
from .history import detail_verdict, parse_history, submission_time_metadata
from .inline_samples import statement_language_paths, statement_page_path, statement_sample_files
from .ledger import Ledger, session_duration
from .resources import ResourceCache, ResourceError, problem_id
from .transport import BASE, BrowserSession, MAX_SOURCE_BYTES

MAX_ZIP_BYTES = 512 * 1024


class ApplicationError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def now_ms():
    return int(time.time() * 1000)


def timestamp_ms(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError('A timestamp requires an explicit timezone')
        value = value.timestamp() * 1000
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected a nonnegative epoch-millisecond timestamp')
    return int(value)


def rankland_url(raw, session_id, start_at):
    if not raw:
        return None
    parsed = urlparse(str(raw).strip())
    if (parsed.scheme != 'https' or parsed.netloc != 'vp.xcpc.link' or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.fragment):
        raise ValueError('Use a https://vp.xcpc.link/ contest URL')
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not query.get('contest'):
        raise ValueError('The RankLand URL must select a contest')
    query.update(run=session_id, **{'from': '0', 'play': '1', 'speed': '1'})
    if start_at is None:
        query.pop('at', None)
    else:
        query['at'] = datetime.fromtimestamp(start_at / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    return urlunparse(('https', 'vp.xcpc.link', '/', '', urlencode(query), ''))


def load_upstream(path):
    root = Path(path).expanduser().resolve()
    if not (root / 'qoj_submitter/client.py').is_file():
        raise ApplicationError('QOJ_LIBRARY_MISSING', 'The pinned qoj-submitter library is not installed')
    sys.path.insert(0, str(root))
    modules = [importlib.import_module('qoj_submitter.' + name) for name in ('client', 'samples', 'cli')]
    if any(not Path(module.__file__).resolve().is_relative_to(root) for module in modules):
        raise ApplicationError('QOJ_LIBRARY_CONFLICT', 'An unexpected qoj-submitter installation was imported')
    return modules


class Application:
    def __init__(self, state_dir=None, qoj_path=None, *, fixture_origin=None, clock=now_ms):
        self.clock = clock
        default_state = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'qoj-vp'
        self.ledger = Ledger(state_dir or os.environ.get('QOJ_VP_STATE_DIR') or default_state)
        self.resources = ResourceCache(self.ledger.directory)
        self.qoj_path = Path(qoj_path or os.environ.get('QOJ_VP_QOJ_PATH') or Path(__file__).resolve().parents[1] / 'vendor/qoj-submitter')
        # Test routing is supplied by installation/environment, never by a UI
        # task that might silently turn a real submission into a fake receipt.
        self.fixture_origin = fixture_origin or os.environ.get('QOJ_VP_FIXTURE_ORIGIN')

    def close(self):
        self.ledger.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def view(self, session):
        result = dict(session)
        elapsed = max(0, self.clock() - session['startAt']) if session.get('startAt') is not None else 0
        result['elapsedMs'] = min(elapsed, session_duration(session))
        result['effectiveState'] = ('finished' if session['state'] == 'running' and elapsed >= session['durationMs'] else session['state'])
        return result

    def dispatch(self, method, args=None, exchange=None):
        args = args or {}
        if not isinstance(args, dict):
            raise ApplicationError('VALIDATION_ERROR', 'Task arguments must be an object')
        try:
            if method == 'hello':
                return {'version': __version__, 'capabilities': ['qoj', 'sessions', 'samples', 'resource-cache', 'submission-history', 'rankland-outbox'],
                        'helperPid': os.getpid(), 'stateDir': str(self.ledger.directory), 'fixture': bool(self.fixture_origin)}
            if method == 'create_session':
                return self.create_session(args)
            if method == 'list_sessions':
                return {'sessions': [self.view(s) for s in self.ledger.sessions()]}
            if method in {'inspect_session', 'start_session', 'archive_session', 'finish_session', 'delete_session',
                          'update_session', 'prepare_rankland'}:
                return self.session_action(method, args)
            if method == 'rankland_queue':
                return {'items': self.ledger.queue(args.get('sessionId'))}
            if method == 'rankland_ack':
                return self.ledger.ack(args.get('sessionId'), args)
            if method in {'resource_manifest', 'resource_chunk'}:
                session = self.ledger.session(args.get('sessionId'))
                return self.resources.manifest(session) if method == 'resource_manifest' else self.resources.chunk(session, args)
            if method == 'import_samples':
                return self.import_samples(args)
            if method == 'prepare_resource':
                session = self.ledger.session(args.get('sessionId'))
                manual = self.resources.manual_entry(session, problem_id(args.get('problemId')))
                if manual:
                    return manual
            if method == 'qoj_submissions' and args.get('refresh') is False:
                session = self.ledger.session(args.get('sessionId'))
                return {'submissions': self.ledger.submissions(session['sessionId']), 'account': session.get('account'),
                        'coverage': {'complete': False, 'pages': 0, 'warning': 'Cached history; refresh to query QOJ'}}
            if method not in {'qoj_contest', 'qoj_problem_form', 'qoj_samples', 'qoj_submit', 'qoj_submissions', 'qoj_reconcile', 'prepare_resource'}:
                raise ApplicationError('UNKNOWN_METHOD', 'Unknown application method')
            if not callable(exchange):
                raise ApplicationError('HTTP_BRIDGE_REQUIRED', 'This operation requires a Firefox QOJ tab')
            modules = load_upstream(self.qoj_path)
            transport = BrowserSession(exchange, allow_post=method == 'qoj_submit', fixture_origin=self.fixture_origin)
            client = modules[0].QojClient(BASE, session=transport)
            try:
                if method == 'qoj_contest':
                    account, _ = current_account(client)
                    contest = client.contest(modules[0].contest_id(str(args.get('contestId', ''))))
                    self.ledger.save_contest(account, contest)
                    return {**contest, 'account': account, 'problems': self.problem_list(contest),
                            'source': 'fixture' if self.fixture_origin else 'real-qoj-browser'}
                session = self.ledger.session(args.get('sessionId'))
                if method == 'qoj_submit':
                    return self.submit(session, args, client, modules)
                if method == 'prepare_resource':
                    return self.prepare_resource(session, args, client, modules, transport)
                self.authenticate(client, session)
                contest = client.contest(session['contestId'])
                self.ledger.save_contest(session.get('account'), contest)
                if method == 'qoj_problem_form':
                    problem = self.problem(contest, args)
                    form = client.form(contest['id'], problem['id'])
                    response = transport.last_response
                    return {'problemId': problem['id'], 'problemName': problem['name'],
                            'problemLabel': next(label for label, item in contest['problems'].items() if item['id'] == problem['id']),
                            'languages': form.languages, 'csrfPresent': bool(form.token),
                            'pdfCandidates': self.pdf_candidates(response.text, response.url),
                            'statementUrl': BASE + f"/contest/{contest['id']}/problem/{problem['id']}"}
                if method == 'qoj_samples':
                    problem = self.problem(contest, args)
                    metadata, data = self.extract_resource(contest, problem, client, modules, transport,
                                                           interactive_hint=args.get('interactiveHint', False))
                    if len(data) > MAX_ZIP_BYTES:
                        raise ApplicationError('ARTIFACT_TOO_LARGE', 'This attachment exceeds the current 512 KiB download limit; use QOJ directly')
                    return {'zipFilename': f"samples-{metadata['problemLabel']}.zip",
                            'zipBase64': base64.b64encode(data).decode('ascii'),
                            **{key: metadata[key] for key in ('files', 'warnings', 'extraFiles', 'sampleSource')}}
                refreshed = self.refresh(session, contest, client,
                                         preferred_sid=str(args.get('submissionId', '')) if method == 'qoj_reconcile' else None)
                if method == 'qoj_reconcile':
                    return self.reconcile(session, args, refreshed)
                return refreshed
            except modules[0].QojError as exc:
                raise self.upstream_error(exc) from exc
        except ResourceError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise ApplicationError('VALIDATION_ERROR', str(exc)) from exc
        except KeyError as exc:
            raise ApplicationError('NOT_FOUND', str(exc)) from exc

    @staticmethod
    def upstream_error(exc):
        message = str(exc)
        code = 'LOGIN_REQUIRED' if any(x in message.lower() for x in ('logged in', 'login', 'session expired')) else 'QOJ_ERROR'
        cause = exc
        while cause:
            if getattr(cause, 'bridge_code', None):
                code = cause.bridge_code
                break
            cause = cause.__cause__
        return ApplicationError(code, message)

    @staticmethod
    def statement_resource_files(contest, problem, client):
        response = client.get(f"/contest/{contest['id']}/problem/{problem['id']}")

        def extract(page):
            if urlparse(page.url).path.startswith('/login'):
                raise ApplicationError('LOGIN_REQUIRED', 'The QOJ session expired while reading statement samples')
            if statement_page_path(page.url, contest['id'], problem['id']) is None:
                raise ApplicationError('SAMPLES_UNAVAILABLE', 'The statement response does not belong to the requested problem')
            return statement_sample_files(page.text) if page.status_code == 200 else {}

        files = extract(response)
        if files:
            return files
        paths = statement_language_paths(response.text, response.url, contest['id'], problem['id'])
        visited = {urlparse(response.url).path}
        for path in paths:
            if path in visited:
                continue
            visited.add(path)
            response = client.get(path, allow_404=True)
            files = extract(response)
            visited.add(urlparse(response.url).path)
            if files:
                return files
        return {}

    @staticmethod
    def extract_resource(contest, problem, client, modules, transport, *, interactive_hint=False):
        if not isinstance(interactive_hint, bool):
            raise ValueError('interactiveHint must be a boolean')
        label = next(label for label, item in contest['problems'].items() if item['id'] == problem['id'])
        with contextlib.redirect_stdout(sys.stderr):
            samples, extras, warnings = modules[1].download(client, {**contest, 'problems': {label: problem}})
        sample_source = 'attachment'
        attachment_response = transport.last_response
        if attachment_response is not None and attachment_response.status_code != 404:
            body = attachment_response.content
            content_type = attachment_response.headers.get('Content-Type', '').lower()
            if (not body or 'text/html' in content_type
                    or body.lstrip().lower().startswith((b'<!doctype html', b'<html', b'<body', b'<form', b'<script'))):
                raise ApplicationError('SAMPLES_UNAVAILABLE', 'The attachment response is empty or is not a verified resource')
        if (not interactive_hint and not samples and not extras and attachment_response is not None
                and attachment_response.status_code == 404):
            raw_files = Application.statement_resource_files(contest, problem, client)
            if raw_files:
                organized, special, count, pairs = modules[1].organize(raw_files)
                if not special and count > 0 and count == pairs:
                    samples = {f'samples-{label}/{name}': content for name, content in organized.items()}
                    sample_source = 'inline-statement'
                    warnings.append(f'{label}: using verified labelled statement samples; attachment availability remains unconfirmed')
        files = {**samples, **extras}
        if not files:
            raise ApplicationError('SAMPLES_UNAVAILABLE', 'No resource could be verified from this response; absence is not confirmed')
        inputs = {name[:-3] for name in samples if name.endswith('.in')}
        answers = {name[:-4] for name in samples if name.endswith('.ans')}
        kind = 'samples' if inputs and inputs == answers and not extras else 'attachment'
        metadata = {'problemLabel': label, 'kind': kind,
                    'filename': f"{'samples' if kind == 'samples' else 'attachments'}-{label}.zip",
                    'sampleCount': len(inputs), 'pairCount': len(inputs & answers),
                    'files': [{'name': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                              for name, value in files.items()],
                    'extraFiles': list(extras), 'sampleSource': sample_source, 'warnings': warnings,
                    'interactiveHint': interactive_hint}
        return metadata, modules[1].zip_bytes(files)

    def prepare_resource(self, session, args, client, modules, transport):
        pid = problem_id(args.get('problemId'))
        hint = args.get('interactiveHint', False)
        if not isinstance(hint, bool):
            raise ValueError('interactiveHint must be a boolean')
        label = None
        try:
            self.authenticate(client, session)
            contest = client.contest(session['contestId'])
            self.ledger.save_contest(session.get('account'), contest)
            problem = self.problem(contest, {'problemId': pid})
            label = next(key for key, item in contest['problems'].items() if str(item['id']) == pid)
            metadata, payload = self.extract_resource(contest, problem, client, modules, transport, interactive_hint=hint)
            return self.resources.store(session, pid, metadata, payload, self.clock())
        except (ApplicationError, modules[0].QojError, ResourceError) as exc:
            code = self.upstream_error(exc).code if isinstance(exc, modules[0].QojError) else exc.code
            return self.resources.unknown(session, pid, code, self.clock(), label=label, interactive_hint=hint)

    def create_session(self, args):
        cid = str(args.get('contestId', '')).strip()
        if not re.fullmatch(r'\d+', cid):
            raise ValueError('Expected a numeric QOJ contest ID')
        sid = str(uuid.uuid4())
        start = timestamp_ms(args['startAt']) if args.get('startAt') is not None else None
        duration = args.get('durationMs', 5 * 60 * 60 * 1000)
        if isinstance(duration, bool) or not isinstance(duration, int) or not 0 < duration <= 14 * 24 * 60 * 60 * 1000:
            raise ValueError('Invalid contest duration')
        account = args.get('account') or None
        if account is not None and (not isinstance(account, str) or len(account) > 100 or any(ord(c) < 32 for c in account)):
            raise ValueError('Invalid account name')
        record = {'sessionId': sid, 'contestId': cid, 'title': str(args.get('title') or f'QOJ Contest {cid}')[:200],
                  'account': account, 'startAt': start, 'durationMs': duration,
                  'state': 'running' if start is not None else 'prepared', 'createdAt': self.clock(),
                  'ranklandUrl': rankland_url(args.get('ranklandUrl'), sid, start),
                  'ranklandPrepared': False, 'ranklandPreparedAt': None}
        self.ledger.create_session(record)
        return self.view(record)

    def import_samples(self, args):
        session = self.ledger.session(args.get('sessionId'))
        pid = problem_id(args.get('problemId'))
        if not session.get('account'):
            raise ApplicationError('ACCOUNT_UNKNOWN', 'Read this contest with the QOJ account before importing samples')
        contest = self.ledger.contest(session['account'], session['contestId'])
        if contest is not None:
            self.problem(contest, {'problemId': pid})
            label = next(label for label, problem in contest['problems'].items() if str(problem['id']) == pid)
        else:
            # Older installations can already have a scoped entry recorded
            # after QOJ verified the contest/problem relationship.
            entry = self.resources.read_entry(session, pid)
            label = entry.get('problemLabel') if entry else None
            if not label:
                raise ApplicationError('CONTEST_NOT_CACHED', 'Read this contest from QOJ before importing samples')
        return self.resources.import_samples(session, pid, label, args, self.clock())

    def session_action(self, method, args):
        sid = args.get('sessionId')
        target_changed = False
        with self.ledger.transaction():
            record = self.ledger.session(sid)
            if method == 'start_session':
                if record['state'] in {'archived', 'finished'} or self.view(record)['effectiveState'] == 'finished':
                    raise ValueError('A finished or archived session cannot be started')
                if record['startAt'] is None:
                    record['startAt'], record['state'] = self.clock(), 'running'
                    record['ranklandUrl'] = rankland_url(record.get('ranklandUrl'), sid, record['startAt'])
                    record['ranklandPrepared'], record['ranklandPreparedAt'] = False, None
            elif method == 'prepare_rankland':
                if record.get('startAt') is None or self.clock() < record['startAt']:
                    raise ApplicationError('SESSION_NOT_RUNNING', 'Start the VP session before opening its RankLand replay')
                if not record.get('ranklandUrl'):
                    raise ApplicationError('RANKLAND_NOT_CONFIGURED', 'Choose a RankLand contest URL first')
                if not record.get('ranklandPrepared'):
                    parsed = urlparse(record['ranklandUrl'])
                    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                    elapsed = self.view(record)['elapsedMs']
                    # The original replay rejects from >= its duration. For
                    # a first opening after this local session has ended,
                    # enter its final second; keep the local finished clock
                    # and every previously frozen URL unchanged. Contest
                    # durations still need to match the selected RankLand.
                    if elapsed >= record['durationMs']:
                        elapsed = max(0, record['durationMs'] - 1000)
                    # RankLand's play=1 path starts at `from` even when `at`
                    # is in the past. Freeze this offset once: changing it on
                    # reopening would select a different localStorage slot.
                    query['from'] = format(elapsed / 60000, '.12g')
                    record['ranklandUrl'] = urlunparse(parsed._replace(query=urlencode(query)))
                    record['ranklandPrepared'], record['ranklandPreparedAt'] = True, self.clock()
            elif method == 'archive_session':
                record['state'] = 'archived'
            elif method == 'finish_session':
                if record['state'] == 'prepared' or record['state'] == 'archived' or record.get('startAt') is None:
                    raise ApplicationError('SESSION_NOT_RUNNING', 'Only a started local session can be finished')
                if self.clock() < record['startAt']:
                    raise ApplicationError('SESSION_NOT_RUNNING', 'This local session has not started yet')
                if record['state'] != 'finished':
                    record['finishedAt'] = min(self.clock(), record['startAt'] + record['durationMs'])
                    record['state'] = 'finished'
            elif method == 'delete_session':
                if args.get('confirmed') is not True:
                    raise ApplicationError('CONFIRMATION_REQUIRED', 'Confirm deletion of this local session')
                if self.view(record)['effectiveState'] not in {'prepared', 'archived', 'finished'}:
                    raise ApplicationError('SESSION_RUNNING', 'Finish this local session before deleting it')
                if self.ledger.has_unresolved_operations(sid):
                    raise ApplicationError('UNRESOLVED_SUBMISSION', 'Reconcile unconfirmed source submissions before deleting this session')
                self.ledger.delete_session(sid)
                return {'deleted': True, 'sessionId': sid}
            elif method == 'update_session':
                if set(args) - {'sessionId', 'ranklandUrl', 'title', 'durationMs'}:
                    raise ValueError('Only session title, duration and RankLand URL may be changed')
                if ('title' in args or 'durationMs' in args) and record['state'] != 'prepared':
                    raise ApplicationError('SESSION_NOT_PREPARED', 'Title and duration can only be edited before starting')
                if 'title' in args:
                    if not isinstance(args['title'], str) or not args['title'].strip() or len(args['title']) > 200 or any(ord(c) < 32 for c in args['title']):
                        raise ValueError('Use a nonempty title of at most 200 characters')
                    record['title'] = args['title'].strip()
                if 'durationMs' in args:
                    duration = args['durationMs']
                    if isinstance(duration, bool) or not isinstance(duration, int) or not 0 < duration <= 14 * 24 * 60 * 60 * 1000:
                        raise ValueError('Invalid contest duration')
                    record['durationMs'] = duration
                if 'ranklandUrl' in args:
                    target = rankland_url(args['ranklandUrl'], sid, record['startAt'])
                    original = rankland_url(record.get('ranklandUrl'), sid, record['startAt'])
                    # Compare canonical target configuration while ignoring
                    # managed run/time parameters; preserve the frozen URL.
                    target_changed = (target is None) != (original is None)
                    if target is not None and original is not None:
                        target_changed = dict(parse_qsl(urlparse(target).query, keep_blank_values=True)) != dict(
                            parse_qsl(urlparse(original).query, keep_blank_values=True))
                    if target_changed:
                        record['ranklandUrl'] = target
                        record['ranklandPrepared'], record['ranklandPreparedAt'] = False, None
            self.ledger.save_session(record)
        if target_changed:
            self.ledger.requeue_session(sid)
        return self.view(record)

    @staticmethod
    def problem_list(contest):
        return [{'label': label, **item, 'url': BASE + f"/contest/{contest['id']}/problem/{item['id']}"}
                for label, item in contest['problems'].items()]

    @staticmethod
    def problem(contest, args):
        label = str(args.get('problemLabel', '')).upper()
        pid = str(args.get('problemId', ''))
        candidates = [p for key, p in contest['problems'].items() if (not label or key == label) and (not pid or str(p['id']) == pid)]
        if len(candidates) != 1 or not (label or pid):
            raise ValueError('The selected problem does not belong to this contest')
        return candidates[0]

    def authenticate(self, client, session):
        account, logged_in = current_account(client)
        if not account:
            if logged_in:
                raise ApplicationError('ACCOUNT_UNKNOWN', 'QOJ did not expose an unambiguous account in its navigation menu')
            raise ApplicationError('LOGIN_REQUIRED', 'Log in to QOJ in Firefox before continuing')
        if session.get('account') and session['account'].casefold() != account.casefold():
            raise ApplicationError('ACCOUNT_MISMATCH', 'The Firefox account differs from this VP session account')
        session.update(self.ledger.bind_account(session['sessionId'], account))
        return account

    @staticmethod
    def pdf_candidates(html, page_url):
        page = BeautifulSoup(html, 'html.parser')
        result, seen = [], set()
        for node in page.select('a[href], iframe[src], object[data]'):
            raw = node.get('href') or node.get('src') or node.get('data')
            url = urljoin(page_url, raw)
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.netloc != 'qoj.ac' or parsed.username or parsed.password:
                continue
            if parsed.path.lower().endswith('.pdf') or (node.name in {'object', 'iframe'} and 'pdf' in node.get('type', '').lower()):
                if url not in seen:
                    seen.add(url)
                    result.append({'url': url, 'text': node.get_text(' ', strip=True)[:200] or 'PDF statement'})
        return result

    def submit(self, session, args, client, modules):
        filename = str(args.get('filename', ''))
        operation_id = str(args.get('operationId', ''))
        if not operation_id or len(operation_id) > 120 or any(ord(c) < 33 for c in operation_id):
            raise ValueError('A stable operationId is required')
        if not filename or len(filename) > 255 or any(c in filename for c in '/\\') or any(ord(c) < 32 for c in filename):
            raise ValueError('Select a single source filename')
        try:
            contents = base64.b64decode(args.get('contentsBase64', ''), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid source-file encoding') from exc
        if not contents or len(contents) > MAX_SOURCE_BYTES:
            raise ValueError('Source file must contain between 1 byte and 512 KiB')
        language, pid, label = (str(args.get(key, '')) for key in ('language', 'problemId', 'problemLabel'))
        if not pid.isdigit() or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', label) or not language or len(language) > 100:
            raise ValueError('Choose an explicit contest problem and language')
        fingerprint = hashlib.sha256(json.dumps([session['contestId'], pid, language,
                                                hashlib.sha256(contents).hexdigest()], separators=(',', ':')).encode()).hexdigest()
        existing = self.ledger.operation(operation_id)
        if existing:
            if existing['sessionId'] != session['sessionId'] or existing['fingerprint'] != fingerprint:
                raise ValueError('operationId is already bound to different submission data')
            return self.operation_result(existing)
        if self.view(session)['effectiveState'] != 'running' or self.clock() < session['startAt']:
            raise ApplicationError('SESSION_NOT_RUNNING', 'Start a VP session before submitting')
        # Validate all read-only state before recording the send intent.
        self.authenticate(client, session)
        contest = client.contest(session['contestId'])
        self.ledger.save_contest(session.get('account'), contest)
        problem = self.problem(contest, args)
        form = client.form(contest['id'], problem['id'])
        if language not in form.languages:
            raise ValueError('The selected language is not available for this problem')
        at = self.clock()
        record = {'id': None, 'operationId': operation_id, 'sessionId': session['sessionId'],
                  'account': session['account'], 'problemId': problem['id'],
                  'problemLabel': next(k for k, p in contest['problems'].items() if p['id'] == problem['id']),
                  'language': language, 'filename': filename, 'submittedAt': at, 'timeSource': 'local-intent',
                  'verdict': 'UNKNOWN', 'rawVerdict': 'Submission receipt not yet confirmed', 'pending': False,
                  'url': None, 'sourceSha256': hashlib.sha256(contents).hexdigest()}
        record, acquired = self.ledger.begin_operation(record, fingerprint)
        if not acquired:
            return self.operation_result(record)
        self.ledger.save_operation(record, 'submitting')
        try:
            url = client.submit(form, filename, contents, language, contest['id'])
        except modules[0].UnknownSubmission:
            record.update(state='unknown', rawVerdict='Receipt unknown; check QOJ before retrying')
            self.ledger.save_operation(record, 'unknown')
            return self.operation_result(record)
        except modules[0].QojError as exc:
            record.update(state='rejected', rawVerdict='QOJ rejected the submission')
            self.ledger.save_operation(record, 'rejected')
            return {**self.operation_result(record), 'error': {'code': 'SUBMISSION_REJECTED', 'message': str(exc)}}
        sid = urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]
        record.update(id=sid, url=url, state='confirmed', verdict='JUDGING', rawVerdict='Waiting for judge', pending=True)
        submission = {k: v for k, v in record.items() if k not in {'sourceSha256', 'fingerprint', 'sessionId'}}
        with self.ledger.transaction():
            self.ledger.save_operation(record, 'confirmed')
            saved = self.ledger.save_submission(session['sessionId'], submission)
        return {'submission': saved, 'state': 'confirmed'}

    def operation_result(self, operation):
        if operation.get('id'):
            fact = self.ledger.provider_submission(operation['account'], operation['id'])
            if fact:
                return {'submission': self.ledger.submission_view(operation['sessionId'], {**fact, 'operationId': operation['operationId']}),
                        'state': 'confirmed'}
        view = self.ledger.submission_view(operation['sessionId'], self.ledger.operation_view(operation))
        return {'submission': view, 'state': view['state']}

    def refresh(self, session, contest, client, *, preferred_sid=None):
        warnings, pages, seen = [], 0, set()
        complete = False
        deadline = time.monotonic() + 35
        time_candidates, time_attempts, known_time_ids = {}, {}, set()
        backfill_times = session.get('startAt') is not None and session.get('state') == 'running'
        linked_ids = {str(item['id']) for item in self.ledger.submissions(session['sessionId'])
                      if item.get('id') and item.get('operationId')}
        for page in range(1, 11):
            if time.monotonic() >= deadline:
                warnings.append('History refresh reached its time budget; refresh again to continue')
                break
            query = urlencode({'submitter': session['account'], 'page': page, 'locale': 'en'})
            try:
                response = client.get(f"/contest/{contest['id']}/submissions?{query}")
                if urlparse(response.url).path.startswith('/login'):
                    raise ApplicationError('LOGIN_REQUIRED', 'The QOJ session expired')
                parsed = parse_history(response.text, contest['id'], session['account'], contest['problems'])
            except ApplicationError:
                raise
            except Exception as exc:
                warnings.append('A history page could not be verified: ' + type(exc).__name__)
                break
            pages += 1
            warnings.extend(parsed['warnings'])
            if parsed['malformedRows']:
                warnings.append('Some submission rows could not be verified')
            page_new = 0
            for item in parsed['submissions']:
                if item['id'] in seen:
                    continue
                page_new += 1
                seen.add(item['id'])
                previous = self.ledger.provider_submission(session['account'], item['id']) or {}
                if item.get('submittedAt') is None and previous.get('submittedAt') is not None:
                    item.update(submittedAt=previous['submittedAt'], timeSource=previous['timeSource'])
                if item.get('submittedAt') is not None:
                    known_time_ids.add(item['id'])
                elif backfill_times:
                    retry_at = previous.get('timeProbeAfter')
                    if not isinstance(retry_at, (int, float)) or retry_at <= self.clock():
                        time_candidates[item['id']] = item
                        time_attempts[item['id']] = previous.get('timeProbeAttemptAt')
                start, at = session.get('startAt'), item.get('submittedAt')
                in_window = start is not None and at is not None and 0 <= at - start < session_duration(session)
                # Training mode can hide details. Refine a numeric partial
                # score, but do not erase an explicit current list verdict.
                if (item['verdict'] == 'UNKNOWN' and item['score'] is not None and item['score'] < 100
                        and not item['pending'] and (in_window or str(item['id']) in linked_ids)):
                    if time.monotonic() < deadline:
                        try:
                            detail = client.get(item['url'] + '?locale=en')
                            metadata = submission_time_metadata(detail.text, contest['id'], session['account'], item['id'], item['problemId'])
                            if metadata:
                                item.update(metadata, timeProbeAfter=None, timeProbeStatus='verified')
                                known_time_ids.add(item['id'])
                            item.update(detail_verdict(detail.text, item['score']))
                        except Exception:
                            item.update(verdict='UNKNOWN', rawVerdict='Detailed verdict unavailable', pending=False)
                            warnings.append(f"#{item['id']}: detailed verdict unavailable; refresh to retry")
                    else:
                        warnings.append('Detailed verdicts remain unverified; refresh to retry')
                self.ledger.save_submission(session['sessionId'], item)
            if not parsed['submissions'] or (page >= parsed['lastPage']):
                complete = not parsed['malformedRows']
                break
            if page_new == 0:
                warnings.append('Repeated history page detected; further pagination was stopped')
                break
        else:
            warnings.append('History exceeded ten pages; earlier submissions remain unverified')
        # Import known current facts before spending any requests on historical
        # timestamps. This stage never guesses an official VP's start from a
        # relative clock and never refines old out-of-window verdicts.
        probe_count = 0
        def time_priority(sid):
            attempt = time_attempts[sid]
            tried = isinstance(attempt, (int, float))
            # New/untried IDs first, then oldest retries. A minute-only alarm
            # must not retry the same latest three failures forever.
            return sid == preferred_sid, not tried, -attempt if tried else 0, int(sid)
        for sid in sorted(time_candidates, key=time_priority, reverse=True):
            if probe_count >= 3 or time.monotonic() >= deadline:
                break
            item = time_candidates[sid]
            attempt_at = self.clock()
            # Claim a short negative-cache window before the GET. Concurrent
            # helpers and a killed helper cannot turn each UI refresh into
            # another unbounded burst of old detail requests.
            with self.ledger.transaction():
                latest = self.ledger.provider_submission(session['account'], sid) or {}
                if latest.get('submittedAt') is not None:
                    item.update(submittedAt=latest['submittedAt'], timeSource=latest['timeSource'])
                    known_time_ids.add(sid)
                    self.ledger.save_submission(session['sessionId'], item)
                    continue
                retry_at = latest.get('timeProbeAfter')
                if isinstance(retry_at, (int, float)) and retry_at > attempt_at:
                    continue
                item.update(timeProbeAfter=attempt_at + 60000, timeProbeAttemptAt=attempt_at, timeProbeStatus='pending')
                self.ledger.save_submission(session['sessionId'], item)
            probe_count += 1
            try:
                detail = client.get(item['url'] + '?locale=en')
                metadata = submission_time_metadata(detail.text, contest['id'], session['account'], sid, item['problemId'])
                if metadata:
                    item.update(metadata, timeProbeAfter=None, timeProbeStatus='verified')
                    known_time_ids.add(sid)
                    start, at = session.get('startAt'), item['submittedAt']
                    in_window = start is not None and 0 <= at - start < session_duration(session)
                    if (item['verdict'] == 'UNKNOWN' and item['score'] is not None and item['score'] < 100
                            and not item['pending'] and (in_window or sid in linked_ids)):
                        item.update(detail_verdict(detail.text, item['score']))
                else:
                    item['timeProbeStatus'] = 'missing'
            except Exception:
                item['timeProbeStatus'] = 'unavailable'
            self.ledger.save_submission(session['sessionId'], item)
        verified_warnings = {f'#{sid}: absolute submission time is not verified' for sid in known_time_ids}
        warnings = [warning for warning in warnings if warning not in verified_warnings]
        return {'submissions': self.ledger.submissions(session['sessionId']), 'account': session['account'],
                'coverage': {'complete': complete and not warnings, 'pages': pages,
                             **({'warning': '; '.join(dict.fromkeys(warnings))} if warnings else {})}}

    def reconcile(self, session, args, refreshed):
        operation = self.ledger.operation(str(args.get('operationId', '')))
        if not operation or operation['sessionId'] != session['sessionId']:
            raise ValueError('Unknown submission operation')
        if operation['state'] not in {'unknown', 'submitting', 'preparing'}:
            raise ValueError('Only an unknown receipt can be reconciled')
        sid = str(args.get('submissionId', ''))
        submission = next((item for item in refreshed['submissions'] if item.get('id') == sid), None)
        if not submission:
            raise ValueError('The submission ID is not verified in this account history')
        if submission['problemId'] != operation['problemId'] or submission.get('language') != operation['language']:
            raise ValueError('The selected submission does not match this operation problem and language')
        at = submission.get('submittedAt')
        if at is None or not operation['submittedAt'] - 60000 <= at <= operation['submittedAt'] + 10 * 60000:
            raise ValueError('The selected submission time could not be matched to this operation')
        operation.update(id=sid, url=submission['url'], state='confirmed')
        self.ledger.save_operation(operation, 'confirmed')
        return {'submission': {**submission, 'operationId': operation['operationId']}, 'state': 'confirmed'}
