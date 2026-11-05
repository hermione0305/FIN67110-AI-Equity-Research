"""Regression tests for live API rejection, SDK parsing and lost repair content."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx
from openai import OpenAI, RateLimitError

from research_roles import RESEARCH, PARTS, analyst_schema
from team_runtime import SingleCalls
from purdue_api import BASE_URL
import test_desk_flow as fixtures
from test_desk_flow import Provider


class ApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.packet={'task':'Return grounded research.','context':{},'expected_output':{'parts':[PARTS[0]]}}
        self.schema=analyst_schema([PARTS[0]])
        self.result={'parts':[{'title':PARTS[0],'claims':[{'text':'The issuer sells products.',
                     'evidence':[{'source_id':'10-K:L1','quote':'The issuer sells products.'}],'calculation_ids':[]}]}],
                     'metric_ids':[]}
    def tearDown(self): self.temp.cleanup()

    def client(self,text,status='completed'):
        requests=[]
        payload={'id':'chatcmpl_fixture','object':'chat.completion','created':1,'model':'gpt-oss:120b',
                 'choices':[{'index':0,'finish_reason':'stop' if status=='completed' else 'length',
                             'message':{'role':'assistant','content':text,'reasoning_content':'internal reasoning'}}]}
        def handle(request):
            requests.append(request)
            return httpx.Response(200,json=payload)
        http_client=httpx.Client(transport=httpx.MockTransport(handle))
        self.addCleanup(http_client.close)
        return OpenAI(api_key='fixture-key',base_url=BASE_URL,http_client=http_client,max_retries=0),requests

    def test_real_sdk_response_with_reasoning_before_text_is_parsed(self):
        client,requests=self.client(json.dumps(self.result))
        calls=SingleCalls('fixture-key',self.folder,client=client)
        self.assertEqual(calls.call(RESEARCH,self.packet,self.schema),self.result)
        self.assertEqual(len(requests),1)
        self.assertEqual(calls.outcomes[RESEARCH][0]['status'],'parsed')
        raw=json.loads((self.folder/'nodes/research_analyst_1_response.json').read_text())
        self.assertEqual(raw['choices'][0]['message']['reasoning_content'],'internal reasoning')
        self.assertEqual(raw['choices'][0]['message']['content'],json.dumps(self.result))
        self.assertEqual(str(requests[0].url),BASE_URL+'/chat/completions')

    def test_invalid_json_preserves_raw_response_and_reports_parse_stage(self):
        client,requests=self.client('not valid JSON')
        calls=SingleCalls('fixture-key',self.folder,client=client)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(RuntimeError):
            calls.call(RESEARCH,self.packet,self.schema)
        saved=json.loads((self.folder/'nodes/research_analyst_1_output.json').read_text())
        self.assertEqual(saved['diagnostic']['stage'],'json_parse')
        self.assertEqual(saved['diagnostic']['response_id'],'chatcmpl_fixture')
        self.assertTrue((self.folder/'nodes/research_analyst_1_response.json').exists())
        self.assertEqual(len(requests),1)

    def test_invalid_schema_and_incomplete_response_are_not_accepted(self):
        for text,status,stage in [('{}','completed','schema_validation'),(json.dumps(self.result),'incomplete','response_status')]:
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                client,requests=self.client(text,status)
                calls=SingleCalls('fixture-key',Path(directory),client=client)
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(RuntimeError):
                    calls.call(RESEARCH,self.packet,self.schema)
                saved=json.loads((Path(directory)/'nodes/research_analyst_1_output.json').read_text())
                self.assertEqual(saved['diagnostic']['stage'],stage)
                self.assertEqual(len(requests),1)

    def test_quota_error_is_distinguished_and_key_is_redacted(self):
        key='sk-fixture-secret'
        body={'error':{'code':'credit_balance_exhausted','type':'insufficient_quota',
                       'message':'No credits remain; secret '+key}}
        def create(**kwargs):
            response=httpx.Response(429,request=httpx.Request('POST','https://genai.rcac.purdue.edu/api/chat/completions'))
            raise RateLimitError('quota',response=response,body=body)
        calls=SingleCalls(key,self.folder,client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        capture=io.StringIO()
        with contextlib.redirect_stderr(capture),self.assertRaises(RuntimeError):
            calls.call(RESEARCH,self.packet,self.schema)
        saved=json.loads((self.folder/'nodes/research_analyst_1_output.json').read_text())
        self.assertEqual(saved['diagnostic']['stage'],'api_request')
        self.assertEqual(saved['diagnostic']['api_code'],'credit_balance_exhausted')
        self.assertEqual(saved['diagnostic']['http_status'],429)
        self.assertIn('Check Purdue account access',saved['diagnostic']['action'])
        self.assertNotIn(key,capture.getvalue())
        for file in self.folder.rglob('*.json'): self.assertNotIn(key,file.read_text())
        self.assertFalse((self.folder/'nodes/research_analyst_1_response.json').exists())


class FailureFlowTests(unittest.TestCase):
    setUp = fixtures.FlowTests.setUp
    tearDown = fixtures.FlowTests.tearDown
    run_flow = fixtures.FlowTests.run_flow
    # Use the same real Flow fixture, adding cases for the previously silent failures.
    def test_failed_repair_retains_successful_analyst_content(self):
        class RepairFailure(Provider):
            research_calls=0
            def create(self,**kwargs):
                if 'You are the Research Analyst.' in kwargs['messages'][0]['content']:
                    self.research_calls+=1
                    if self.research_calls==2: raise RuntimeError('repair outage')
                return super().create(**kwargs)
        with contextlib.redirect_stderr(io.StringIO()):
            flow,provider,_=self.run_flow(RepairFailure(repair=True))
        self.assertTrue(flow.state.outputs[RESEARCH]['parts'])
        self.assertEqual(len(flow.state.outputs[RESEARCH]['parts']),3)
        failure=json.loads((self.folder/'research_analyst_repair_failure.json').read_text())
        self.assertTrue(failure['prior_content_retained'])
        self.assertIn('subscription model',(self.folder/'report.md').read_text())

    def test_all_model_calls_rejected_is_failed_not_successful_empty_report(self):
        class Quota(Provider):
            def create(self,**kwargs):
                response=httpx.Response(429,request=httpx.Request('POST','https://genai.rcac.purdue.edu/api/chat/completions'))
                raise RateLimitError('quota',response=response,body={'code':'credit_balance_exhausted',
                    'type':'insufficient_quota','message':'No credits remaining.'})
        with contextlib.redirect_stderr(io.StringIO()): flow,_,_=self.run_flow(Quota())
        summary=json.loads((self.folder/'run_status.json').read_text())
        self.assertEqual(summary['status'],'failed')
        self.assertEqual(summary['number_count'],0)
        self.assertFalse(any(summary['analyst_claims_by_section'].values()))
        self.assertEqual(flow.state.node_order[-1],'Verifier')
        self.assertIn('FAILED — no analyst content was generated',(self.folder/'report.md').read_text())
        self.assertIn('failure record, not a completed equity-research report',(self.folder/'verified_report.md').read_text())
        self.assertNotIn('**Hold**',(self.folder/'report.md').read_text())
        self.assertEqual(summary['model_calls']['Research Analyst'][0]['diagnostic']['api_code'],'credit_balance_exhausted')


if __name__=='__main__': unittest.main()
