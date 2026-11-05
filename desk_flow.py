"""Fixed CrewAI graph: steps -> research -> financial -> advisor -> manager -> verifier."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import re
import shutil
import sys
from typing import Any, ClassVar

from dotenv import dotenv_values
from pydantic import BaseModel, Field, PrivateAttr
from crewai.flow import Flow, listen, start

from equity_desk import Desk, ROOT, SecClient, save_json
from research_roles import ADVISOR, FINANCIAL, MANAGER, RESEARCH, PARTS
from team_runtime import Coordinator, SingleCalls, audit, prepare_bundle, tools_for, unique_folder
from desk_verifier import Verifier


class TeamState(BaseModel):
    ticker: str = ''
    peers: list[str] = Field(default_factory=list)
    price: float | None = None
    folder: str = ''
    outputs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    node_order: list[str] = Field(default_factory=list)
    report: str = ''
    verified_report: str = ''
    call_counts: dict[str, int] = Field(default_factory=dict)


class Runtime:
    """Private services; credentials never enter Flow state or a model packet."""
    def __init__(self, key, sec_client=None, calls_factory=None, desk_factory=None):
        self.key, self.sec_client = key, sec_client
        self.calls_factory = calls_factory or (lambda folder: SingleCalls(key, folder))
        self.desk_factory = desk_factory or (lambda args: Desk(self.sec_client, args))
        self.desk = self.calls = self.coordinator = None

    def steps(self, state):
        print('Steps', flush=True)
        state.node_order.append('Steps')
        args = argparse.Namespace(ticker=state.ticker,peers=state.peers,price=state.price,step=None)
        self.desk = self.desk_factory(args)
        results = []
        for tool in tools_for(self.desk):
            print(f'Step {tool.step}: {tool.description}', flush=True)
            result = tool.run()
            results.append(result)
            if result['stdout']:
                print(result['stdout'],end='',flush=True)
            if result['error']:
                state.errors.append('Step '+str(tool.step)+': '+result['error'])
            # Resolve the company before selecting the unique directory name.
            if not state.folder:
                try:
                    folder = self.desk.folder()
                except Exception:
                    folder, stamp = unique_folder(state.ticker+'_unresolved')
                    self.desk._folder, self.desk.stamp = folder, stamp
                state.folder = str(folder)
                audit(folder,'steps_input',{'task':'Run the seven SEC data tools in order.',
                       'context':{'ticker':state.ticker,'peers':state.peers,'price':state.price},
                       'expected_output':'Saved filing texts, facts, ratios, release lines and peer facts.'})
            audit(state.folder,f'step_{tool.step}_input',{'tool':tool.name,'arguments':{},
                  'ticker':state.ticker,'peers':state.peers,'price':state.price})
            audit(state.folder,f'step_{tool.step}_output',result)
        bundle = prepare_bundle(self.desk, state.errors)
        self.calls = self.calls_factory(Path(state.folder))
        self.coordinator = Coordinator(self.desk,bundle,self.calls,state.errors)
        output = {'tools':results,'source_groups':{name:len(ids) for name,ids in bundle.groups.items()},
                  'errors':list(state.errors)}
        audit(state.folder,'steps_output',output)
        state.outputs['Steps'] = {'errors':list(state.errors),'source_groups':output['source_groups']}

    def analyst(self, role, state):
        print(role, flush=True)
        state.node_order.append(role)
        state.outputs[role] = deepcopy(self.coordinator.visit(role))
        state.call_counts = dict(self.calls.counts)

    def manager(self, state):
        print(MANAGER, flush=True)
        state.node_order.append(MANAGER)
        try:
            state.report = self.coordinator.manage()
        except Exception as exc:
            state.errors.append('Manager compilation failed: '+type(exc).__name__)
            path = Path(state.folder)/'report.md'
            if not path.exists():
                lines = ['Filings read: unavailable — see saved facts and node errors',
                         'Run time: '+self.desk.stamp, '', '# Equity Research Report', '',
                         'DRAFT — manager compilation failed.']
                for part in PARTS:
                    lines.extend(['','## '+part,'','Evidence could not be compiled.'])
                with path.open('x',encoding='utf-8') as stream: stream.write('\n'.join(lines)+'\n')
            state.report = str(path)
        state.outputs[MANAGER] = {'report':state.report,'errors':list(state.errors)}
        for role in (RESEARCH,FINANCIAL,ADVISOR):
            state.outputs[role] = deepcopy(self.coordinator.outputs[role])
        state.call_counts = dict(self.calls.counts)

    def verifier(self, state):
        state.node_order.append('Verifier')
        result = Verifier(state.folder,self.calls).run()
        state.verified_report = result['path']
        state.outputs['Verifier'] = result
        state.call_counts = dict(self.calls.counts)
        review_path = Path(state.folder)/'review_final.json'
        review = json.loads(review_path.read_text()) if review_path.exists() else {}
        counts = {part:sum(len(p.get('claims',[])) for p in self.coordinator.outputs[owner].get('parts',[])
                          if p.get('title')==part)
                  for part,owner in ((PARTS[0],RESEARCH),(PARTS[1],RESEARCH),(PARTS[2],FINANCIAL),(PARTS[3],RESEARCH))}
        status = ('failed' if state.errors or result['status']=='failed' or not all(counts.values()) else
                  'needs_review' if any(review.values()) or result['status']=='needs_review' else 'passed')
        summary = {'status':status,'analyst_claims_by_section':counts,'number_count':result['number_count'],
                   'semantic_completed':result['semantic_completed'],'semantic_batch_count':result['batch_count'],
                   'unresolved_numbers':result['unresolved_count'],'errors':list(state.errors),
                   'model_calls':getattr(self.calls,'outcomes',{}),'report':state.report,
                   'verified_report':state.verified_report}
        save_json(Path(state.folder)/'run_status.json',summary)
        state.outputs['Run Status'] = summary
        audit(state.folder,'flow_output',state.model_dump())
        print('Run status: '+status.upper()+(' — no successful report is available.' if status=='failed' else ''),flush=True)
        print('Run folder: '+state.folder,flush=True)
        return state.verified_report


class EquityTeamFlow(Flow[TeamState]):
    """No routers, hierarchical process, delegation, model tools, or optional verifier."""
    _runtime: Any = PrivateAttr(default=None)
    # CrewAI 1.15.34 auto-creates persistent Memory unless this supported
    # runtime flag is set. This graph must have no implicit memory/context.
    _skip_auto_memory: ClassVar[bool] = True

    def __init__(self, runtime, **kwargs):
        super().__init__(tracing=False, suppress_flow_events=True, **kwargs)
        self._runtime = runtime

    @start()
    def steps(self):
        self._runtime.steps(self.state)

    @listen(steps)
    def research_analyst(self):
        self._runtime.analyst(RESEARCH,self.state)

    @listen(research_analyst)
    def financial_analyst(self):
        self._runtime.analyst(FINANCIAL,self.state)

    @listen(financial_analyst)
    def investment_advisor(self):
        self._runtime.analyst(ADVISOR,self.state)

    @listen(investment_advisor)
    def strategy_manager(self):
        self._runtime.manager(self.state)

    @listen(strategy_manager)
    def verifier(self):
        return self._runtime.verifier(self.state)


class VerificationState(BaseModel):
    folder: str = ''
    verified_report: str = ''
    semantic_error: str | None = None


class VerificationFlow(Flow[VerificationState]):
    """The verify-only graph has exactly one node and no SEC/data/analyst service."""
    _calls: Any = PrivateAttr(default=None)
    _skip_auto_memory: ClassVar[bool] = True

    def __init__(self, calls, **kwargs):
        super().__init__(tracing=False,suppress_flow_events=True,**kwargs)
        self._calls = calls

    @start()
    def verifier(self):
        result = Verifier(self.state.folder,self._calls).run()
        self.state.verified_report = result['path']
        self.state.semantic_error = result['semantic_error']
        save_json(Path(self.state.folder)/'run_status.json',
                  {'status':result['status'],'number_count':result['number_count'],
                   'semantic_completed':result['semantic_completed'],'semantic_batch_count':result['batch_count'],
                   'unresolved_numbers':result['unresolved_count'],'semantic_error':result['semantic_error'],
                   'model_calls':getattr(self._calls,'outcomes',{})})
        audit(self.state.folder,'flow_output',{'node_order':['Verifier'],'result':result,
                                             'call_counts':dict(self._calls.counts)})
        return result['path']


def copy_saved_run(source, parent=None):
    source = Path(source).expanduser().resolve()
    if not source.is_dir() or not (source/'report.md').is_file():
        raise ValueError('--verify-only must name a saved run folder containing report.md')
    company = re.split(r'_\d{4}-\d{2}-\d{2}_',source.name,maxsplit=1)[0]
    destination,stamp = unique_folder(company, parent)
    names = ['report.md','facts.json','peers.json','verification_facts.json','companyfacts_raw.json']
    names += [p.name for p in source.glob('peer_*_companyfacts_raw.json')]
    names += [p.name for p in source.glob('*.txt')]
    for name in dict.fromkeys(names):
        path = source/name
        if path.is_file(): shutil.copyfile(path,destination/name)
    # Only exact-packet, schema-valid completed responses can establish meaning.
    # Failed attempts are copied only to schedule smaller packets, never as proof.
    cache_pairs=list(source.glob('verification_batch_*_input.json'))
    cache_pairs+=list((source/'semantic_cache').glob('*_input.json'))
    for index,path in enumerate(cache_pairs,1):
        output=path.with_name(path.name.replace('_input.json','_output.json'))
        if not output.exists(): continue
        cache=destination/'semantic_cache';cache.mkdir(exist_ok=True)
        cached_input=json.loads(path.read_text())
        if 'instructions' not in cached_input:
            match=re.search(r'verification_batch_(\d+)_input',path.name)
            node=source/'nodes'/f'verifier_{int(match[1])}_input.json' if match else None
            if node is not None and node.exists():
                cached_input['instructions']=json.loads(node.read_text()).get('instructions')
        save_json(cache/f'cached_{index:03d}_input.json',cached_input)
        shutil.copyfile(output,cache/f'cached_{index:03d}_output.json')
    save_json(destination/'run.json',{'mode':'verify-only','source_run':str(source),'run_time':stamp})
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ticker',nargs='?')
    parser.add_argument('--peers',nargs='+',default=[],help='Space- or comma-separated tickers')
    parser.add_argument('--price',type=float,help='Positive USD price per share')
    parser.add_argument('--verify-only',type=Path,help='Verify a saved run in a new folder; run no other nodes')
    args = parser.parse_args(argv)
    if args.verify_only and (args.ticker or args.peers or args.price is not None):
        parser.error('--verify-only cannot be combined with ticker, --peers or --price')
    if not args.verify_only and not args.ticker:
        parser.error('Supply a ticker or --verify-only SAVED_RUN_FOLDER')
    if args.price is not None and (not math.isfinite(args.price) or args.price <= 0):
        parser.error('--price must be a finite positive number')
    config = dotenv_values(ROOT/'.env')
    key = (config.get('API_KEY') or '').strip()
    if not key or key=='paste-here': parser.error('Set API_KEY in .env')
    try:
        if args.verify_only:
            folder = copy_saved_run(args.verify_only)
            flow = VerificationFlow(SingleCalls(key,folder))
            flow.kickoff(inputs={'folder':str(folder)})
            print('Run folder: '+str(folder),flush=True)
            status = json.loads((folder/'run_status.json').read_text())['status']
            print('Run status: '+status.upper(),flush=True)
            return 0 if status=='passed' else 1
        ua = (config.get('SEC_USER_AGENT') or '').strip()
        if not ua or 'your-email@' in ua.lower() or not re.search(r'\S+@\S+\.\S+',ua):
            parser.error('Set SEC_USER_AGENT in .env to your name and real email')
        peers = list(dict.fromkeys(t.upper() for item in args.peers for t in item.split(',') if t))
        flow = EquityTeamFlow(Runtime(key,SecClient(ua)))
        flow.kickoff(inputs={'ticker':args.ticker.upper(),'peers':peers,'price':args.price})
        return 0 if flow.state.outputs['Run Status']['status']=='passed' else 1
    except Exception as exc:
        print('Desk run failed ('+type(exc).__name__+'). Inspect the saved node audit files.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
