"""One durable application interface behind the Firefox and native entrypoints."""
from __future__ import annotations

import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlparse
import uuid


from . import __version__
from .ledger import Ledger, session_duration
from .resources import ResourceCache, ResourceError, problem_id
from .transport import BASE
from .virtual import VirtualPageError


from .domain import ApplicationError, now_ms, timestamp_ms
from .board_config import rankland_url, board_settings
from .judgers.qoj import QojJudger, load_upstream


class Application:
    def __init__(self, state_dir=None, qoj_path=None, *, fixture_origin=None, clock=now_ms):
        self.clock = clock
        default_state = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'qoj-vp'
        self.ledger = Ledger(state_dir or os.environ.get('QOJ_VP_STATE_DIR') or default_state)
        self.resources = ResourceCache(self.ledger.directory)
        # Source checkouts keep dependencies beside src; system launchers supply
        # QOJ_VP_QOJ_PATH for the installed layout.
        self.qoj_path = Path(qoj_path or os.environ.get('QOJ_VP_QOJ_PATH') or Path(__file__).resolve().parents[2] / 'vendor/qoj-submitter')
        # Test routing is supplied by installation/environment, never by a UI
        # task that might silently turn a real submission into a fake receipt.
        self.fixture_origin = fixture_origin or os.environ.get('QOJ_VP_FIXTURE_ORIGIN')
        self.judgers = {'qoj': QojJudger(ledger=self.ledger, resources=self.resources, clock=self.clock,
            qoj_path=self.qoj_path, fixture_origin=self.fixture_origin, view=self.view,
            create_session=self.create_session, cached_history=self.cached_history,
            operation_result=self.operation_result, session_started=self.session_started)}

    def session_started(self, session):
        session['ranklandUrl'] = rankland_url(session.get('ranklandUrl'), session['sessionId'], session['startAt'],
                                             allow_loopback=bool(self.fixture_origin), board=session.get('board'))
        session['ranklandPrepared'], session['ranklandPreparedAt'] = False, None

    def close(self):
        self.ledger.close()


    def __enter__(self):
        return self


    def __exit__(self, *_):
        self.close()


    def view(self, session):
        result = dict(session)
        result.setdefault("judger", "qoj")
        elapsed = max(0, self.clock() - session['startAt']) if session.get('startAt') is not None else 0
        result['elapsedMs'] = min(elapsed, session_duration(session))
        result['effectiveState'] = ('finished' if session['state'] == 'running' and elapsed >= session['durationMs'] else session['state'])
        return result


    def dispatch(self, method, args=None, exchange=None):
        if method.startswith('judger.'):
            action = method[len('judger.'):]
            method = 'prepare_resource' if action == 'prepare_resource' else 'qoj_' + action
        args = args or {}
        if not isinstance(args, dict):
            raise ApplicationError('VALIDATION_ERROR', 'Task arguments must be an object')
        try:
            if method == 'hello':
                return {'version': __version__, 'capabilities': ['qoj', 'sessions', 'samples', 'resource-cache', 'submission-history', 'rankland-outbox', 'judger-adapters', 'local-board'],
                        'helperPid': os.getpid(), 'stateDir': str(self.ledger.directory), 'fixture': bool(self.fixture_origin)}
            if method == 'create_session':
                return self.create_session(args)
            if method == 'list_sessions':
                return {'sessions': [self.view(s) for s in self.ledger.sessions()]}
            if method == 'settlement_sessions':
                return {'sessions': [self.view(s) for s in self.ledger.settlement_sessions(self.clock())]}
            if method == 'refresh_sessions':
                return {'sessions': [self.view(s) for s in self.ledger.refresh_sessions(self.clock())]}
            if method == 'session_snapshot':
                with self.ledger.transaction(write=False):
                    session = self.ledger.session(args.get('sessionId'))
                    contest = self.ledger.contest(session.get('account'), session['contestId'])
                    if contest is not None:
                        contest = {**contest, 'account': session.get('account'),
                                   'problems': self.problem_list(contest), 'source': 'verified-cache'}
                    return {'session': self.view(session), 'contest': contest, 'history': self.cached_history(session)}
            if method in {'inspect_session', 'start_session', 'archive_session', 'finish_session', 'delete_session',
                          'update_session', 'prepare_rankland'}:
                return self.session_action(method, args)
            if method == 'rankland_queue':
                return {'items': self.ledger.queue(args.get('sessionId'))}
            if method == 'rankland_plan':
                return self.ledger.rankland_plan(args.get('sessionId'))
            if method == 'rankland_ack':
                return self.ledger.ack(args.get('sessionId'), args)
            if method == 'rankland_ack_batch':
                return self.ledger.ack_batch(args.get('sessionId'), args.get('acknowledgements'),
                                             plan_token=args.get('planToken'))
            if method in {'resource_manifest', 'resource_chunk'}:
                session = self.ledger.session(args.get('sessionId'))
                return self.resources.manifest(session) if method == 'resource_manifest' else self.resources.chunk(session, args)
            if method == 'import_samples':
                return self.import_samples(args)
            if method in {'submitter_check', 'submitter_bind'}:
                from .submitter import check
                return check(self.qoj_path, self.ledger.session(args.get('sessionId')), args,
                             bind=method == 'submitter_bind')
            if method == 'prepare_resource':
                session = self.ledger.session(args.get('sessionId'))
                manual = self.resources.manual_entry(session, problem_id(args.get('problemId')))
                if manual:
                    return manual
            if method == 'qoj_submissions' and args.get('refresh') is False:
                session = self.ledger.session(args.get('sessionId'))
                return self.cached_history(session)
            action = method.removeprefix('judger.').removeprefix('qoj_')
            provider = args.get('provider', 'qoj')
            if args.get('sessionId'):
                provider = self.ledger.session(args['sessionId']).get('judger', 'qoj')
            adapter = self.judgers.get(provider)
            if adapter is None:
                raise ApplicationError('UNSUPPORTED_JUDGER', 'This Judger is not installed')
            adapter.fixture_origin, adapter.clock = self.fixture_origin, self.clock
            return adapter.execute(action, args, exchange)
        except (ResourceError, VirtualPageError) as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise ApplicationError('VALIDATION_ERROR', str(exc)) from exc
        except KeyError as exc:
            raise ApplicationError('NOT_FOUND', str(exc)) from exc


    def create_session(self, args):
        if args.get('judger', 'qoj') not in self.judgers:
            raise ApplicationError('UNSUPPORTED_JUDGER', 'This Judger is not installed')
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
                  'ranklandUrl': rankland_url(args.get('ranklandUrl'), sid, start,
                                              allow_loopback=bool(self.fixture_origin)),
                  'ranklandPrepared': False, 'ranklandPreparedAt': None}
        record['judger'] = args.get('judger', 'qoj')
        if 'board' in args:
            record['board'] = board_settings(args['board'])
            record['ranklandUrl'] = rankland_url(record['ranklandUrl'], sid, start,
                allow_loopback=bool(self.fixture_origin), board=record['board'])
        self.ledger.create_session(record)
        return self.view(record)


    def import_samples(self, args):
        session = self.ledger.session(args.get('sessionId'))
        pid = problem_id(args.get('problemId'))
        if not session.get('account'):
            raise ApplicationError('ACCOUNT_UNKNOWN', 'Read this contest with the QOJ account before importing samples')
        contest = self.ledger.contest(session['account'], session['contestId'])
        if contest is not None:
            if not any(str(p['id']) == pid for p in contest['problems'].values()):
                raise ValueError('The selected problem does not belong to this contest')
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
                    if record.get('qojVirtual', {}).get('mode') == 'qoj-native':
                        raise ApplicationError('QOJ_VIRTUAL_START_REQUIRED', 'Start this VP on the QOJ confirmation page; its verified clock will synchronize automatically')
                    record['startAt'], record['state'] = self.clock(), 'running'
                    record['ranklandUrl'] = rankland_url(record.get('ranklandUrl'), sid, record['startAt'],
                                                         allow_loopback=bool(self.fixture_origin), board=record.get('board'))
                    record['ranklandPrepared'], record['ranklandPreparedAt'] = False, None
            elif method == 'prepare_rankland':
                if record.get('startAt') is None or self.clock() < record['startAt']:
                    raise ApplicationError('SESSION_NOT_RUNNING', 'Start the VP session before opening its RankLand replay')
                if not record.get('ranklandUrl'):
                    raise ApplicationError('RANKLAND_NOT_CONFIGURED', 'Choose a RankLand contest URL first')
                previous_url = record['ranklandUrl']
                target = rankland_url(previous_url, sid, record['startAt'],
                                      allow_loopback=bool(self.fixture_origin), board=record.get('board'))
                if 'run' in dict(parse_qsl(urlparse(previous_url).query, keep_blank_values=True)):
                    # Preserve the exact old storage identity as migration
                    # evidence. The browser adapter decides whether any owned
                    # submissions can be migrated; no provider data is deleted.
                    record.setdefault('ranklandLegacyUrl', previous_url)
                record['ranklandUrl'] = target
                if not record.get('ranklandPrepared') or target != previous_url:
                    # Keep from=0 even for a first opening hours after Start.
                    # Adding elapsed here would count that time twice, while
                    # replacing `at` would select a different provider archive.
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
                if set(args) - {'sessionId', 'ranklandUrl', 'expectedRanklandUrl', 'title', 'durationMs', 'expectedDurationMs', 'board'}:
                    raise ValueError('Only session title, duration and RankLand URL may be changed')
                if 'expectedRanklandUrl' in args and record.get('ranklandUrl') != args['expectedRanklandUrl']:
                    return self.view(record)
                if 'expectedDurationMs' in args and record['durationMs'] != args['expectedDurationMs']:
                    return self.view(record)
                if ('title' in args or 'durationMs' in args) and record['state'] != 'prepared':
                    raise ApplicationError('SESSION_NOT_PREPARED', 'Title and duration can only be edited before starting')
                if 'board' in args:
                    record['board'] = board_settings(args['board'])
                if 'title' in args:
                    if not isinstance(args['title'], str) or not args['title'].strip() or len(args['title']) > 200 or any(ord(c) < 32 for c in args['title']):
                        raise ValueError('Use a nonempty title of at most 200 characters')
                    record['title'] = args['title'].strip()
                if 'durationMs' in args:
                    duration = args['durationMs']
                    if isinstance(duration, bool) or not isinstance(duration, int) or not 0 < duration <= 14 * 24 * 60 * 60 * 1000:
                        raise ValueError('Invalid contest duration')
                    record['durationMs'] = duration
                if 'ranklandUrl' in args or 'board' in args:
                    target = rankland_url(args.get('ranklandUrl', record.get('ranklandUrl')), sid, record['startAt'],
                                          allow_loopback=bool(self.fixture_origin), board=record.get('board'))
                    original = rankland_url(record.get('ranklandUrl'), sid, record['startAt'],
                                            allow_loopback=bool(self.fixture_origin))
                    # Compare canonical target configuration while ignoring
                    # managed run/time parameters; preserve the existing URL.
                    target_changed = (target is None) != (original is None)
                    if target is not None and original is not None:
                        target_parts, original_parts = urlparse(target), urlparse(original)
                        target_changed = ((target_parts.scheme, target_parts.netloc) !=
                            (original_parts.scheme, original_parts.netloc) or
                            dict(parse_qsl(target_parts.query, keep_blank_values=True)) !=
                            dict(parse_qsl(original_parts.query, keep_blank_values=True)))
                    if target_changed:
                        record['ranklandUrl'] = target
                        record['ranklandPrepared'], record['ranklandPreparedAt'] = False, None
                        record.pop('ranklandLegacyUrl', None)
            self.ledger.save_session(record)
        if target_changed:
            self.ledger.requeue_session(sid)
        return self.view(record)


    @staticmethod
    def problem_list(contest):
        return [{'label': label, **item, 'url': BASE + f"/contest/{contest['id']}/problem/{item['id']}"}
                for label, item in contest['problems'].items()]


    def cached_history(self, session):
        return {'submissions': self.ledger.submissions(session['sessionId']), 'account': session.get('account'),
                'coverage': {'complete': False, 'pages': 0, 'warning': 'Cached history; refresh to query QOJ'}}


    def operation_result(self, operation):
        if operation.get('id'):
            fact = self.ledger.provider_submission(operation['account'], operation['id'])
            if fact:
                return {'submission': self.ledger.submission_view(operation['sessionId'], {**fact, 'operationId': operation['operationId']}),
                        'state': 'confirmed'}
        view = self.ledger.submission_view(operation['sessionId'], self.ledger.operation_view(operation))
        return {'submission': view, 'state': view['state']}
