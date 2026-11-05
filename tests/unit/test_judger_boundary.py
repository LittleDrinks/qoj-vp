from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qojvp import Application, ApplicationError
from qojvp.board_config import board_settings

ROOT=Path(__file__).resolve().parents[2]

class JudgerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=ROOT/'.scratch',prefix='judger-boundary-')
        self.addCleanup(self.directory.cleanup)
        self.app=Application(self.directory.name,clock=lambda:1000000)
        self.addCleanup(lambda:self.app.close())

    def test_provider_dispatch_is_selected_by_persisted_session_not_caller_override(self):
        class Adapter:
            def execute(self,action,args,exchange):return {'action':action,'exchange':exchange}
        self.app.judgers['synthetic']=Adapter()
        s=self.app.dispatch('create_session',{'judger':'synthetic','contestId':'7'})
        result=self.app.dispatch('judger.submissions',{'sessionId':s['sessionId'],'provider':'qoj'},exchange='fixture')
        self.assertEqual(result,{'action':'submissions','exchange':'fixture'})
        with self.assertRaises(ApplicationError) as cm:
            self.app.dispatch('judger.contest',{'provider':'missing'})
        self.assertEqual(cm.exception.code,'UNSUPPORTED_JUDGER')

    def test_board_rules_and_existing_session_survive_helper_restart(self):
        s=self.app.dispatch('create_session',{'contestId':'7','board':{'rule':'CCPC26','revealCount':40,'revealRatio':15}})
        self.app.close()
        self.app=Application(self.directory.name)
        snapshot=self.app.dispatch('session_snapshot',{'sessionId':s['sessionId']})
        self.assertEqual(snapshot['session']['board'],{'rule':'CCPC26','revealCount':40,'revealRatio':15})
        old=self.app.ledger.session(s['sessionId']);old.pop('judger');self.app.ledger.save_session(old)
        self.assertEqual(self.app.dispatch('inspect_session',{'sessionId':s['sessionId']})['judger'],'qoj')

    def test_cached_board_input_and_polling_never_call_judger_or_export_plan(self):
        s=self.app.dispatch('create_session',{'contestId':'7','account':'fixture','startAt':1,'durationMs':999999})
        with (patch.object(self.app.judgers['qoj'],'execute',side_effect=AssertionError('network')),
              patch.object(self.app.ledger,'rankland_plan',side_effect=AssertionError('external board'))):
            snapshot=self.app.dispatch('session_snapshot',{'sessionId':s['sessionId']})
            self.assertEqual(snapshot['history']['submissions'],[])
            self.assertEqual(len(self.app.dispatch('settlement_sessions')['sessions']),1)
            self.app.ledger.mark_history_refresh(s['sessionId'],1000000,complete=True)
            self.assertEqual(self.app.dispatch('settlement_sessions')['sessions'],[])

    def test_invalid_rules_do_not_modify_session(self):
        s=self.app.dispatch('create_session',{'contestId':'7','board':{'rule':'ICPC'}})
        for value in ({'rule':'unknown'},{'revealCount':True},{'revealRatio':float('nan')},{'revealCount':-1}):
            with self.subTest(value=value),self.assertRaises((ValueError,ApplicationError)):
                self.app.dispatch('update_session',{'sessionId':s['sessionId'],'board':value})
        self.assertEqual(self.app.dispatch('inspect_session',{'sessionId':s['sessionId']})['board'],board_settings({'rule':'ICPC'}))

    def test_board_rule_and_export_url_are_one_configuration(self):
        from urllib.parse import urlparse, parse_qs
        s=self.app.dispatch('create_session',{'contestId':'7',
            'ranklandUrl':'https://vp.xcpc.link/?contest=fixture&rule=CCPC26&count=50&ratio=20',
            'board':{'rule':'ICPC'}})
        self.assertEqual(parse_qs(urlparse(s['ranklandUrl']).query)['rule'], ['ICPC'])
        s=self.app.dispatch('update_session',{'sessionId':s['sessionId'],
            'board':{'rule':'CCPC26','revealCount':10,'revealRatio':25}})
        q=parse_qs(urlparse(s['ranklandUrl']).query)
        self.assertEqual((q['rule'],q['count'],q['ratio']), (['CCPC26'],['10'],['25']))
        s=self.app.dispatch('update_session',{'sessionId':s['sessionId'],'board':{'rule':'auto'}})
        q=parse_qs(urlparse(s['ranklandUrl']).query)
        self.assertNotIn('rule', q)
        self.assertNotIn('count', q)
        self.assertNotIn('ratio', q)
