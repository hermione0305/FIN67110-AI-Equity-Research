from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from desk_verifier import marker, report_numbers
from quote_matching import quote_matches
import test_desk_verifier as fixtures
from test_desk_verifier import Replies, atom


class PresentationTests(unittest.TestCase):
    def test_live_hyphen_and_wrap_failures(self):
        self.assertTrue(quote_matches('e\u2011commerce and private\u2010label\nproducts',
                                      'e-commerce and private-label products'))
        self.assertTrue(quote_matches('spend $7,500 du ring fiscal 2027 .',
                                      'spend $7,500 during fiscal 2027.'))
        for quote in ['loss $120 million', 'profit $121 million', 'profit $120 billion',
                      'profit −120 million', 'profit $1 20 million']:
            self.assertFalse(quote_matches(quote,'profit $120 million'))

    def test_annotated_asc_identifier_is_not_a_financial_quantity(self):
        a=atom('450', identifier='A');b=atom('30',identifier='B')
        report='ASC 450'+marker(a)+'-30'+marker(b)+'; refunds $184.'
        entries=report_numbers(report)
        self.assertEqual([e['value'] for e in entries],['184'])
        self.assertEqual([e['value'] for e in report_numbers('ASC 450-30; refunds $184.')],['184'])
        actual='Accounting Standards Codification (ASC) 450'+marker(a)+'-30,'+marker({**b,'display':'30,'})+' refunds $184.'
        self.assertEqual([e['value'] for e in report_numbers(actual)],['184'])
        self.assertEqual([e['value'] for e in report_numbers('Loss -30 million.')],['-30'])


class BatchTests(unittest.TestCase):
    setUp=fixtures.VerifierTests.setUp
    tearDown=fixtures.VerifierTests.tearDown
    report=fixtures.VerifierTests.report
    run_verifier=fixtures.VerifierTests.run_verifier

    def test_every_claim_covered_once_and_saved(self):
        self.report([atom(identifier=f'N{i:05}') for i in range(25)])
        calls=Replies();result=self.run_verifier(calls)
        ids=[i for _,packet in calls.packets for i in packet['expected_output']['number_ids']]
        self.assertEqual(len(ids),25);self.assertEqual(len(set(ids)),25)
        self.assertEqual(result['batch_count'],3)
        self.assertTrue(result['semantic_completed'])
        self.assertEqual(len(list(self.folder.glob('verification_batch_*_input.json'))),3)
        self.assertEqual(len(list(self.folder.glob('verification_batch_*_output.json'))),3)

    def test_missing_batch_response_is_incomplete_not_code_success(self):
        self.report([atom(identifier=f'N{i:05}') for i in range(13)])
        calls=Replies(lambda packet:{'checks':[]})
        result=self.run_verifier(calls)
        self.assertFalse(result['semantic_completed']);self.assertEqual(result['status'],'failed')
        self.assertTrue(all(m['code_status']=='correct' and m['mark']=='unsupported' for m in result['marks']))

    def test_one_batch_failure_is_split_without_skipping_claims(self):
        self.report([atom(identifier=f'N{i:05}') for i in range(25)])
        calls=Replies(); original=calls.call
        def call(*args):
            if len(calls.packets)==1:
                calls.packets.append(('failed',deepcopy(args[1])))
                raise RuntimeError('test outage')
            return original(*args)
        calls.call=call
        result=self.run_verifier(calls)
        self.assertEqual(len(calls.packets),5)
        self.assertTrue(result['semantic_completed'])
        self.assertEqual(sum(m['mark']=='correct' for m in result['marks']),25)

    def test_changed_instructions_prevent_cached_approval(self):
        from desk_flow import copy_saved_run
        from desk_verifier import Verifier
        import contextlib,io
        self.report([atom()]);self.run_verifier()
        with tempfile.TemporaryDirectory() as parent:
            copied=copy_saved_run(self.folder,Path(parent))
            cached=next((copied/'semantic_cache').glob('*_input.json'))
            data=json.loads(cached.read_text());data['instructions']='Different instructions'
            cached.write_text(json.dumps(data))
            calls=Replies()
            with contextlib.redirect_stdout(io.StringIO()): result=Verifier(copied,calls).run()
            self.assertEqual(calls.counts,{'Verifier':1})
            self.assertTrue(result['semantic_completed'])
