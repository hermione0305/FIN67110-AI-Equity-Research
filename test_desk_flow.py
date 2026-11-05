"""Real CrewAI Flow + SDK boundary stubs; no SEC/model requests or .env reads."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desk_flow import EquityTeamFlow, VerificationFlow, Runtime, copy_saved_run, main
from desk_verifier import report_numbers
from equity_desk import save_json
from research_roles import RESEARCH, FINANCIAL, ADVISOR, MANAGER, PARTS
from team_runtime import SingleCalls, unique_folder
from test_research_roles import FixtureDesk


class ToolDesk(FixtureDesk):
    def step1(self): save_json(self.folder()/'company.json',self.company())
    def step2(self): save_json(self.folder()/'selected_filings.json',self.selections())
    def step3(self): print('Saved fixture filing texts.')
    def step4(self): save_json(self.folder()/'facts.json',self.facts())
    def step5(self): print('Fixture Python ratios are already saved.')
    def step6(self): print('Fixture quarter source lines are already saved.')
    def step7(self): print('Fixture peers are already saved.')


class Response:
    def __init__(self,value):
        self.id='fixture-response'
        self.model='gpt-oss:120b'
        self.choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(
            content=json.dumps(value),tool_calls=None,refusal=None))]


class Provider:
    def __init__(self,repair=False,broken_role=None):
        self.requests=[]
        self.repair=repair
        self.broken_role=broken_role
        self.manager_calls=0
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self,**kwargs):
        self.requests.append(deepcopy(kwargs))
        instructions=kwargs['messages'][0]['content']
        packet=json.loads(kwargs['messages'][1]['content'])
        if 'You are the Verifier' in instructions:
            return Response({'checks':[{'id':key,'status':'correct','reason':'Meaning and definition match.',
                'replacement':None,'ratio_replacement':None} for key in packet['expected_output']['number_ids']]})
        role=next(role for role in (RESEARCH,FINANCIAL,ADVISOR,MANAGER) if 'You are the '+role+'.' in instructions)
        if role==self.broken_role: raise RuntimeError('fixture outage')
        if role==MANAGER:
            self.manager_calls+=1
            return Response({'checks':[{'part':title,'passed':not(self.repair and self.manager_calls==1 and title==PARTS[1]),
                'issues':['Retain the execution-risk condition.'] if self.repair and self.manager_calls==1 and title==PARTS[1] else []} for title in PARTS]})
        if role==RESEARCH:
            self.assert_context(packet,{'business','mda','release'})
            source=next(s for s in packet['context']['business'] if 'subscription' in s['quote'])
            return Response({'parts':[{'title':title,'claims':[{'text':'The business uses a subscription model.',
                'evidence':[{'source_id':source['source_id'],'quote':source['quote']}],'calculation_ids':[]}]}
                for title in packet['expected_output']['parts']],'metric_ids':[]})
        if role==FINANCIAL:
            self.assert_context(packet,{'facts','ratios','quarter','peers','definitions','price'})
            source=next(s for s in packet['context']['ratios'] if s['source_id']=='ratio:subject:operating_margin_pct')
            return Response({'parts':[{'title':PARTS[2],'claims':[{'text':'The cited operating margin supports the profitability analysis.',
                'evidence':[{'source_id':source['source_id'],'quote':source['quote']}],
                'calculation_ids':[source['source_id']]}]}],'metric_ids':packet['expected_output']['required_metric_ids']})
        self.assert_context(packet,{'research_analyst','financial_analyst'})
        return Response({'thesis':'The cited business model and profitability support the thesis, subject to execution risk.',
            'recommendation':'Hold','deciding_metric_id':'ratio:subject:operating_margin_pct',
            'rationale':'The operating margin is the deciding measure; the evidence does not establish a price target.'})

    @staticmethod
    def assert_context(packet,expected):
        if set(packet)!= {'task','context','expected_output'} or set(packet['context'])!=expected:
            raise AssertionError('Unexpected state leaked into role context.')


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def run_flow(self,provider=None):
        provider=provider or Provider()
        def factory(args):
            desk=ToolDesk(self.folder); desk.args=args
            return desk
        runtime=Runtime('fixture-key',None,calls_factory=lambda folder:SingleCalls('fixture-key',folder,client=provider),desk_factory=factory)
        flow=EquityTeamFlow(runtime)
        with contextlib.redirect_stdout(io.StringIO()):
            result=flow.kickoff(inputs={'ticker':'TEST','peers':['PEER'],'price':60})
        return flow,provider,result

    def test_real_flow_has_fixed_order_no_router_and_mandatory_verifier(self):
        flow,provider,result=self.run_flow()
        self.assertEqual(flow.state.node_order,['Steps',RESEARCH,FINANCIAL,ADVISOR,MANAGER,'Verifier'])
        self.assertTrue(Path(result).is_file())
        self.assertIsNone(flow.memory)
        batches=flow.state.outputs['Verifier']['batch_count']
        self.assertEqual(flow.state.call_counts,{RESEARCH:1,FINANCIAL:1,ADVISOR:1,MANAGER:1,'Verifier':batches})
        self.assertEqual(len(provider.requests),4+batches)
        for request in provider.requests:
            self.assertNotIn('tools',request)
            self.assertNotIn('previous_response_id',request)
            self.assertNotIn('store',request)
            self.assertFalse(request['stream'])
            self.assertEqual(len(request['messages']),2)
            self.assertEqual(request['messages'][0]['role'],'system')
        self.assertEqual(set(flow._definition.methods),{'steps','research_analyst','financial_analyst','investment_advisor','strategy_manager','verifier'})

    def test_saved_inputs_outputs_report_header_and_every_tool(self):
        flow,_,_=self.run_flow()
        nodes=self.folder/'nodes'
        for stage in ['steps','research_analyst_1','financial_analyst_1','investment_advisor_1','strategy_manager_1','verifier_1']:
            self.assertTrue((nodes/(stage+'_input.json')).exists(),stage)
            self.assertTrue((nodes/(stage+'_output.json')).exists(),stage)
        for step in range(1,8):
            self.assertTrue((nodes/f'step_{step}_input.json').exists())
            self.assertTrue((nodes/f'step_{step}_output.json').exists())
        report=(self.folder/'report.md').read_text()
        verified=(self.folder/'verified_report.md').read_text()
        self.assertEqual(report.splitlines()[0],verified.splitlines()[0])
        self.assertTrue(verified.splitlines()[2].startswith('| ID |'))
        for title in PARTS: self.assertEqual(report.count('## '+title+'\n'),1)
        for path in nodes.glob('*.json'): self.assertNotIn('fixture-key',path.read_text())
        self.assertTrue(all(row['mark']=='correct' for row in flow.state.outputs['Verifier']['marks']))
        self.assertTrue((self.folder/'facts.json').exists())

    def test_repair_schedule_bounds_calls_and_refreshes_advisor_once(self):
        flow,provider,_=self.run_flow(Provider(repair=True))
        self.assertEqual(flow.state.node_order,['Steps',RESEARCH,FINANCIAL,ADVISOR,MANAGER,'Verifier'])
        self.assertEqual(flow.state.call_counts[RESEARCH],2)
        self.assertEqual(flow.state.call_counts[ADVISOR],2)
        self.assertEqual(flow.state.call_counts[MANAGER],2)
        self.assertEqual(flow.state.call_counts[FINANCIAL],1)
        self.assertEqual(flow.state.call_counts['Verifier'],flow.state.outputs['Verifier']['batch_count'])
        self.assertLessEqual(max(n for role,n in flow.state.call_counts.items() if role!='Verifier'),2)
        request=json.loads((self.folder/'nodes/research_analyst_2_input.json').read_text())
        self.assertEqual(request['packet']['expected_output']['parts'],[PARTS[1]])

    def test_verifier_still_runs_after_failed_role_and_failed_manager(self):
        flow,_,_=self.run_flow(Provider(broken_role=MANAGER))
        self.assertEqual(flow.state.node_order[-1],'Verifier')
        self.assertTrue((self.folder/'verified_report.md').exists())
        self.assertEqual(flow.state.call_counts[MANAGER],2)
        self.assertEqual(flow.state.call_counts['Verifier'],flow.state.outputs['Verifier']['batch_count'])

    def test_verify_only_copies_sources_and_never_changes_original(self):
        self.run_flow()
        original={p.relative_to(self.folder).as_posix():p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        with tempfile.TemporaryDirectory() as destination_parent:
            copied=copy_saved_run(self.folder,Path(destination_parent))
            provider=Provider(); calls=SingleCalls('fixture-key',copied,client=provider)
            with contextlib.redirect_stdout(io.StringIO()):
                VerificationFlow(calls).kickoff(inputs={'folder':str(copied)})
            batches=json.loads((copied/'verifier_output.json').read_text())['batches']
            self.assertEqual(calls.counts,{})
            self.assertEqual(len(provider.requests),0)
            self.assertTrue(all(row['cached_from'] for row in batches))
            self.assertFalse((copied/'research_analyst.json').exists())
            self.assertTrue((copied/'facts.json').exists())
            self.assertTrue((copied/'verified_report.md').exists())
            self.assertNotEqual(copied,self.folder)
        self.assertEqual(original,{p.relative_to(self.folder).as_posix():p.read_bytes() for p in self.folder.rglob('*') if p.is_file()})

    def test_unique_folders_never_reuse_an_earlier_directory(self):
        a,_=unique_folder('Fixture issuer',self.folder)
        b,_=unique_folder('Fixture issuer',self.folder)
        self.assertNotEqual(a,b)
        self.assertTrue(a.is_dir() and b.is_dir())

    def test_call_limit_is_checked_before_sdk_request(self):
        provider=Provider(); calls=SingleCalls('fixture-key',self.folder,client=provider)
        # Bound applies even when caller attempts to bypass graph services.
        calls.counts[RESEARCH]=2
        with self.assertRaises(RuntimeError): calls.call(RESEARCH,{}, {})
        self.assertFalse(provider.requests)

    def test_cli_has_no_skip_verifier_option(self):
        for flag in ('--data-only','--step','--no-verify','--skip-verifier'):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(['TEST',flag])

    def test_verify_only_cli_does_not_require_sec_user_agent_or_call_sec(self):
        self.run_flow()
        with tempfile.TemporaryDirectory() as destination_parent:
            original_copy=copy_saved_run
            provider=Provider()
            with patch('desk_flow.dotenv_values',return_value={'API_KEY':'fixture-key'}), \
                 patch('desk_flow.SecClient',side_effect=AssertionError('SEC must not run')), \
                 patch('desk_flow.copy_saved_run',side_effect=lambda path:original_copy(path,Path(destination_parent))), \
                 patch('desk_flow.SingleCalls',side_effect=lambda key,folder:SingleCalls(key,folder,client=provider)), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--verify-only',str(self.folder)]),0)
            self.assertEqual(len(provider.requests),0)  # Exact completed batches reused.


if __name__=='__main__': unittest.main()
