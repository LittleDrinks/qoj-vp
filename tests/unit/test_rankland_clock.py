"""Provider URL clocks must use QOJ's start, never the time RankLand opens."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from qojvp import Application, ApplicationError

ROOT = Path(__file__).resolve().parents[2]
START = 1800000000123


def query(session):
    return parse_qs(urlsplit(session['ranklandUrl']).query)


def replay_elapsed(session, now):
    """Current provider contract: from minutes + elapsed wall time since at."""
    q = query(session)
    at = datetime.fromisoformat(q['at'][0].replace('Z', '+00:00')).timestamp() * 1000
    anchor = datetime.fromisoformat(q.get('anchor', q['at'])[0].replace('Z', '+00:00')).timestamp() * 1000
    elapsed = float(q['from'][0]) * 60000
    if q['play'] == ['1'] and now >= at:
        elapsed += max(0, now - anchor) * float(q['speed'][0])
    return min(session['durationMs'], elapsed)


class RanklandWallClockTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='rankland-clock-')
        self.now = START
        self.app = Application(self.directory.name, clock=lambda: self.now)

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def create(self, **extra):
        return self.app.dispatch('create_session', {'contestId': '4613', 'account': 'SyntheticUser',
            'durationMs': 18000000, 'ranklandUrl': 'https://vp.xcpc.link/?contest=ccpc2026ladies', **extra})

    def action(self, name, session, **extra):
        return self.app.dispatch(name, {'sessionId': session['sessionId'], **extra})

    def test_late_open_and_restart_advance_once_from_qoj_start(self):
        session = self.create(startAt=START)
        self.now += 7200123
        opened = self.action('prepare_rankland', session)
        self.assertAlmostEqual(replay_elapsed(opened, self.now), 7200123, places=2)
        self.assertEqual(query(opened)['from'], ['0'])
        self.assertNotIn('run', query(opened))
        self.app.close()
        self.now += 600000
        self.app = Application(self.directory.name, clock=lambda: self.now)
        reopened = self.action('prepare_rankland', session)
        self.assertEqual(reopened['ranklandUrl'], opened['ranklandUrl'])
        self.assertAlmostEqual(replay_elapsed(reopened, self.now), 7800123, places=2)

    def test_prepared_link_does_not_reuse_someone_elses_clock(self):
        session = self.create(ranklandUrl='https://vp.xcpc.link/?contest=ccpc2026ladies&run=other&at=2026-11-01T09:00:00%2B08:00&anchor=2026-11-01T10:00:00%2B08:00&from=60&play=1&speed=5&team=My+Team&organization=School')
        q = query(session)
        self.assertNotIn('run', q)
        self.assertNotIn('at', q)
        self.assertNotIn('anchor', q)
        self.assertEqual((q['play'], q['from'], q['speed']), (['0'], ['0'], ['1']))
        self.assertEqual((q['team'], q['organization']), (['My Team'], ['School']))
        with self.assertRaises(ApplicationError) as error:
            self.action('prepare_rankland', session)
        self.assertEqual(error.exception.code, 'SESSION_NOT_RUNNING')
        started = self.action('start_session', session)
        self.assertEqual(query(started)['play'], ['1'])
        self.assertEqual(replay_elapsed(started, self.now), 0)

    def test_equivalent_timezone_link_preserves_saved_target_and_clock(self):
        session = self.create(startAt='2026-11-04T12:00:00+08:00')
        self.now = session['startAt'] + 60000
        opened = self.action('prepare_rankland', session)
        equivalent = self.action('update_session', session,
            ranklandUrl='https://vp.xcpc.link/?contest=ccpc2026ladies&at=2026-11-04T04:00:00Z&anchor=2026-11-04T04:01:00Z&from=1&play=1&speed=1')
        self.assertEqual(equivalent['ranklandUrl'], opened['ranklandUrl'])
        self.assertEqual(equivalent['ranklandPreparedAt'], opened['ranklandPreparedAt'])
        self.assertEqual(query(equivalent)['at'], ['2026-11-04T04:00:00.000Z'])
        self.assertAlmostEqual(replay_elapsed(equivalent, self.now), 60000, places=2)

    def test_legacy_offset_is_preserved_as_migration_evidence_not_added_to_new_clock(self):
        session = self.create(startAt=START)
        record = self.app.ledger.session(session['sessionId'])
        old = record['ranklandUrl'] + '&run=' + session['sessionId']
        old = old.replace('from=0', 'from=120')
        record.update(ranklandUrl=old, ranklandPrepared=True, ranklandPreparedAt=START + 7200000)
        self.app.ledger.save_session(record)
        self.now = START + 7800000
        opened = self.action('prepare_rankland', session)
        self.assertEqual(opened['ranklandLegacyUrl'], old)
        self.assertAlmostEqual(replay_elapsed(opened, self.now), 7800000, places=2)
        self.assertNotIn('run', query(opened))
        again = self.action('prepare_rankland', session)
        self.assertEqual(again['ranklandLegacyUrl'], old)
        self.assertEqual(again['ranklandUrl'], opened['ranklandUrl'])

    def test_first_open_after_end_replays_exact_end_without_resetting_start(self):
        session = self.create(startAt=START)
        self.now = START + 20000000
        opened = self.action('prepare_rankland', session)
        self.assertEqual(replay_elapsed(opened, self.now), 18000000)
        self.assertEqual(opened['startAt'], START)
        self.assertEqual(query(opened)['from'], ['0'])


if __name__ == '__main__':
    unittest.main()
