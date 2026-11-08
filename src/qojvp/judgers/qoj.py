"""QOJ Judger adapter: network facts, resources and submission reconciliation."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from ..account import current_account
from ..history import detail_verdict, parse_history, submission_source_hashes, submission_time_metadata
from ..inline_samples import statement_language_paths, statement_page_path, statement_sample_files
from ..ledger import receipt_metadata_matches, session_duration
from ..resources import ResourceError, problem_id
from ..transport import BASE, BrowserSession, MAX_SOURCE_BYTES
from ..virtual import dashboard_state, registration_rules, registration_snapshot, verify_page

MAX_ZIP_BYTES = 512 * 1024


from ..domain import ApplicationError, timestamp_ms

def load_upstream(path):
    root = Path(path).expanduser().resolve()
    if not (root / 'qoj_submitter/client.py').is_file():
        raise ApplicationError('QOJ_LIBRARY_MISSING', 'The pinned qoj-submitter library is not installed')
    sys.path.insert(0, str(root))
    modules = [importlib.import_module('qoj_submitter.' + name) for name in ('client', 'samples', 'cli')]
    if any(not Path(module.__file__).resolve().is_relative_to(root) for module in modules):
        raise ApplicationError('QOJ_LIBRARY_CONFLICT', 'An unexpected qoj-submitter installation was imported')
    return modules


class QojJudger:
    provider = 'qoj'
    actions = {'contest', 'problem_form', 'samples', 'submit', 'submissions', 'reconcile',
               'bind_virtual', 'confirm_virtual_start', 'prepare_resource'}

    def __init__(self, *, ledger, resources, clock, qoj_path, fixture_origin, view,
                 create_session, cached_history, operation_result, session_started):
        self.ledger, self.resources, self.clock = ledger, resources, clock
        self.qoj_path, self.fixture_origin = qoj_path, fixture_origin
        self.view, self.create_session = view, create_session
        self.cached_history, self.operation_result = cached_history, operation_result
        self.session_started = session_started

    def execute(self, action, args, exchange):
        if action not in self.actions:
            raise ApplicationError('UNKNOWN_METHOD', 'Unknown Judger action')
        method = action if action == 'prepare_resource' else 'qoj_' + action
        if method not in {'qoj_contest', 'qoj_problem_form', 'qoj_samples', 'qoj_submit', 'qoj_submissions', 'qoj_reconcile', 'prepare_resource',
                          'qoj_bind_virtual', 'qoj_confirm_virtual_start'}:
            raise ApplicationError('UNKNOWN_METHOD', 'Unknown application method')
        if not callable(exchange):
            raise ApplicationError('HTTP_BRIDGE_REQUIRED', 'This operation requires a Firefox QOJ tab')
        modules = load_upstream(self.qoj_path)
        transport = BrowserSession(exchange, allow_post=method == 'qoj_submit', fixture_origin=self.fixture_origin)
        client = modules[0].QojClient(BASE, session=transport)
        try:
            if method == 'qoj_bind_virtual':
                return self.bind_virtual(args, client)
            if method == 'qoj_confirm_virtual_start':
                return self.confirm_virtual_start(args, client)
            if method == 'qoj_contest':
                account, _ = current_account(client)
                contest = self.read_contest(client, modules[0].contest_id(str(args.get('contestId', ''))))
                self.ledger.save_contest(account, contest)
                return {**contest, 'account': account, 'problems': self.problem_list(contest),
                        'source': 'fixture' if self.fixture_origin else 'real-qoj-browser'}
            session = self.ledger.session(args.get('sessionId'))
            if method == 'qoj_submit':
                return self.submit(session, args, client, modules)
            if method == 'prepare_resource':
                return self.prepare_resource(session, args, client, modules, transport)
            if method in {'qoj_submissions', 'qoj_reconcile'}:
                # An offline/login failure before the first history page
                # must also keep an ended session eligible for retry.
                self.ledger.mark_history_refresh(session['sessionId'], self.clock(), complete=False)
            self.authenticate(client, session)
            contest = self.read_contest(client, session['contestId'])
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
                                     preferred_sid=str(args.get('submissionId', '')) if method == 'qoj_reconcile' else None,
                                     recover_receipts=method != 'qoj_reconcile')
            if method == 'qoj_reconcile':
                return self.reconcile(session, args, refreshed, client)
            return refreshed
        except modules[0].QojError as exc:
            raise self.upstream_error(exc) from exc

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
            raw_files = QojJudger.statement_resource_files(contest, problem, client)
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
            contest = self.read_contest(client, session['contestId'])
            self.ledger.save_contest(session.get('account'), contest)
            problem = self.problem(contest, {'problemId': pid})
            label = next(key for key, item in contest['problems'].items() if str(item['id']) == pid)
            metadata, payload = self.extract_resource(contest, problem, client, modules, transport, interactive_hint=hint)
            return self.resources.store(session, pid, metadata, payload, self.clock())
        except (ApplicationError, modules[0].QojError, ResourceError) as exc:
            code = self.upstream_error(exc).code if isinstance(exc, modules[0].QojError) else exc.code
            return self.resources.unknown(session, pid, code, self.clock(), label=label, interactive_hint=hint)


    def virtual_context(self, cid, client, *, expected_account=None, native_duration_ms=None):
        if not isinstance(cid, str) or not re.fullmatch(r'\d{1,20}', cid):
            raise ValueError('Expected a numeric QOJ contest ID')
        account, logged_in = current_account(client)
        if not account:
            code = 'ACCOUNT_UNKNOWN' if logged_in else 'LOGIN_REQUIRED'
            raise ApplicationError(code, 'Log in to QOJ in Firefox with an identifiable account before continuing')
        if expected_account and account.casefold() != expected_account.casefold():
            raise ApplicationError('ACCOUNT_MISMATCH', 'The Firefox account differs from this VP session account')
        contest = self.read_contest(client, cid)
        response = client.session.last_response
        verify_page(response, cid, account)
        virtual = dashboard_state(response.text, cid, native_duration_ms=native_duration_ms)
        return account, contest, virtual


    @staticmethod
    def virtual_binding_matches(session, cid, account):
        bound = session.get('qojVirtual')
        return (isinstance(bound, dict) and bound.get('mode') == 'qoj-native' and bound.get('origin') == BASE
                and str(bound.get('contestId')) == cid and str(session.get('contestId')) == cid
                and str(bound.get('account', '')).casefold() == account.casefold()
                and str(session.get('account', '')).casefold() == account.casefold())


    def virtual_result(self, session, contest, virtual):
        return {'session': self.view(session),
                'contest': {**contest, 'account': session['account'], 'problems': self.problem_list(contest),
                            'source': 'fixture' if self.fixture_origin else 'real-qoj-browser'},
                'virtual': virtual}


    def bind_virtual(self, args, client):
        cid = args.get('contestId')
        account, contest, virtual = self.virtual_context(cid, client)
        dashboard_html = client.session.last_response.text
        rules = (registration_snapshot(args['registrationPage'], cid, account)
                 if args.get('registrationPage') is not None else None)
        bindings = [s for s in self.ledger.sessions() if self.virtual_binding_matches(s, cid, account)
                    and s['state'] not in {'archived', 'finished'}]
        durations = {s['qojVirtual'].get('durationMs') for s in bindings}
        if len(durations) > 1:
            raise ApplicationError('QOJ_VIRTUAL_DURATION_MISMATCH', 'Existing native QOJ bindings disagree about the contest duration')
        duration = durations.pop() if bindings else rules['durationMs'] if rules else None
        if rules and bindings and rules['durationMs'] != duration:
            raise ApplicationError('QOJ_VIRTUAL_DURATION_MISMATCH', 'Captured rules differ from the existing native QOJ binding')
        if duration is None:
            registration = client.get(f'/contest/{cid}/virtual/register')
            verify_page(registration, cid, account, registration=True)
            rules = registration_rules(registration.text, cid)
            duration = rules['durationMs']
        # After Start, QOJ redirects /virtual/register to /contests. Either
        # earlier binding or the browser's validated pre-POST page provides
        # the original rules; the active dashboard supplies its own clock.
        virtual = {**dashboard_state(dashboard_html, cid, native_duration_ms=duration),
                   'durationMs': duration, 'registrationUrl': f'{BASE}/contest/{cid}/virtual/register'}
        with self.ledger.transaction():
            candidates = [s for s in self.ledger.sessions() if str(s['contestId']) == cid
                          and str(s.get('account', '')).casefold() == account.casefold()
                          and s['state'] not in {'archived', 'finished'}]
            prepared = [s for s in candidates if s.get('startAt') is None and s['state'] == 'prepared']
            prepared.sort(key=lambda s: not self.virtual_binding_matches(s, cid, account))
            started = [s for s in candidates if self.virtual_binding_matches(s, cid, account)
                       and s.get('startAt') is not None]
            if virtual.get('startAt') is not None and any(s['startAt'] != virtual['startAt'] for s in started):
                raise ApplicationError('QOJ_VIRTUAL_CLOCK_CONFLICT', 'The verified QOJ VP start differs from its existing session')
            session = started[0] if started else prepared[0] if prepared else None
            if session and session['durationMs'] != duration:
                raise ApplicationError('QOJ_VIRTUAL_DURATION_MISMATCH',
                    'The prepared contest duration differs from QOJ native VP rules; adjust it before binding')
            if session is None:
                title = re.sub(r'\s+-\s+(?:比赛主页\s+-\s+比赛|Dashboard\s+-\s+Contest)\s+-\s+QOJ\.ac\s*$',
                               '', str(contest.get('name') or ''), flags=re.I).strip()
                session = self.create_session({'contestId': cid, 'account': account, 'durationMs': duration,
                                               'title': title or f'QOJ Contest {cid}'})
                session.pop('elapsedMs', None)
                session.pop('effectiveState', None)
            old_binding = session.get('qojVirtual') or {}
            # A registration response can arrive after another helper confirms
            # the start. Keep that confirmed session and its replay target.
            observed_state = (old_binding['state'] if session.get('startAt') is not None
                              and virtual.get('startAt') is None else virtual['state'])
            session['qojVirtual'] = {**old_binding, 'mode': 'qoj-native', 'origin': BASE, 'contestId': cid,
                'account': account, 'registrationUrl': f'{BASE}/contest/{cid}/virtual/register',
                'state': observed_state, 'durationMs': duration, 'boundAt': old_binding.get('boundAt', self.clock()),
                'rulesSource': old_binding.get('rulesSource') or (rules or {}).get('source', 'qoj-registration-rules')}
            self.ledger.save_session(session)
            self.ledger.save_contest(account, contest)
        return self.virtual_result(session, contest, virtual)


    def confirm_virtual_start(self, args, client):
        session = self.ledger.session(args.get('sessionId'))
        cid, account = str(session['contestId']), session.get('account')
        if not account or not self.virtual_binding_matches(session, cid, account):
            raise ApplicationError('QOJ_VIRTUAL_NOT_BOUND', 'Prepare this contest from its QOJ VP confirmation page first')
        duration = session['qojVirtual'].get('durationMs')
        if session['durationMs'] != duration:
            raise ApplicationError('QOJ_VIRTUAL_DURATION_MISMATCH', 'The local duration differs from the verified QOJ VP rules')
        account, contest, virtual = self.virtual_context(cid, client, expected_account=account, native_duration_ms=duration)
        # Only a verified provider clock may transition the local session.
        # Unsupported active-page formats remain unknown and are retried by the browser.
        start = virtual.get('startAt')
        if start is None:
            return self.virtual_result(session, contest, virtual)
        start = timestamp_ms(start)
        if virtual.get('timeSource') not in {'provider-absolute', 'provider-countdown'} or virtual['state'] not in {'running', 'finished'}:
            raise ApplicationError('QOJ_VIRTUAL_TIME_UNVERIFIED', 'QOJ did not expose a verified native VP start time')
        changed = False
        with self.ledger.transaction():
            session = self.ledger.session(args.get('sessionId'))
            if not self.virtual_binding_matches(session, cid, account):
                raise ApplicationError('QOJ_VIRTUAL_NOT_BOUND', 'This session binding changed during verification')
            if session['durationMs'] != virtual.get('durationMs'):
                raise ApplicationError('QOJ_VIRTUAL_DURATION_MISMATCH', 'The local duration differs from the native QOJ VP')
            if session['state'] in {'archived', 'finished'}:
                raise ApplicationError('QOJ_VIRTUAL_SESSION_CLOSED', 'A finished or archived local session cannot be started')
            if session.get('startAt') is not None and session['startAt'] != start:
                raise ApplicationError('QOJ_VIRTUAL_CLOCK_CONFLICT', 'The verified QOJ VP start differs from this session clock')
            if session.get('startAt') is None:
                session.update(startAt=start, state='running')
                self.session_started(session)
                changed = True
            session['qojVirtual'].update(state=virtual['state'], startAt=start, timeSource=virtual['timeSource'],
                                         confirmedAt=self.clock(), source=virtual['source'])
            if virtual.get('timeSource') == 'provider-countdown':
                session['qojVirtual'].update(serverNow=virtual['serverNow'], remainingMs=virtual['remainingMs'])
            self.ledger.save_session(session)
            self.ledger.save_contest(account, contest)
        if changed:
            self.ledger.requeue_session(session['sessionId'])
        return self.virtual_result(session, contest, virtual)


    @staticmethod
    def read_contest(client, cid):
        from ..scoreboards import contest_navigation
        contest = client.contest(cid)
        response = client.session.last_response
        return {**contest, **contest_navigation(response.text, contest['id'])}


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
        contest = self.read_contest(client, session['contestId'])
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
            # The durable operation ledger below owns receipt recovery.
            url = client.submit(form, filename, contents, language, contest['id'], recover_receipt=False)
        except modules[0].UnknownSubmission:
            record.update(state='unknown', rawVerdict='Receipt unknown; check QOJ before retrying')
            self.ledger.save_operation(record, 'unknown')
            # QOJ can legitimately redirect to the contest submission list.
            # Recover only through read-only history/source verification; the
            # original source must never be sent again to obtain a receipt.
            try:
                self.refresh(session, contest, client)
            except Exception:
                pass  # Keep the durable unknown intent if QOJ cannot be read.
            return self.operation_result(self.ledger.operation(operation_id))
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


    def refresh(self, session, contest, client, *, preferred_sid=None, recover_receipts=True):
        refresh_started_at = self.clock()
        warnings, pages, seen = [], 0, set()
        complete, history_verified = False, True
        deadline = time.monotonic() + 35
        time_candidates, time_attempts, known_time_ids = {}, {}, set()
        backfill_times = session.get('startAt') is not None and session.get('state') in {'running', 'finished'}
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
                history_verified = False
            page_new = 0
            for item in parsed['submissions']:
                if item['id'] in seen:
                    continue
                page_new += 1
                seen.add(item['id'])
                previous = self.ledger.provider_submission(session['account'], item['id']) or {}
                if (item.get('submittedAt') is None and previous.get('submittedAt') is not None
                        and previous.get('timeSource') == 'provider-absolute'):
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
                if latest.get('submittedAt') is not None and latest.get('timeSource') == 'provider-absolute':
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
        if recover_receipts and complete and history_verified:
            self.recover_receipts(session, client, deadline, seen)
        # Use the pass's start, so a request begun before the deadline cannot
        # satisfy the post-deadline catch-up. Even a pages=0 cached fallback is
        # an incomplete attempt that must remain eligible for another refresh.
        self.ledger.mark_history_refresh(session['sessionId'], refresh_started_at,
                                        complete=complete and history_verified and not warnings)
        return {'submissions': self.ledger.submissions(session['sessionId']), 'account': session['account'],
                'coverage': {'complete': complete and not warnings, 'pages': pages,
                             **({'warning': '; '.join(dict.fromkeys(warnings))} if warnings else {})}}


    def receipt_source_evidence(self, session, operation, submission, client):
        sid = str(submission['id'])
        detail = client.get(f'/submission/{sid}?locale=en')
        final = urlparse(detail.url)
        if (detail.status_code != 200 or final.scheme != 'https' or final.netloc != 'qoj.ac' or
                final.path.rstrip('/') != f'/submission/{sid}'):
            raise ApplicationError('RECEIPT_SOURCE_UNVERIFIED', 'QOJ did not expose the selected submission source')
        hashes = submission_source_hashes(detail.text, session['contestId'], session['account'], sid,
                                          operation['problemId'], operation['language'])
        if not hashes or hashes['submittedAt'] != submission.get('submittedAt'):
            raise ApplicationError('RECEIPT_SOURCE_UNVERIFIED', 'The submission source and metadata could not be verified')
        match = next(((ending, value) for ending, value in hashes['variants'].items()
                      if value['sha256'] == operation['sourceSha256']), None)
        if not match:
            raise ApplicationError('RECEIPT_SOURCE_MISMATCH', 'The selected submission contains different source code')
        ending, value = match
        return {key: item for key, item in hashes.items() if key != 'variants'} | {
            'sourceSha256': value['sha256'], 'sourceBytes': value['bytes'], 'lineEndings': ending}


    def recover_receipts(self, session, client, deadline, verified_ids):
        attempts = 0
        for operation in self.ledger.operations(session['sessionId']):
            if attempts >= 3 or time.monotonic() >= deadline:
                break
            if operation['state'] != 'unknown' or operation.get('id') or not operation.get('sourceSha256'):
                continue
            facts = [item for item in self.ledger._provider_rows(session['sessionId']) if item['id'] in verified_ids]
            candidates = [item for item in facts if receipt_metadata_matches(operation, item, automatic=True)]
            if len(candidates) != 1:
                continue
            claimed = self.ledger.claim_receipt_probe(operation['operationId'], self.clock())
            if not claimed:
                continue
            attempts += 1
            status = 'unavailable'
            try:
                evidence = self.receipt_source_evidence(session, claimed, candidates[0], client)
                self.ledger.confirm_operation(operation['operationId'], str(candidates[0]['id']), evidence=evidence, automatic=True)
                continue
            except ApplicationError as exc:
                if exc.code == 'RECEIPT_SOURCE_MISMATCH':
                    status = 'source-mismatch'
            except ValueError:
                status = 'ambiguous'
            except Exception:
                pass  # A failed GET never permits another source submission.
            self.ledger.receipt_probe_result(operation['operationId'], claimed['receiptProbeAttemptAt'], status)


    def reconcile(self, session, args, refreshed, client):
        operation = self.ledger.operation(str(args.get('operationId', '')))
        if not operation or operation['sessionId'] != session['sessionId']:
            raise ValueError('Unknown submission operation')
        sid = str(args.get('submissionId', ''))
        if operation['state'] == 'confirmed' and operation.get('id') == sid:
            return self.operation_result(operation)
        if operation['state'] not in {'unknown', 'submitting', 'preparing'}:
            raise ValueError('Only an unknown receipt can be reconciled')
        submission = next((item for item in refreshed['submissions'] if item.get('id') == sid), None)
        if not submission:
            raise ValueError('The submission ID is not verified in this account history')
        if not receipt_metadata_matches(operation, submission):
            raise ValueError('The selected submission time could not be matched to this operation')
        evidence = self.receipt_source_evidence(session, operation, submission, client) if operation.get('sourceSha256') else None
        confirmed = self.ledger.confirm_operation(operation['operationId'], sid, evidence=evidence)
        return self.operation_result(confirmed)


    @staticmethod
    def problem_list(contest):
        return [{'label': label, **item, 'url': BASE + f"/contest/{contest['id']}/problem/{item['id']}"}
                for label, item in contest['problems'].items()]
