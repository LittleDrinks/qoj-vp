"""Durable sessions, submission intents, provider facts and independent outbox."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import uuid

from .history import FINAL_VERDICTS


def session_duration(session):
    """The local participation window can end before the configured duration."""
    duration = session['durationMs']
    if session.get('startAt') is not None and session.get('finishedAt') is not None:
        duration = min(duration, max(0, session['finishedAt'] - session['startAt']))
    return duration


def receipt_metadata_matches(operation, submission, *, automatic=False):
    """Match provider identity and clocks before ever examining source bytes."""
    if (not operation.get('account') or
            operation['account'].casefold() != str(submission.get('account', '')).casefold() or
            str(operation.get('problemId')) != str(submission.get('problemId')) or
            not operation.get('language') or operation['language'] != submission.get('language')):
        return False
    sent, observed = operation.get('submittedAt'), submission.get('submittedAt')
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in (sent, observed)):
        return False
    if automatic:
        # QOJ's date is second-granularity. Earlier submissions from a preceding
        # second must never become the receipt of a later failed send attempt.
        return submission.get('timeSource') == 'provider-absolute' and int(sent // 1000) * 1000 <= observed <= sent + 60000
    return sent - 60000 <= observed <= sent + 10 * 60000


class Ledger:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'vp.sqlite3'
        self.db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, record_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
              operation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
              fingerprint TEXT NOT NULL, state TEXT NOT NULL, created_at INTEGER NOT NULL, record_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS operation_fingerprint ON operations(session_id,fingerprint);
            CREATE TABLE IF NOT EXISTS submissions (
              account TEXT NOT NULL, submission_id TEXT NOT NULL, record_json TEXT NOT NULL,
              revision INTEGER NOT NULL, PRIMARY KEY(account,submission_id));
            CREATE TABLE IF NOT EXISTS session_submissions (
              session_id TEXT NOT NULL REFERENCES sessions(session_id), account TEXT NOT NULL,
              submission_id TEXT NOT NULL, PRIMARY KEY(session_id,account,submission_id));
            CREATE TABLE IF NOT EXISTS rankland_queue (
              queue_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
              account TEXT NOT NULL, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
              state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, record_json TEXT NOT NULL,
              UNIQUE(session_id,account,submission_id));
            CREATE TABLE IF NOT EXISTS contest_snapshots (
              account TEXT NOT NULL, contest_id TEXT NOT NULL, record_json TEXT NOT NULL,
              PRIMARY KEY(account,contest_id));
        ''')
        os.chmod(self.path, 0o600)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self, *, write=True):
        self.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def session(self, session_id):
        row = self.db.execute('SELECT record_json FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if row is None:
            raise KeyError('Unknown session')
        return json.loads(row[0])

    def sessions(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT record_json FROM sessions ORDER BY created_at DESC,session_id')]

    def create_session(self, record):
        self.db.execute('INSERT INTO sessions VALUES(?,?,?)',
                        (record['sessionId'], record['createdAt'], json.dumps(record)))

    def save_session(self, record):
        self.db.execute('UPDATE sessions SET record_json=? WHERE session_id=?', (json.dumps(record), record['sessionId']))

    def save_contest(self, account, contest):
        if account:
            self.db.execute('''INSERT INTO contest_snapshots VALUES(?,?,?)
                ON CONFLICT(account,contest_id) DO UPDATE SET record_json=excluded.record_json''',
                (account.casefold(), str(contest['id']), json.dumps(contest)))

    def contest(self, account, contest_id):
        row = self.db.execute('SELECT record_json FROM contest_snapshots WHERE account=? AND contest_id=?',
                              ((account or '').casefold(), str(contest_id))).fetchone()
        return json.loads(row[0]) if row else None

    def has_unresolved_operations(self, session_id):
        return self.db.execute('''SELECT 1 FROM operations WHERE session_id=?
            AND state NOT IN ('confirmed','rejected') LIMIT 1''', (session_id,)).fetchone() is not None

    def delete_session(self, session_id):
        """Called inside the application's transaction after eligibility checks.

        Resource objects and verified contest snapshots are account/contest
        scoped. Deleting one local practice must not remove those shared data.
        """
        linked = self.db.execute('SELECT account,submission_id FROM session_submissions WHERE session_id=?',
                                 (session_id,)).fetchall()
        self.db.execute('DELETE FROM rankland_queue WHERE session_id=?', (session_id,))
        self.db.execute('DELETE FROM operations WHERE session_id=?', (session_id,))
        self.db.execute('DELETE FROM session_submissions WHERE session_id=?', (session_id,))
        for account, submission_id in linked:
            self.db.execute('''DELETE FROM submissions WHERE account=? AND submission_id=?
                AND NOT EXISTS (SELECT 1 FROM session_submissions WHERE account=? AND submission_id=?)''',
                (account, submission_id, account, submission_id))
        self.db.execute('DELETE FROM sessions WHERE session_id=?', (session_id,))

    def bind_account(self, session_id, account):
        with self.transaction():
            record = self.session(session_id)
            if record.get('account') and record['account'].casefold() != account.casefold():
                raise ValueError('Browser account differs from the session account')
            record['account'] = account
            self.save_session(record)
        return record

    def operation(self, operation_id):
        row = self.db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        if row is None:
            return None
        record = json.loads(row['record_json'])
        record.update(state=row['state'], fingerprint=row['fingerprint'])
        return record

    def operations(self, session_id):
        return [self.operation(row[0]) for row in self.db.execute(
            'SELECT operation_id FROM operations WHERE session_id=? ORDER BY created_at', (session_id,)).fetchall()]

    def claim_receipt_probe(self, operation_id, now):
        with self.transaction():
            operation = self.operation(operation_id)
            if not operation or operation['state'] != 'unknown' or operation.get('id'):
                return None
            retry = operation.get('receiptProbeAfter')
            if isinstance(retry, (int, float)) and retry > now:
                return None
            operation.update(receiptProbeAfter=now + 60000, receiptProbeAttemptAt=now, receiptProbeStatus='pending')
            self.save_operation(operation, 'unknown')
            return operation

    def receipt_probe_result(self, operation_id, attempt_at, status):
        with self.transaction():
            operation = self.operation(operation_id)
            if (operation and operation['state'] == 'unknown' and not operation.get('id') and
                    operation.get('receiptProbeAttemptAt') == attempt_at):
                operation['receiptProbeStatus'] = status
                self.save_operation(operation, 'unknown')

    def confirm_operation(self, operation_id, submission_id, *, evidence=None, automatic=False):
        """Atomically bind an existing provider fact; never create/retry a POST."""
        with self.transaction():
            operation = self.operation(operation_id)
            if not operation:
                raise ValueError('Unknown submission operation')
            session = self.session(operation['sessionId'])
            account = (session.get('account') or '').casefold()
            fact = self.provider_submission(account, submission_id)
            linked = self.db.execute('SELECT 1 FROM session_submissions WHERE session_id=? AND account=? AND submission_id=?',
                                     (session['sessionId'], account, submission_id)).fetchone()
            if not fact or not linked or not receipt_metadata_matches(operation, fact, automatic=automatic):
                raise ValueError('The provider submission does not match this local operation')
            if operation.get('id'):
                if operation['id'] == submission_id and operation['state'] == 'confirmed':
                    return operation
                raise ValueError('This operation already has another submission receipt')
            allowed = {'unknown'} if automatic else {'unknown', 'preparing', 'submitting'}
            if operation['state'] not in allowed:
                raise ValueError('Only an unresolved receipt can be reconciled')
            if operation.get('sourceSha256'):
                expected = {'account': account, 'contestId': str(session['contestId']), 'submissionId': submission_id,
                    'problemId': str(fact['problemId']), 'language': fact['language'], 'submittedAt': fact['submittedAt'],
                    'sourceSha256': operation['sourceSha256']}
                if not isinstance(evidence, dict) or any(evidence.get(key) != value for key, value in expected.items()):
                    raise ValueError('The submission source and metadata were not verified')
            elif automatic:
                raise ValueError('Automatic receipt recovery requires a source hash')
            for row in self.db.execute('SELECT operation_id FROM operations WHERE operation_id<>?', (operation_id,)).fetchall():
                other = self.operation(row[0])
                if str(other.get('account', '')).casefold() != account:
                    continue
                if str(other.get('id')) == submission_id:
                    raise ValueError('This provider submission is already bound to another local operation')
                if (automatic and other['state'] in {'preparing', 'submitting', 'unknown'} and
                        other.get('sourceSha256') in {None, operation['sourceSha256']} and
                        receipt_metadata_matches(other, fact, automatic=True) and
                        str(self.session(other['sessionId'])['contestId']) == str(session['contestId'])):
                    raise ValueError('More than one local operation could own this provider submission')
            if automatic:
                facts = self._provider_rows(session['sessionId'])
                candidates = [item for item in facts if receipt_metadata_matches(operation, item, automatic=True)]
                unknown_metadata = [item for item in facts if
                    str(item.get('problemId')) == str(operation['problemId']) and
                    item.get('language') in {None, '', operation['language']} and
                    (item.get('submittedAt') is None or (not item.get('language') and
                     receipt_metadata_matches(operation, {**item, 'language': operation['language']}, automatic=True)))]
                if len(candidates) != 1 or candidates[0]['id'] != submission_id or unknown_metadata:
                    raise ValueError('The provider history does not identify a unique receipt candidate')
            operation.update(id=submission_id, url=fact['url'], state='confirmed', receiptProbeStatus='verified')
            operation['receiptEvidence'] = {'method': 'source-sha256' if evidence else 'manual-selected-history',
                                            'submissionId': submission_id, 'submittedAt': fact['submittedAt']}
            self.save_operation(operation, 'confirmed')
            return operation

    def begin_operation(self, record, fingerprint):
        with self.transaction():
            existing = self.operation(record['operationId'])
            if existing:
                if existing['sessionId'] != record['sessionId'] or existing['fingerprint'] != fingerprint:
                    raise ValueError('operationId is already bound to different submission data')
                return existing, False
            # A new click/operation ID must not bypass an unresolved identical
            # source intent after a browser or helper disconnect.
            row = self.db.execute('''SELECT operation_id FROM operations
                 WHERE session_id=? AND fingerprint=? AND state IN ('preparing','submitting','unknown')
                 ORDER BY created_at LIMIT 1''', (record['sessionId'], fingerprint)).fetchone()
            if row:
                return self.operation(row[0]), False
            current = self.session(record['sessionId'])
            if (current['state'] != 'running' or current.get('startAt') is None
                    or not 0 <= record['submittedAt'] - current['startAt'] < session_duration(current)):
                raise ValueError('The local session ended before the submission could be sent')
            self.db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',
                            (record['operationId'], record['sessionId'], fingerprint, 'preparing',
                             record['submittedAt'], json.dumps(record)))
        return self.operation(record['operationId']), True

    def save_operation(self, record, state):
        self.db.execute('UPDATE operations SET state=?,record_json=? WHERE operation_id=?',
                        (state, json.dumps(record), record['operationId']))

    def provider_submission(self, account, sid):
        row = self.db.execute('SELECT record_json FROM submissions WHERE account=? AND submission_id=?',
                              (account.casefold(), sid)).fetchone()
        return json.loads(row[0]) if row else None

    def save_submission(self, session_id, incoming):
        account, sid = incoming['account'].casefold(), str(incoming['id'])
        with self.transaction() if not self.db.in_transaction else nullcontext():
            row = self.db.execute('SELECT record_json,revision FROM submissions WHERE account=? AND submission_id=?',
                                  (account, sid)).fetchone()
            old = json.loads(row['record_json']) if row else {}
            merged = {**old, **incoming}
            if incoming.get('submittedAt') is None and old.get('submittedAt') is not None:
                for key in ('submittedAt', 'timeSource'):
                    merged[key] = old[key]
            if not incoming.get('language') and old.get('language'):
                merged['language'] = old['language']
            changed = not row or any(merged.get(k) != old.get(k) for k in
                                    ('verdict', 'rawVerdict', 'score', 'pending', 'submittedAt', 'timeSource', 'problemId', 'problemLabel'))
            revision = row['revision'] + int(changed) if row else 1
            merged['revision'] = revision
            self.db.execute('''INSERT INTO submissions VALUES(?,?,?,?)
                ON CONFLICT(account,submission_id) DO UPDATE SET record_json=excluded.record_json,revision=excluded.revision''',
                            (account, sid, json.dumps(merged), revision))
            self.db.execute('INSERT OR IGNORE INTO session_submissions VALUES(?,?,?)', (session_id, account, sid))
            # A shared provider fact may be associated with more than one local
            # session. A rejudge updates every relevant outbox revision.
            links = self.db.execute('SELECT session_id FROM session_submissions WHERE account=? AND submission_id=?',
                                    (account, sid)).fetchall()
            for link in links:
                self._queue(link[0], merged, revision)
        return self.submission_view(session_id, merged)

    def _queue(self, session_id, submission, revision, *, reset=False):
        session = self.session(session_id)
        start, at = session.get('startAt'), submission.get('submittedAt')
        eligible = (session.get('ranklandUrl') and start is not None and at is not None
                    and 0 <= at - start < session_duration(session))
        verdict = submission.get('verdict')
        previous = self.db.execute('SELECT * FROM rankland_queue WHERE session_id=? AND account=? AND submission_id=?',
                                  (session_id, submission['account'].casefold(), submission['id'])).fetchone()
        if not eligible and previous is None:
            return
        # Rejudging to pending/unknown invalidates any earlier final outbox
        # receipt but cannot be expressed as a blind extra manual submission.
        if verdict not in FINAL_VERDICTS and previous is None:
            return
        value = {"sessionId": session_id, "submissionId": submission['id'],
                 "problemId": submission['problemId'], "problemLabel": submission['problemLabel'],
                 "elapsedMs": at - start if at is not None and start is not None else None,
                 "verdict": verdict, "rawVerdict": submission['rawVerdict'],
                 "sourceId": f"qoj:{submission['account'].casefold()}:{submission['id']}"}
        if not eligible:
            # Retain a newer tombstone revision: an older delivered result must
            # be withdrawn if QOJ corrects its time outside this session.
            value['withdrawn'] = True
        queue_id = previous['queue_id'] if previous else str(uuid.uuid4())
        if previous and previous['revision'] == revision and not reset:
            return
        previous_value = json.loads(previous['record_json']) if previous else {}
        delivered_before = previous and (previous['state'] == 'synced' or 'receipt' in previous_value)
        if delivered_before and not reset:
            value['previousVerdict'] = previous_value.get('verdict')
            if 'receipt' in previous_value:
                value['receipt'] = previous_value['receipt']
            value['rejudge'] = True
        state = 'pending' if verdict in FINAL_VERDICTS and not (delivered_before and not reset) else 'needs-review'
        self.db.execute('''INSERT INTO rankland_queue VALUES(?,?,?,?,?,?,?,?)
             ON CONFLICT(session_id,account,submission_id) DO UPDATE SET
             revision=excluded.revision,state=excluded.state,record_json=excluded.record_json''',
                        (queue_id, session_id, submission['account'].casefold(), submission['id'],
                         revision, state, 0, json.dumps(value)))

    def requeue_session(self, session_id):
        with self.transaction():
            for submission in self._provider_rows(session_id):
                self._queue(session_id, submission, submission['revision'], reset=True)

    def submission_view(self, session_id, submission):
        result = dict(submission)
        session = self.session(session_id)
        at, start = result.get('submittedAt'), session.get('startAt')
        result['elapsedMs'] = at - start if at is not None and start is not None else None
        result['inSession'] = (result['elapsedMs'] is not None and 0 <= result['elapsedMs'] < session_duration(session))
        return result

    @staticmethod
    def operation_view(record):
        result = {key: value for key, value in record.items() if key not in ('fingerprint', 'sourceSha256')}
        if result['state'] in {'preparing', 'submitting'}:
            result['state'] = 'unknown'
        return result

    def _provider_rows(self, session_id):
        return [json.loads(row[0]) for row in self.db.execute('''SELECT s.record_json FROM submissions s
                JOIN session_submissions l USING(account,submission_id) WHERE l.session_id=?''', (session_id,))]

    def submissions(self, session_id):
        results = [self.submission_view(session_id, row) for row in self._provider_rows(session_id)]
        operations = self.db.execute('SELECT operation_id FROM operations WHERE session_id=?', (session_id,)).fetchall()
        for row in operations:
            operation = self.operation(row[0])
            if not operation.get('id'):
                results.append(self.submission_view(session_id, self.operation_view(operation)))
            else:
                for submission in results:
                    if submission['id'] == operation['id']:
                        submission['operationId'] = operation['operationId']
        return sorted(results, key=lambda item: (item.get('submittedAt') or 0, item.get('id') or ''), reverse=True)

    def queue(self, session_id):
        self.session(session_id)
        result = []
        for row in self.db.execute('SELECT * FROM rankland_queue WHERE session_id=? ORDER BY rowid', (session_id,)):
            item = json.loads(row['record_json'])
            item.update(queueId=row['queue_id'], revision=row['revision'], state=row['state'], attempts=row['attempts'])
            result.append(item)
        return result

    def rankland_plan(self, session_id):
        """Return the full desired projection, retaining source identities.

        Pending/unknown results are barriers only for later submissions of the
        same problem. A delayed WA must precede its later AC when delivered.
        Previously delivered rejudgements are included: the receiving adapter
        replaces its owned record instead of appending another attempt.
        """
        with self.transaction(write=False) if not self.db.in_transaction else nullcontext():
            session = self.session(session_id)
            queued = self.queue(session_id)
            by_id = {item['submissionId']: item for item in queued}
            records = [item for item in self.submissions(session_id) if item['inSession']]

            def order(item):
                sid = str(item.get('id') or '')
                # Locally uncertain receipts have no provider ID. At the same
                # instant they must precede every known provider submission.
                return (item['elapsedMs'], int(sid) if sid.isdecimal() else -1, item.get('operationId', ''))

            blocked, waiting, items = set(), [], []
            pending_count, blocked_count = 0, 0
            for record in sorted(records, key=order):
                pid = str(record['problemId'])
                if record.get('state') == 'rejected':
                    continue
                identity = {'problemId': pid, 'problemLabel': record.get('problemLabel'),
                            'elapsedMs': record['elapsedMs']}
                if record.get('id'):
                    identity['submissionId'] = str(record['id'])
                elif record.get('operationId'):
                    identity['operationId'] = record['operationId']
                unverified_time = record.get('timeSource') != 'provider-absolute'
                unresolved = (not record.get('id') or unverified_time or record.get('pending') is True
                              or record.get('verdict') not in FINAL_VERDICTS)
                if unresolved:
                    pending_count += 1
                    blocked.add(pid)
                    reason = ('receipt-unknown' if not record.get('id') else
                              'time-unverified' if unverified_time else 'judgement-pending')
                    waiting.append({**identity, 'reason': reason})
                elif pid in blocked:
                    blocked_count += 1
                    waiting.append({**identity, 'reason': 'earlier-pending'})
                elif session.get('ranklandUrl') and str(record['id']) in by_id:
                    item = dict(by_id[str(record['id'])])
                    # Session membership may change when the user ends early,
                    # without changing the provider fact or its revision.
                    item.pop('withdrawn', None)
                    items.append(item)
            # This token describes desired content, not delivery bookkeeping.
            # In particular, resolving an unknown receipt can release a final
            # record without changing that provider fact's revision.
            token_value = {'target': session.get('ranklandUrl'), 'startAt': session.get('startAt'),
                           'durationMs': session_duration(session), 'waiting': waiting,
                           'items': [[item['sourceId'], item['revision']] for item in items],
                           'sources': [{key: item.get(key) for key in
                               ('sourceId', 'revision', 'elapsedMs', 'verdict', 'rawVerdict', 'problemId', 'problemLabel')}
                               for item in sorted(queued, key=lambda row: row['sourceId'])]}
            token = hashlib.sha256(json.dumps(token_value, sort_keys=True, separators=(',', ':'),
                                               allow_nan=False).encode()).hexdigest()
            return {'sessionId': session_id, 'items': items, 'waiting': waiting, 'allItems': queued,
                    'pendingCount': pending_count, 'blockedCount': blocked_count, 'planToken': token}

    def mark_history_refresh(self, session_id, started_at, *, complete):
        with self.transaction():
            session = self.session(session_id)
            if started_at >= session.get('lastHistoryRefreshAt', 0):
                session['lastHistoryRefreshAt'] = started_at
                session['lastHistoryRefreshComplete'] = complete
            if complete:
                session['lastHistoryCompleteAt'] = max(started_at, session.get('lastHistoryCompleteAt', 0))
            self.save_session(session)

    def settlement_sessions(self, now):
        """Judge polling eligibility without an external board/export dependency."""
        result = []
        for session in self.sessions():
            start = session.get('startAt')
            if session['state'] not in {'running', 'finished'} or start is None or start > now:
                continue
            end = start + session_duration(session)
            pending = sum(1 for row in self.submissions(session['sessionId'])
                          if row.get('inSession') and row.get('state') != 'rejected'
                          and (not row.get('id') or row.get('timeSource') != 'provider-absolute'
                               or row.get('pending') is True or row.get('verdict') not in FINAL_VERDICTS))
            if (now < end or pending or session.get('lastHistoryCompleteAt', 0) < end
                    or session.get('lastHistoryRefreshComplete') is False
                    or session.get('lastHistoryRefreshAt', 0) > session.get('lastHistoryCompleteAt', 0)):
                result.append({**session, 'refreshRequired': True, 'pendingCount': pending})
        return result

    def refresh_sessions(self, now):
        """Poll started sessions through settlement, independently of tabs."""
        result = []
        for session in self.sessions():
            start = session.get('startAt')
            if session['state'] not in {'running', 'finished'} or start is None or start > now:
                continue
            end = start + session_duration(session)
            plan = self.rankland_plan(session['sessionId'])
            refresh = (now < end or plan['pendingCount'] > 0
                       or session.get('lastHistoryCompleteAt', 0) < end
                       or session.get('lastHistoryRefreshComplete') is False
                       or session.get('lastHistoryRefreshAt', 0) > session.get('lastHistoryCompleteAt', 0))
            synchronize = bool(session.get('ranklandUrl') and
                               (session.get('ranklandSyncedPlanToken') != plan['planToken']
                                or any(item['state'] != 'synced' for item in plan['allItems'])))
            if refresh or synchronize:
                result.append({**session, 'refreshRequired': refresh, 'syncRequired': synchronize,
                               'pendingCount': plan['pendingCount']})
        return result

    def ack(self, session_id, args):
        if args.get('state') not in {'synced', 'ambiguous', 'failed'}:
            raise ValueError('Unknown outbox acknowledgement state')
        with self.transaction() if not self.db.in_transaction else nullcontext():
            row = self.db.execute('SELECT * FROM rankland_queue WHERE queue_id=? AND session_id=?',
                                  (args.get('queueId'), session_id)).fetchone()
            if row is None:
                raise KeyError('Unknown outbox item')
            if row['revision'] != args.get('revision'):
                return {'accepted': False, 'reason': 'stale-revision'}
            value = json.loads(row['record_json'])
            # Only structured non-secret receipt metadata is retained.
            receipt = args.get('receipt')
            if isinstance(receipt, dict):
                value['receipt'] = {k: receipt[k] for k in ('targetKey', 'problemIndex', 'timeMs', 'result', 'observedAt')
                                    if k in receipt and isinstance(receipt[k], (str, int, float, bool, type(None)))}
            if args.get('error'):
                value['syncError'] = str(args['error'])[:300]
            elif args['state'] == 'synced':
                value.pop('syncError', None)
            self.db.execute('UPDATE rankland_queue SET state=?,attempts=attempts+1,record_json=? WHERE queue_id=?',
                            (args['state'], json.dumps(value), args['queueId']))
        return {'accepted': True, 'queueId': args['queueId'], 'state': args['state']}

    def ack_batch(self, session_id, acknowledgements, *, plan_token=None):
        """Acknowledge one applied projection atomically in one helper task."""
        if not isinstance(acknowledgements, list) or len(acknowledgements) > 10000:
            raise ValueError('Expected at most 10000 outbox acknowledgements')
        if plan_token is not None and (not isinstance(plan_token, str) or len(plan_token) != 64
                                      or any(char not in '0123456789abcdef' for char in plan_token)):
            raise ValueError('Invalid RankLand plan token')
        seen = set()
        for item in acknowledgements:
            if (not isinstance(item, dict) or not isinstance(item.get('queueId'), str) or not item['queueId']
                    or type(item.get('revision')) is not int or item['revision'] < 1
                    or item.get('state') not in {'synced', 'ambiguous', 'failed'}):
                raise ValueError('Invalid outbox acknowledgement')
            if item['queueId'] in seen:
                raise ValueError('A queue item cannot occur twice in one acknowledgement batch')
            seen.add(item['queueId'])
        with self.transaction():
            session = self.session(session_id)
            if plan_token is not None:
                current = self.rankland_plan(session_id)
                if current['planToken'] != plan_token:
                    return {'accepted': False, 'reason': 'stale-plan', 'results': []}
                if seen != {item['queueId'] for item in current['allItems']}:
                    raise ValueError('A projection acknowledgement must cover every planned queue item')
            stale = set()
            for item in acknowledgements:
                row = self.db.execute('SELECT revision FROM rankland_queue WHERE queue_id=? AND session_id=?',
                                      (item['queueId'], session_id)).fetchone()
                if row is None:
                    raise KeyError('Unknown outbox item')
                if row['revision'] != item['revision']:
                    stale.add(item['queueId'])
            if stale:
                return {'accepted': False, 'reason': 'stale-revision', 'results': [
                    {'accepted': False, 'queueId': item['queueId'],
                     'reason': 'stale-revision' if item['queueId'] in stale else 'batch-stale'}
                    for item in acknowledgements]}
            results = [self.ack(session_id, item) for item in acknowledgements]
            if plan_token is not None and all(item['state'] == 'synced' for item in acknowledgements):
                session['ranklandSyncedPlanToken'] = plan_token
                self.save_session(session)
            return {'accepted': True, 'results': results}
