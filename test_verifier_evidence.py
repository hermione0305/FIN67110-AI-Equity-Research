"""Context-limit regressions without model calls or changing verification truth."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx
from openai import BadRequestError

from desk_verifier import marker,report_numbers
from purdue_api import request_budget,request_parameters
from research_roles import RESEARCH,PARTS,analyst_schema
from team_runtime import SingleCalls
from verifier_evidence import select_evidence,compact_facts,expand_facts,compact_report,expand_report
from test_desk_flow import Provider,Response
import test_desk_flow as fixtures


class EvidenceTests(unittest.TestCase):
    def test_cited_lines_original_numbers_periods_and_alternative_definitions_are_kept(self):
        lines=['Unrelated background.' for _ in range(1500)]
        lines[490]='| Three months ended | 2026 | 2025 | (millions)'
        lines[500]='Operating income | 24 | 20'
        lines[1300]='Adjusted operating income excludes restructuring expenses and is a non-GAAP measure.'
        source={'kind':'line','document':'10-K','line':501,'quote':lines[500],'filing':'annual'}
        entries=[{'id':'N1','kind':'number','value':'24','source':source,'claim':'Operating income','definition':'GAAP operating income'}]
        excerpts,manifest=select_evidence({'10-K':'\n'.join(lines)},entries,{'10-K':'annual'})
        self.assertIn('L501: '+lines[500],excerpts['10-K'])
        self.assertIn('L491: '+lines[490],excerpts['10-K'])
        self.assertIn('L1301: '+lines[1300],excerpts['10-K'])
        self.assertEqual(manifest['number_ids'],['N1'])
        self.assertTrue(manifest['code_checks_use_full_saved_files'])
        self.assertLess(manifest['documents']['10-K']['selected_lines'],100)

    def test_explicit_quarter_citation_is_never_omitted(self):
        quote='Total revenue | 120 | 100'
        entries=[{'id':'N1','source':{'kind':'line','document':'10-Q','line':1,'quote':quote,'filing':'quarter'},
                  'claim':'Quarter revenue','definition':'Total revenue'}]
        excerpts,manifest=select_evidence({'10-Q':quote},entries,{'10-Q':'quarter'})
        self.assertIn(quote,excerpts['10-Q'])
        self.assertEqual(manifest['documents']['10-Q']['cited_lines'],[1])

    def test_uncited_quarter_claim_keeps_quarter_correction_context(self):
        entries=[{'id':'N1','source':{'kind':'none'},'claim':'The latest quarter revenue was misstated.',
                  'definition':'Quarter total revenue','kind':'number'},
                 {'id':'N2','source':{'kind':'tag','filing':'annual','tag':'us-gaap:Revenues'},
                  'claim':'Annual revenue','kind':'number'}]
        text='\n'.join(['Unrelated background.']*1000+['Total revenue | 120 | 100'])
        excerpts,manifest=select_evidence({'10-Q':text},entries,{'10-Q':'quarter'})
        self.assertIn('Total revenue | 120 | 100',excerpts['10-Q'])
        self.assertFalse(manifest['documents']['10-Q']['uncited_quarter_not_used_for_annual_claims'])

    def test_fact_deduplication_round_trips_every_value_tag_and_definition(self):
        original={'facts.json':{'value':120,'tag':'us-gaap:Revenues','end':'2026-08-30'},
                  'verification_facts.json':{'definitions':{'a':{'quote':'The same exact definition.','selected':True},
                                                          'b':{'quote':'The same exact definition.','selected':False}}}}
        before=deepcopy(original)
        packed=compact_facts(original)
        self.assertEqual(expand_facts(packed),before)
        self.assertEqual(original,before)
        self.assertEqual(len(packed['_shared_definition_texts']),1)

    def test_report_compaction_retains_every_number_and_is_lossless(self):
        prose='The quoted amount is annual revenue, not net sales, for the stated fiscal year.'
        entries=[{'id':f'N{i}','kind':'number','display':str(i),'value':str(i),'source':{'kind':'none'},
                  'claim':prose,'definition':prose} for i in range(1,20)]
        report='Filings read: fixture\nRun time: fixture\n'+ '\n'.join(e['display']+marker(e) for e in entries)
        packed=compact_report(report)
        self.assertLess(len(json.dumps(packed)),len(json.dumps(report)))
        self.assertEqual(expand_report(packed),report)
        self.assertEqual([e['id'] for e in report_numbers(expand_report(packed))],[e['id'] for e in entries])

    def test_budget_includes_output_and_margin_not_just_input(self):
        body=request_parameters('gpt-oss:120b','instructions',{'task':'test','context':{},'expected_output':{}},analyst_schema([PARTS[0]]))
        budget=request_budget(body)
        self.assertTrue(budget['fits'])
        self.assertEqual(budget['context_window'],65536)
        self.assertGreater(budget['requested_output_tokens'],0)
        self.assertGreaterEqual(budget['safety_margin_tokens'],512)
        self.assertTrue(budget['schema_tokens_included'])

    def test_oversized_request_is_blocked_before_an_api_call(self):
        attempts=[]
        def create(**kwargs): attempts.append(kwargs); raise AssertionError('Must not send oversized requests.')
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with tempfile.TemporaryDirectory() as folder:
            calls=SingleCalls('fixture-key',Path(folder),client=client)
            packet={'task':'test','context':{'text':'unrelated words '*120000},'expected_output':{}}
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(RuntimeError):
                calls.call(RESEARCH,packet,analyst_schema([PARTS[0]]))
            output=json.loads((Path(folder)/'nodes/research_analyst_1_output.json').read_text())
            self.assertEqual(output['diagnostic']['stage'],'context_budget')
            self.assertFalse(json.loads((Path(folder)/'nodes/research_analyst_1_budget.json').read_text())['fits'])
        self.assertFalse(attempts)

    def test_purdue_detail_error_body_is_preserved_and_secret_redacted(self):
        key='private-fixture-key'
        detail="Input length (120188) exceeds model's maximum context length (65536). "+key
        def create(**kwargs):
            response=httpx.Response(400,request=httpx.Request('POST','https://genai.rcac.purdue.edu/api/chat/completions'))
            raise BadRequestError('Purdue rejection',response=response,body={'detail':detail})
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with tempfile.TemporaryDirectory() as folder:
            calls=SingleCalls(key,Path(folder),client=client)
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(RuntimeError):
                calls.call(RESEARCH,{'task':'test','context':{},'expected_output':{}},analyst_schema([PARTS[0]]))
            output=json.loads((Path(folder)/'nodes/research_analyst_1_output.json').read_text())
            self.assertIn('120188',output['diagnostic']['api_message'])
            self.assertEqual(output['diagnostic']['api_code'],'context_length_exceeded')
            self.assertTrue((Path(folder)/'nodes/research_analyst_1_http_error_response.json').exists())
            for file in Path(folder).rglob('*.json'): self.assertNotIn(key,file.read_text())


class RepairTests(unittest.TestCase):
    setUp=fixtures.FlowTests.setUp
    tearDown=fixtures.FlowTests.tearDown
    run_flow=fixtures.FlowTests.run_flow

    def test_empty_json_repair_cannot_erase_prior_claims(self):
        class EmptyRepair(Provider):
            research_calls=0
            def create(self,**kwargs):
                if 'You are the Research Analyst.' in kwargs['messages'][0]['content']:
                    self.research_calls+=1
                    if self.research_calls==2:
                        packet=json.loads(kwargs['messages'][1]['content'])
                        return Response({'parts':[{'title':title,'claims':[]} for title in packet['expected_output']['parts']],
                                         'metric_ids':[]})
                return super().create(**kwargs)
        flow,_,_=self.run_flow(EmptyRepair(repair=True))
        self.assertTrue(all(p['claims'] for p in flow.state.outputs[RESEARCH]['parts']))
        self.assertTrue((self.folder/'research_analyst_repair_failure.json').exists())
        error=json.loads((self.folder/'nodes/research_analyst_2_output.json').read_text())
        self.assertEqual(error['diagnostic']['stage'],'schema_validation')
        self.assertEqual(flow.state.call_counts[RESEARCH],2)

    def test_concise_supported_repair_can_replace_a_longer_draft(self):
        class ConciseRepair(Provider):
            research_calls=0
            def create(self,**kwargs):
                response=super().create(**kwargs)
                if 'You are the Research Analyst.' in kwargs['messages'][0]['content']:
                    self.research_calls+=1
                    if self.research_calls==1:
                        output=json.loads(response.choices[0].message.content)
                        for part in output['parts']: part['claims']*=2
                        return Response(output)
                return response
        flow,_,_=self.run_flow(ConciseRepair(repair=True))
        part=next(p for p in flow.state.outputs[RESEARCH]['parts'] if p['title']==PARTS[1])
        self.assertEqual(len(part['claims']),1)


if __name__=='__main__':unittest.main()
