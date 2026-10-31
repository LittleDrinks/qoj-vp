#!/usr/bin/env python3
"""Read only safe acceptance facts from the real workbench ledger."""
import json
from pathlib import Path
import sqlite3
import time

root = Path(__file__).resolve().parents[1]
out = root / 'results/live-session'
result = {'observedAt': time.time(), 'databaseOpenedReadOnly': True,
          'sessions': [], 'operations': [], 'submissions': [], 'queue': []}
database = Path.home() / '.local/share/qoj-vp/vp.sqlite3'
with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    result['quickCheck'] = db.execute('PRAGMA quick_check').fetchone()[0]
    for row in db.execute('SELECT record_json FROM sessions'):
        session = json.loads(row[0])
        if session.get('contestId') != '1051':
            continue
        result['sessions'].append(session)
        sid = session['sessionId']
        for item in db.execute('SELECT state,record_json FROM operations WHERE session_id=?', (sid,)):
            value = json.loads(item['record_json'])
            result['operations'].append({'state': item['state'], **{key: value.get(key) for key in
                ('operationId', 'sessionId', 'id', 'url', 'account', 'filename', 'sourceSha256',
                 'language', 'problemId', 'problemLabel', 'submittedAt', 'receiptTransport', 'httpStatus')}})
        for item in db.execute('''SELECT s.record_json FROM submissions s JOIN session_submissions ss
                ON s.account=ss.account AND s.submission_id=ss.submission_id WHERE ss.session_id=?''', (sid,)):
            value = json.loads(item[0])
            result['submissions'].append({key: value.get(key) for key in
                ('id', 'url', 'account', 'problemId', 'problemLabel', 'language', 'submittedAt',
                 'timeSource', 'verdict', 'rawVerdict', 'score', 'pending', 'revision')})
        for item in db.execute('SELECT state,attempts,record_json FROM rankland_queue WHERE session_id=?', (sid,)):
            value = json.loads(item['record_json'])
            result['queue'].append({'state': item['state'], 'attempts': item['attempts'],
                **{key: value.get(key) for key in
                   ('sessionId', 'submissionId', 'problemId', 'problemLabel', 'elapsedMs',
                    'verdict', 'rawVerdict', 'receipt', 'error')}})
result['ordinaryFirefoxPid12358Alive'] = Path('/proc/12358').exists()
out.mkdir(parents=True, exist_ok=True)
(out / 'ledger-state.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
