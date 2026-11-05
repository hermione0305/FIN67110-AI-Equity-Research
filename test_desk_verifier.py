"""Verifier truth tables: no credentials, SEC requests or model requests."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from equity_desk import extract_facts, save_json
from test_equity_desk import fixture
from desk_verifier import (SavedEvidence, Verifier, arithmetic, expression_value,
                           marker, report_numbers)


def source(tag='RevenueFromContractWithCustomerExcludingAssessedTax', end='2025-12-31', start='2025-01-01'):
    return {'kind':'tag','entity':'subject','tag':'us-gaap:'+tag,'period_start':start,
            'period_end':end,'filing':'0000000001-26-000001','unit':'USD'}


def atom(value='120', citation=None, identifier='N00001', **extra):
    return {'id':identifier,'kind':'number','value':value,'display':value,
            'source':citation if citation is not None else source(),'claim':'Revenue for the current fiscal year.',
            'definition':'Annual revenue',**extra}


class Replies:
    def __init__(self, responder=None):
        self.responder = responder
        self.packets = []
        self.counts = {}

    def call(self,role,packet,schema):
        self.counts[role] = self.counts.get(role,0)+1
        self.packets.append((role,deepcopy(packet)))
        if self.responder: return self.responder(packet)
        return {'checks':[{'id':key,'status':'correct','reason':'Meaning matches the saved filing.',
                           'replacement':None,'ratio_replacement':None} for key in packet['expected_output']['number_ids']]}


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        save_json(self.folder/'facts.json',extract_facts(fixture(),'0000000001'))
        save_json(self.folder/'verification_facts.json',{'user_price':60,'documents':{'release':'0000000001-26-000003'}})
        (self.folder/'release.txt').write_text('Quarter results\nTotal revenue was $120 million.\nDiluted EPS was ($1.00).\n')
        self.evidence = SavedEvidence(self.folder)

    def tearDown(self): self.temp.cleanup()

    def report(self,records,tail=''):
        text='Filings read: 10-K 0000000001-26-000001; Exhibit 99.1 0000000001-26-000003\nRun time: 2026-11-03\n\n'
        text+='\n'.join(row['display']+marker(row) for row in records)+'\n'+tail
        (self.folder/'report.md').write_text(text)
        return text

    def run_verifier(self,calls=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return Verifier(self.folder,calls or Replies()).run()

    def test_exact_tag_period_unit_and_accession(self):
        self.assertEqual(self.evidence.code_check(atom())[0],'correct')
        self.assertEqual(self.evidence.code_check(atom('120.0000000001'))[0],'wrong')
        for field,value in [('period_end','2024-12-31'),('period_start','2025-02-01'),('filing','not-the-filing'),('unit','shares')]:
            citation=source(); citation[field]=value
            self.assertEqual(self.evidence.code_check(atom(citation=citation))[0],'unsupported')

    def test_line_allows_spacing_and_accounting_negative(self):
        citation={'kind':'line','document':'release','line':2,'quote':'Total  revenue was $ 120 million.',
                  'filing':'0000000001-26-000003','period_end':'2025-12-31'}
        self.assertEqual(self.evidence.code_check(atom(citation=citation))[0],'correct')
        citation['line']=3; citation['quote']='Diluted EPS was ($1.00).'
        self.assertEqual(self.evidence.code_check(atom('-1',citation=citation))[0],'correct')
        self.assertEqual(self.evidence.code_check(atom('1',citation=citation))[0],'wrong')
        citation['quote']='Invented EPS of $99.'
        self.assertEqual(self.evidence.code_check(atom('99',citation=citation))[0],'unsupported')

    def ratio(self,value=None,definition='Operating income / annual revenue, in percent.'):
        inputs=[{'name':'a','value':'24','source':source('OperatingIncomeLoss')},
                {'name':'b','value':'120','source':source()}]
        actual,display=arithmetic('a / b * 100',inputs)
        if value is not None: display=display.rsplit('=',1)[0]+'= '+value
        return {'id':'R00001','kind':'ratio','value':value or actual,'display':display,
                'expression':'a / b * 100','inputs':inputs,'decimal_places':6,
                'definition':definition,'claim':'operating_margin_pct'}

    def test_ratio_recomputes_from_quoted_inputs_and_checks_inputs(self):
        record=self.ratio()
        self.assertEqual(self.evidence.code_check(record)[0],'correct')
        self.assertEqual(self.evidence.code_check(self.ratio('99'))[0],'wrong')
        record['inputs'][0]['value']='48'
        self.assertEqual(self.evidence.code_check(record)[0],'wrong')
        record['inputs'][0]['source']['tag']='us-gaap:Nonexistent'
        self.assertEqual(self.evidence.code_check(record)[0],'unsupported')
        self.assertEqual(self.evidence.code_check(self.ratio(definition=''))[0],'unsupported')

    def test_calculator_rejects_executable_expressions(self):
        for expression in ['__import__("os")','a.__class__','a ** 100','[a][0]']:
            with self.assertRaises(ValueError): expression_value(expression,{'a':'24'})

    def test_wrong_tag_number_corrected_with_real_tag(self):
        original=self.report([atom('999')])
        result=self.run_verifier()
        mark=result['marks'][0]
        self.assertEqual(mark['mark'],'wrong')
        self.assertEqual(mark['correction'],'120')
        text=(self.folder/'verified_report.md').read_text()
        self.assertEqual(text.splitlines()[0],original.splitlines()[0])
        self.assertTrue(text.splitlines()[2].startswith('| ID |'))
        self.assertIn('us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',text)
        self.assertIn('120 [source:',text)

    def test_seeded_eps_uses_exact_fact_and_real_line_not_malformed_model_value(self):
        facts=json.loads((self.folder/'facts.json').read_text())
        facts['concepts']['diluted_eps']['current']['val']=20.76
        save_json(self.folder/'facts.json',facts)
        real='Diluted | $ | 20.76 | | | $ | 18.21 | | | $ | 16.56 |'
        (self.folder/'10-K.txt').write_text('\n'*614+real+'\n')
        citation={**source('EarningsPerShareDiluted'),'unit':'USD/shares',
                  'document':'10-K','line':615,'quote':'Diluted | $ | 21.76'}
        self.report([atom('21.76',citation=citation,definition='Annual diluted EPS, USD per share')])
        proposed={**citation,'quote':'Diluted | $ | 20.76'}
        def respond(packet):
            return {'checks':[{'id':'N00001','status':'wrong','reason':'The filing states diluted EPS of 20.76.',
                    'replacement':{'value':'?? placeholder','source':proposed,'definition':'malformed'},
                    'ratio_replacement':None}]}
        result=self.run_verifier(Replies(respond));mark=result['marks'][0]
        self.assertEqual(mark['mark'],'wrong');self.assertEqual(mark['correction'],'20.76')
        self.assertEqual(mark['source']['quote'],real)
        self.assertIn('10-K:L615',(self.folder/'verified_report.md').read_text())
        self.assertIn(real,(self.folder/'verified_report.md').read_text())
        # A forged quote or conflicting period must still block this path.
        proposed['quote']='Diluted | $ | 99.99'
        (self.folder/'verified_report.md').unlink()
        result=self.run_verifier(Replies(respond))
        self.assertIsNone(result['marks'][0]['correction'])
        proposed['quote']='Diluted | $ | 20.76'
        proposed['period_end']='2024-12-31'
        (self.folder/'verified_report.md').unlink()
        result=self.run_verifier(Replies(respond))
        self.assertIsNone(result['marks'][0]['correction'])

    def test_wrong_ratio_corrected_in_code(self):
        self.report([self.ratio('99')])
        result=self.run_verifier()
        self.assertEqual(result['marks'][0]['mark'],'wrong')
        self.assertIn('24 / 120 * 100 = 20',result['marks'][0]['correction'])
        self.assertIn('OperatingIncomeLoss',(self.folder/'verified_report.md').read_text())

    def test_definition_missing_cannot_be_approved_by_model(self):
        self.report([self.ratio(definition='')])
        result=self.run_verifier()
        self.assertEqual(result['marks'][0]['mark'],'unsupported')
        self.assertIsNone(result['marks'][0]['correction'])

    def test_semantic_period_failure_overrides_exact_tag_match(self):
        self.report([atom()])
        replacement_source=source(end='2024-12-31',start='2024-01-01')
        def respond(packet):
            return {'checks':[{'id':'N00001','status':'wrong','reason':'Claim refers to prior year.',
                    'replacement':{'value':'100','source':replacement_source,'definition':'Prior annual revenue'},'ratio_replacement':None}]}
        result=self.run_verifier(Replies(respond))
        self.assertEqual(result['marks'][0]['mark'],'wrong')
        self.assertEqual(result['marks'][0]['correction'],'100')
        self.assertIn('2024-12-31',(self.folder/'verified_report.md').read_text())

    def test_uncited_number_is_unsupported_and_can_be_corrected_from_line(self):
        self.report([],tail='Quarter revenue was 999 million.\n')
        def respond(packet):
            return {'checks':[{'id':key,'status':'unsupported','reason':'No original source.',
                'replacement':{'value':'120','definition':'Quarter revenue','source':{
                'kind':'line','document':'release','line':2,'quote':'Total revenue was $120 million.',
                'filing':'0000000001-26-000003','period_end':'2025-12-31'}},'ratio_replacement':None}
                for key in packet['expected_output']['number_ids']]}
        result=self.run_verifier(Replies(respond))
        self.assertEqual(result['marks'][0]['mark'],'unsupported')
        self.assertEqual(result['marks'][0]['correction'],'120')
        self.assertIn('release:L2',(self.folder/'verified_report.md').read_text())

    def test_unprovable_replacement_is_not_published(self):
        self.report([atom('999',citation={})])
        def respond(packet):
            return {'checks':[{'id':'N00001','status':'unsupported','reason':'No evidence.',
                'replacement':{'value':'777','source':source(),'definition':'Annual revenue'},'ratio_replacement':None}]}
        result=self.run_verifier(Replies(respond))
        self.assertIsNone(result['marks'][0]['correction'])
        self.assertIn('unsupported: no provable correction',(self.folder/'verified_report.md').read_text())

    def test_only_thesis_is_skipped_deciding_number_is_checked(self):
        text=self.report([atom()],tail='<!-- advisor-thesis:start -->Thesis assumes 999.<!-- advisor-thesis:end -->\nDeciding number 77.\n')
        entries=report_numbers(text)
        self.assertEqual([e['value'] for e in entries],['120','77'])

    def test_verifier_context_contains_only_three_allowed_inputs(self):
        self.report([atom()])
        # These files must never enter verifier context.
        (self.folder/'research_analyst.json').write_text('{"secret_role_fact":"forbidden"}')
        (self.folder/'role_sources.json').write_text('{"untrusted_cache":"forbidden"}')
        calls=Replies(); self.run_verifier(calls)
        packet=calls.packets[0][1]
        self.assertEqual(set(packet['context']),{'report','filing_texts','facts'})
        self.assertNotIn('forbidden',json.dumps(packet))

    def test_model_outage_fails_closed_and_still_writes_verified_report(self):
        self.report([atom()])
        class Broken:
            def call(self,*args,**kwargs): raise RuntimeError('API unavailable')
        result=self.run_verifier(Broken())
        self.assertEqual(result['marks'][0]['mark'],'unsupported')
        self.assertTrue(Path(result['path']).exists())

    def test_rerun_refuses_to_overwrite_existing_verification(self):
        self.report([atom()]); self.run_verifier()
        before={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        with self.assertRaises(FileExistsError): self.run_verifier()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()})

    def test_ratio_correction_uses_named_formula_not_model_result(self):
        self.report([self.ratio(definition='')])
        def respond(packet):
            return {'checks':[{'id':'R00001','status':'unsupported','reason':'Definition was absent.',
                'replacement':None,'ratio_replacement':{'formula':'operating_margin_pct',
                'definition':'GAAP operating income / annual revenue, percent.','inputs':self.ratio()['inputs']}}]}
        result=self.run_verifier(Replies(respond))
        self.assertEqual(result['marks'][0]['mark'],'unsupported')
        self.assertEqual(result['marks'][0]['correction'],'24 / 120 * 100 = 20')

    def test_changed_visible_number_is_checked_instead_of_hidden_annotation(self):
        report=self.report([atom()])
        (self.folder/'report.md').write_text(report.replace('120<!-- number:','9999<!-- number:',1))
        result=self.run_verifier()
        self.assertEqual(result['marks'][0]['number'],'9999')
        self.assertEqual(result['marks'][0]['mark'],'wrong')
        self.assertEqual(result['marks'][0]['correction'],'120')

    def test_duplicate_ids_are_unsupported_for_both_occurrences(self):
        self.report([atom(),atom()])
        result=self.run_verifier()
        self.assertEqual([row['mark'] for row in result['marks']],['unsupported','unsupported'])

    def test_named_ratio_cannot_use_a_different_expression(self):
        record=self.ratio()
        record['expression']='a * b'
        self.assertEqual(self.evidence.code_check(record)[0],'unsupported')

    def test_explicit_older_fact_citation_is_read_without_trusting_amount(self):
        citation=('revenue = 120 USD; us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax; '
            'start=2025-01-01; end=2025-12-31; filing=0000000001-26-000001 '
            '[fact:subject:revenue:current; tag=us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax; '
            'period_start=2025-01-01; period_end=2025-12-31; filing=0000000001-26-000001]')
        self.report([],tail=citation)
        entries=report_numbers((self.folder/'report.md').read_text())
        self.assertEqual([e['value'] for e in entries],['120'])
        self.assertEqual(self.evidence.code_check(entries[0])[0],'correct')

    def test_adjacent_line_cannot_be_presented_as_the_cited_line(self):
        citation={'kind':'line','document':'release','line':1,'quote':'Total revenue was $120 million.',
                  'filing':'0000000001-26-000003','period_end':'2025-12-31'}
        self.assertEqual(self.evidence.code_check(atom(citation=citation))[0],'unsupported')


if __name__=='__main__': unittest.main()
