"""Purdue endpoint isolation, model discovery and backend response compatibility."""
from copy import deepcopy
from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from purdue_api import (BASE_URL,CHAT_COMPLETIONS_ENDPOINT,MODELS_ENDPOINT,
                        account_models,check_client_origin,request_parameters,settings)
from research_roles import RESEARCH,PARTS,analyst_schema
from team_runtime import SingleCalls


class PurdueTests(unittest.TestCase):
    def test_exact_documented_urls(self):
        self.assertEqual(BASE_URL,'https://genai.rcac.purdue.edu/api')
        self.assertEqual(CHAT_COMPLETIONS_ENDPOINT,BASE_URL+'/chat/completions')
        self.assertEqual(MODELS_ENDPOINT,BASE_URL+'/models')

    def test_paid_provider_client_is_rejected_before_any_request(self):
        with OpenAI(api_key='fixture') as client:
            with self.assertRaises(ValueError): check_client_origin(client)
            with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):
                SingleCalls('fixture',Path(folder),client=client)

    def test_model_discovery_uses_purdue_models_endpoint(self):
        observed=[]
        def handle(request):
            observed.append(request)
            return httpx.Response(200,json={'data':[{'id':'gpt-oss:120b','object':'model'},
                                                     {'id':'qwen3:32b','object':'model'}]})
        with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
            with OpenAI(api_key='fixture',base_url=BASE_URL,http_client=http_client,max_retries=0) as client:
                self.assertEqual(account_models(client),['gpt-oss:120b','qwen3:32b'])
        self.assertEqual(len(observed),1)
        self.assertEqual(str(observed[0].url),MODELS_ENDPOINT)

    def test_schema_parameters_match_vllm_and_ollama_backends(self):
        schema=analyst_schema([PARTS[0]])
        packet={'task':'test','context':{},'expected_output':{}}
        vllm=request_parameters('gpt-oss:120b','instructions',packet,schema)
        self.assertEqual(vllm['response_format']['json_schema']['schema'],schema)
        self.assertNotIn('store',vllm)
        self.assertNotIn('max_output_tokens',vllm)
        self.assertEqual(json.loads(vllm['messages'][1]['content']),packet)
        with patch('purdue_api.settings',return_value=replace(settings(),backend='ollama')):
            ollama=request_parameters('qwen3:32b','instructions',packet,schema)
        self.assertEqual(ollama['extra_body'],{'format':schema})
        self.assertNotIn('response_format',ollama)

    def test_configuration_cannot_redirect_to_another_provider(self):
        config={'base_url':'https://example.invalid','chat_completions_endpoint':CHAT_COMPLETIONS_ENDPOINT,
                'models_endpoint':MODELS_ENDPOINT,'fallback_provider':None}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text(json.dumps(config))
            with patch('purdue_api.CONFIG_PATH',path),self.assertRaises(ValueError): settings()

    def failed_response(self,payload):
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(200,json=payload)
        http_client=httpx.Client(transport=httpx.MockTransport(handle));self.addCleanup(http_client.close)
        client=OpenAI(api_key='fixture',base_url=BASE_URL,http_client=http_client,max_retries=0)
        self.addCleanup(client.close)
        with tempfile.TemporaryDirectory() as folder:
            calls=SingleCalls('fixture',Path(folder),client=client)
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(RuntimeError):
                calls.call(RESEARCH,{'task':'test','context':{},'expected_output':{}},analyst_schema([PARTS[0]]))
            diagnostic=json.loads((Path(folder)/'nodes/research_analyst_1_output.json').read_text())['diagnostic']
            self.assertEqual(diagnostic['stage'],'response_status')
            self.assertEqual(calls.counts[RESEARCH],1)
        self.assertEqual(len(requests),1)
        self.assertEqual(str(requests[0].url),CHAT_COMPLETIONS_ENDPOINT)
        return diagnostic

    def test_null_response_is_handled_without_retry_or_provider_fallback(self):
        diagnostic=self.failed_response(None)
        self.assertEqual(diagnostic['api_code'],'null_response')

    def test_reasoning_only_text_is_not_treated_as_final_json(self):
        self.failed_response({'id':'chat_fixture','object':'chat.completion','created':1,'model':'gpt-oss:120b',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':None,
                'reasoning_content':'{"parts":[],"metric_ids":[]}'}}]})


if __name__=='__main__': unittest.main()
