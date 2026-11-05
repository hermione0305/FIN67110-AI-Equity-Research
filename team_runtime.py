"""Fixed graph services. Models return content/checks, never graph transitions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import io
import contextlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from uuid import uuid4

from jsonschema import validate
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

from equity_desk import ROOT, STEPS, save_json
from research_roles import (ADVISOR, FINANCIAL, MANAGER, RESEARCH, PARTS, OWNERS,
                            CATALOGUE, EXTRA_RATIOS, SourceBundle, StrategyManager, check_claim)
from desk_verifier import NUMBER, arithmetic, dec, marker, numeric, source_label

from purdue_api import settings as provider_settings, client_for, check_client_origin, request_parameters, request_budget

ROLES = ROOT / 'roles'


def unique_folder(company, parent=None):
    parent = Path(parent or ROOT / 'research_data')
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S_%f%z')
    safe = re.sub(r'[^\w.-]+', '_', company).strip('._') or 'unresolved'
    while True:
        path = parent / f'{safe}_{stamp}_{uuid4().hex[:10]}'
        try:
            path.mkdir(exist_ok=False)
            return path, stamp
        except FileExistsError:
            continue


def audit(folder, name, value):
    path = Path(folder) / 'nodes'
    path.mkdir(exist_ok=True)
    with (path / (name + '.json')).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


class SingleCalls:
    """Exactly one SDK invocation per role visit; no hidden tool/reasoning loop."""
    def __init__(self, key, folder, client=None, model=None):
        if client is None:
            client = client_for(key)
        check_client_origin(client)
        self.client, self.folder, self.model = client, Path(folder), model or provider_settings().model
        self._secret = key
        self.counts = {}
        self.outcomes = {}

    def redact(self, value):
        if isinstance(value,dict): return {k:self.redact(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)): return [self.redact(v) for v in value]
        if isinstance(value,str):
            if self._secret: value=value.replace(self._secret,'[REDACTED]')
            return re.sub(r'\bsk-[A-Za-z0-9_-]+','[REDACTED]',value)
        return value

    def diagnostic(self, exc, stage, response=None):
        body = getattr(exc,'body',None)
        detail = body.get('error',body) if isinstance(body,dict) else {}
        if isinstance(detail,str): detail={'message':detail}
        detail = detail if isinstance(detail,dict) else {}
        text=detail.get('message') or detail.get('detail') or (body if isinstance(body,str) else '')
        if not isinstance(text,str): text=json.dumps(text)
        code,kind = detail.get('code'),detail.get('type')
        if not code and re.search(r'context length|input length',text,re.I): code='context_length_exceeded'
        quota = code in {'insufficient_quota','credit_balance_exhausted'} or kind=='insufficient_quota'
        result = {'stage':stage,'exception':type(exc).__name__,
                  'http_status':getattr(exc,'status_code',None),'api_code':code,'api_type':kind,
                  'api_message':text[:8000],
                  'request_id':getattr(exc,'request_id',None),
                  'response_id':getattr(response,'id',None),
                  'finish_reason':(response.choices[0].finish_reason if response is not None and getattr(response,'choices',None) else None),
                  'provider':'Purdue GenAI Studio', 'model':self.model,
                  'action':('Check Purdue account access or contact RCAC; no paid-provider fallback is allowed.'
                            if quota else 'Inspect the saved Purdue response and diagnostic; no automatic extra model call was made.')}
        if stage=='schema_validation':
            result['validation_path'] = list(getattr(exc,'absolute_path',[]))
            result['validation_message'] = str(getattr(exc,'message','Schema validation failed.'))[:1000]
        if stage=='response_status' and (response is None or (
                not getattr(response,'choices',None) and getattr(response,'id',None) is None)):
            result['api_code'] = 'null_response'
            result['action'] = 'Purdue returned JSON null, which may indicate throttling. Wait before a new run; this visit is not retried.'
        return self.redact(result)

    def call(self, role, packet, schema, calculator=None):
        count = self.counts.get(role, 0) + 1
        # Verifier batches are internal to its one mandatory graph node. Analyst
        # and Manager repair limits stay at two; each batch has one SDK request.
        if role != 'Verifier' and count > 2:
            raise RuntimeError('Role call bound exceeded: ' + role)
        self.counts[role] = count
        basename = role.lower().replace(' ', '_')
        instructions = (ROLES / (basename + '.md')).read_text(encoding='utf-8')
        name = f'{basename}_{count}'
        audit(self.folder, name + '_input', {'instructions_file':'roles/'+basename+'.md',
              'instructions':instructions,'packet':packet, 'schema':schema,
              'provider':'Purdue GenAI Studio','model':self.model,'backend':provider_settings().backend})
        response,stage = None,'context_budget'
        try:
            body=request_parameters(self.model,instructions,packet,schema)
            budget=request_budget(body)
            audit(self.folder,name+'_budget',budget)
            if not budget['fits']:
                raise RuntimeError('Request exceeds the deployed context budget; no claims or evidence may be silently dropped.')
            stage='api_request'
            response = self.client.chat.completions.create(**body)
            # Save the provider's actual Chat Completions response before parsing.
            raw = (response.model_dump(mode='json') if hasattr(response,'model_dump') else
                   {'id':getattr(response,'id',None),'choices':[
                       {'finish_reason':getattr(choice,'finish_reason',None),
                        'message':{'content':getattr(choice.message,'content',None)}}
                       for choice in getattr(response,'choices',[]) ]} if response is not None else None)
            audit(self.folder,name+'_response',self.redact(raw))
            stage = 'response_status'
            if response is None or not getattr(response,'choices',None):
                raise RuntimeError('Purdue returned null or no completion choices.')
            choice = response.choices[0]
            message = choice.message
            if (choice.finish_reason != 'stop' or getattr(message,'tool_calls',None)
                    or getattr(message,'refusal',None)):
                raise RuntimeError('Incomplete, refused, or disallowed tool-call completion.')
            if not isinstance(message.content,str) or not message.content.strip():
                raise RuntimeError('Purdue returned no final answer content; reasoning is not a substitute.')
            stage = 'json_parse'
            result = json.loads(message.content)
            stage = 'schema_validation'
            validate(result, schema)
            audit(self.folder, name + '_output', {'output':result,'response_id':response.id})
            self.outcomes.setdefault(role,[]).append({'status':'parsed','response_id':response.id})
            return result
        except Exception as exc:
            diagnostic = self.diagnostic(exc,stage,response)
            if getattr(exc,'body',None) is not None:
                audit(self.folder,name+'_http_error_response',self.redact({
                    'http_status':getattr(exc,'status_code',None),'body':getattr(exc,'body')}))
            code = diagnostic.get('api_code') or diagnostic.get('api_type')
            message = f'{role} failed at {stage} ({type(exc).__name__}' + (f'; {code}' if code else '') + '); no additional model call was made.'
            audit(self.folder, name + '_output', {'error':message,'diagnostic':diagnostic})
            self.outcomes.setdefault(role,[]).append({'status':'failed','diagnostic':diagnostic})
            print(message+' '+diagnostic['action'],file=sys.stderr,flush=True)
            raise RuntimeError(message) from None


class EmptyInput(BaseModel):
    pass


class DataStepTool(BaseTool):
    name: str
    description: str
    args_schema: type[BaseModel] = EmptyInput
    desk: object = Field(exclude=True, repr=False)
    step: int

    def _run(self):
        capture = io.StringIO()
        error = None
        with contextlib.redirect_stdout(capture):
            try:
                getattr(self.desk, f'step{self.step}')()
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
        return {'step':self.step, 'name':STEPS[self.step-1], 'error':error, 'stdout':capture.getvalue()}


def tools_for(desk):
    return [DataStepTool(name=f'step_{i}', description=description, desk=desk, step=i)
            for i, description in enumerate(STEPS, 1)]


def prepare_bundle(desk, errors):
    try:
        bundle = SourceBundle(desk)
        # Run all optional allowlisted calculations in code, not a model tool loop.
        for entity in bundle.entities:
            for period in ('current','prior'):
                for ratio in EXTRA_RATIOS:
                    bundle.calculator({'ratio':ratio,'entity':entity,'period':period})
        documents = {form: row['accessionNumber'] for form,row in desk.selections().items()}
        documents['earnings_release_99_1'] = desk.selections()['8-K']['accessionNumber']
        documents.update({row['document']:row['filing'] for row in bundle.additional_documents})
        save_json(desk.folder() / 'verification_facts.json', {'user_price':desk.args.price,
                  'documents':documents, 'definitions':{key:row for key,row in bundle.sources.items() if row['kind']=='definition'}})
        save_json(desk.folder() / 'role_sources.json', bundle.sources)
        return bundle
    except Exception as exc:
        errors.append('Source preparation: ' + type(exc).__name__ + ': ' + str(exc))
        return SimpleNamespace(sources={}, groups={g:[] for ids in CATALOGUE.values() for g in ids},
             entities={},required_metrics=[],additional_documents=[],context=lambda ids:{g:[] for g in ids})


class Coordinator(StrategyManager):
    """Reuse data validation; replace the former model-selected plan with fixed allocations."""
    def __init__(self, desk, bundle, calls, errors):
        self.desk, self.bundle, self.calls, self.errors = desk, bundle, calls, errors
        self.outputs = {}
        self.plan = {role:{'task':'Perform the assigned '+role+' analysis from these sources only.',
                     'context':groups,'expected_output':'Return grounded claims, source quotes, period and definition distinctions.'}
                     for role,groups in CATALOGUE.items()}

    def visit(self, role, titles=None, feedback=None):
        previous=deepcopy(self.outputs.get(role))
        try:
            self.analyst(role, titles, feedback)
            if feedback and previous is not None and role in (RESEARCH,FINANCIAL):
                allowed={key for group in self.plan[role]['context'] for key in self.bundle.groups[group]}
                if role==FINANCIAL: allowed.update(self.bundle.groups['ratios'])
                retained=[]
                for title in titles or []:
                    old=next((part for part in previous.get('parts',[]) if part['title']==title),None)
                    new=next((part for part in self.outputs[role].get('parts',[]) if part['title']==title),None)
                    old_good=sum(not check_claim(c,self.bundle.sources,allowed,role) for c in old.get('claims',[])) if old else 0
                    new_good=sum(not check_claim(c,self.bundle.sources,allowed,role) for c in new.get('claims',[])) if new else 0
                    if old and ((not new or not new.get('claims')) or (old_good>0 and new_good==0)):
                        self.outputs[role]['parts']=[p for p in self.outputs[role]['parts'] if p['title']!=title]+[old]
                        retained.append({'part':title,'prior_supported_claims':old_good,'repair_supported_claims':new_good,
                                         'reason':'Repair would erase content or reduce independently supported claims. Existing review errors remain.'})
                if retained:
                    save_json(self.desk.folder()/(role.lower().replace(' ','_')+'_rejected_repair.json'),{'retained_parts':retained})
                    save_json(self.desk.folder()/(role.lower().replace(' ','_')+'.json'),self.outputs[role])
        except Exception as exc:
            self.errors.append(str(exc))
            # A failed repair must not erase a previous successful draft.
            if role in self.outputs:
                save_json(self.desk.folder() / (role.lower().replace(' ','_')+'_repair_failure.json'),
                          {'error':str(exc),'prior_content_retained':True})
                return self.outputs[role]
            self.outputs[role] = ({'thesis':'Evidence unavailable.','recommendation':'Unavailable',
                'deciding_metric_id':'','rationale':'No validated numerical evidence is available.'} if role==ADVISOR
                else {'parts':[], 'metric_ids':[], **({'metrics':{}} if role==FINANCIAL else {})})
        return self.outputs[role]

    def manage(self):
        try:
            findings = self.review()
        except Exception as exc:
            self.errors.append(str(exc))
            findings = {part:['Manager review unavailable; repair this part once from its assigned sources.'] for part in PARTS}
        changed = False
        # The repair schedule and owner map are code. No LLM returns a next-node name.
        for role in (RESEARCH, FINANCIAL, ADVISOR):
            titles = [part for part in PARTS if OWNERS[part]==role and findings[part]]
            if role == ADVISOR and changed and not titles:
                titles = [PARTS[4]]
            if titles:
                print(role + ' — one repair pass', flush=True)
                feedback = {part:findings[part] or ['Upstream analysis changed; reassess using the updated outputs.'] for part in titles}
                self.visit(role, titles, feedback)
                if role != ADVISOR: changed = True
        if changed or any(findings.values()):
            print(MANAGER + ' — final check', flush=True)
            try:
                findings = self.review(final=True)
            except Exception as exc:
                self.errors.append(str(exc))
                findings = {part:['Final manager review unavailable.'] for part in PARTS}
        # Keep code failures even if a manager says all parts pass.
        for part,messages in self.validation().items():
            findings[part] = list(dict.fromkeys(findings[part]+messages))
        save_json(self.desk.folder() / 'review_final.json', findings)
        return ReportCompiler(self).compile(findings)


class ReportCompiler:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.bundle = coordinator.bundle
        self.next_id = 0

    def source(self, record, definition=''):
        kind = record.get('kind')
        if kind == 'fact':
            return {'kind':'tag','entity':record['source_id'].split(':')[1], 'tag':record['tag'],
                    'period_start':record.get('period_start'),'period_end':record['period_end'],
                    'filing':record['filing'],'unit':record['unit']}
        if kind == 'line':
            return {'kind':'line','document':record['document'],'line':record['line'],'quote':record['quote'],
                    'filing':record['filing'],'period_end':record.get('period_end'), 'definition':definition}
        if kind == 'price': return {'kind':'input'}
        return {'kind':'none'}

    def atom(self, value, source, claim, display=None, definition=''):
        self.next_id += 1
        display = display or numeric(value)
        entry = {'id':f'N{self.next_id:05d}', 'kind':'number','value':numeric(value),
                 'display':display,'source':source,'claim':claim,'definition':definition}
        return display + marker(entry)

    def prose(self, text, records, claim=None):
        # Only the compiler may create executable report annotation/thesis markers.
        text = text.replace('<!--','&lt;!--').replace('-->','--&gt;')
        def replace(match):
            value = dec(match.group())
            for record in records:
                if record['kind']=='line' and value in [dec(m.group()) for m in NUMBER.finditer(record['quote'])]:
                    return self.atom(value, self.source(record, claim or text), claim or text, match.group(), claim or text)
                if record['kind'] in {'fact','price'} and record.get('value') is not None and value==dec(record['value']):
                    return self.atom(value, self.source(record), claim or text, match.group(), claim or text)
            return self.atom(value, {'kind':'none'}, claim or text, match.group(), claim or text)
        return NUMBER.sub(replace, text)

    def ratio(self, record):
        name = record['source_id'].split(':')[2]
        rows = list(record.get('inputs',[]))
        definitions = {
            'revenue_growth_pct':('(a / b - 1) * 100','Annual revenue growth: current divided by prior revenue, minus one, in percent.'),
            'operating_margin_pct':('a / b * 100','GAAP operating income divided by total revenue for the same annual period, in percent.'),
            'return_on_average_equity_pct':('a / ((b + c) / 2) * 100','Annual net income divided by average beginning/end stockholders equity, in percent.'),
            'debt_to_equity':('(a + b) / c','Noncurrent long-term debt plus its current maturities, divided by year-end stockholders equity.'),
            'free_cash_flow_USD':('a - b','Operating cash flow minus cash payments for property, plant and equipment; not an adjusted filing definition.'),
            'price_to_earnings':('b / a','User price divided by fiscal-year GAAP diluted EPS including discontinued operations; not adjusted or trailing-twelve-month EPS.'),
            'net_margin_pct':('a / b * 100','Annual GAAP net income divided by revenue, in percent.'),
            'cash_conversion_pct':('a / b * 100','Annual operating cash flow divided by GAAP net income, in percent.'),
            'capex_to_revenue_pct':('a / b * 100','Annual cash payments for property, plant and equipment divided by revenue, in percent.'),
        }
        expression, definition = definitions[name]
        if name=='debt_to_equity' and rows and rows[0].get('tag')=='us-gaap:LongTermDebt':
            rows = [rows[0], rows[2]]
            expression,definition = 'a / b','Total long-term debt already including current maturities, divided by year-end equity; no double counting.'
        if any(r.get('value') is None for r in rows):
            return name + ': unavailable; a required saved input is missing.'
        inputs = [{'name':chr(97+i),'value':numeric(row['value']),'source':self.source(row)} for i,row in enumerate(rows)]
        selected_meanings = []
        for row in rows:
            if row.get('kind') == 'fact':
                entity = row['source_id'].split(':')[1]
                key = f"definition:{entity}:{row['tag'].split(':')[-1]}"
                meaning = self.bundle.sources.get(key,{}).get('quote')
                if meaning: selected_meanings.append(row['tag']+': '+meaning)
        if selected_meanings:
            definition += ' Selected input definitions: ' + ' | '.join(selected_meanings)
        try:
            value, display = arithmetic(expression, inputs)
        except Exception:
            return name + ': unavailable; arithmetic is undefined for the saved inputs.'
        self.next_id += 1
        entry = {'id':f'N{self.next_id:05d}','kind':'ratio','value':value,'display':display,'expression':expression,
                 'inputs':inputs,'decimal_places':6,'definition':definition,'claim':name}
        # The exact selected tags and periods make alternative accounting definitions explicit.
        details = ' | '.join(source_label(row['source']) for row in inputs)
        return name + ': ' + display + marker(entry) + '\nDefinition: ' + definition + ' [source: ' + details.replace(']','') + ']'

    def metric(self, record):
        if record['kind']=='ratio': return self.ratio(record)
        if record.get('value') is None:
            return record['source_id'].split(':')[-2] + ': unavailable.'
        source = self.source(record)
        return record['source_id'].split(':')[-2] + ': ' + self.atom(record['value'], source, record['source_id']) + ' [source: ' + source_label(source) + ']'

    def compile(self, findings):
        c = self.coordinator
        try:
            selected = c.desk.selections()
            filings = {f"{form} {row['accessionNumber']}" for form,row in selected.items()}
            filings.add('Exhibit 99.1 '+selected['8-K']['accessionNumber'])
        except Exception:
            filings = {'unavailable — see node errors'}
        for row in self.bundle.sources.values():
            if row['kind']=='fact': filings.add(row['filing'])
        for row in self.bundle.additional_documents:
            filings.add(row['document']+' '+row['filing'])
        lines = ['Filings read: '+'; '.join(sorted(filings)), 'Run time: '+c.desk.stamp, '', '# Equity Research Report', '',
                 'Status: '+('DRAFT — unresolved checks remain.' if any(findings.values()) or c.errors else 'Manager checks passed; independent verification follows.'),'']
        analyst_claims = sum(len(part.get('claims',[])) for role in (RESEARCH,FINANCIAL)
                             for part in c.outputs[role].get('parts',[]))
        if not analyst_claims:
            lines[5] = 'Status: FAILED — no analyst content was generated.'
            lines += ['**This is a failure record, not a completed equity-research report.**',
                      'Inspect the node error diagnostics in this run folder. No recommendation is available.','']
        for title in PARTS:
            lines += ['## '+title,'']
            if findings[title]:
                # Do not let ungrounded numerical repair messages become report evidence.
                lines += ['Review note: This part has unresolved review issues; see the saved review file.','']
            role = OWNERS[title]
            output = c.outputs[role]
            if role==ADVISOR:
                lines += ['**'+output.get('recommendation','Hold')+'**','', '<!-- advisor-thesis:start -->',
                          output.get('thesis','No supported thesis available.').replace('<!--','&lt;!--').replace('-->','--&gt;'),
                          '<!-- advisor-thesis:end -->','']
                metric = c.outputs[FINANCIAL].get('metrics',{}).get(output.get('deciding_metric_id'))
                if metric and metric.get('value') is not None:
                    lines += ['Deciding number: '+self.metric(metric),'']
                else: lines += ['Deciding number: unavailable.','']
                lines += [self.prose(output.get('rationale',''),[]),'']
                continue
            for part in output.get('parts',[]):
                if part.get('title')!=title: continue
                for claim in part.get('claims',[]):
                    records = [self.bundle.sources[e['source_id']] for e in claim.get('evidence',[]) if e.get('source_id') in self.bundle.sources]
                    lines += [self.prose(claim.get('text',''),records),'']
                    for citation in claim.get('evidence',[]):
                        record = self.bundle.sources.get(citation.get('source_id'))
                        if not record: continue
                        quote = citation.get('quote','')
                        if record['kind'] in {'fact','price','ratio','missing'}:
                            lines += ['Evidence: '+self.metric(record),'']
                            continue
                        # A model quote must occur in its claimed line. Otherwise the Verifier sees it as uncited.
                        trusted = [record] if quote and quote in record.get('quote','') else []
                        lines += ['> '+self.prose(quote,trusted,claim.get('text',''))+' [source: '+source_label(self.source(record))+']','']
            if role==FINANCIAL:
                lines += ['### Statement facts and calculator arithmetic','']
                for record in output.get('metrics',{}).values():
                    lines += ['- '+self.metric(record),'']
        path = c.desk.folder()/'report.md'
        with path.open('x',encoding='utf-8') as stream: stream.write('\n'.join(lines)+'\n')
        print(f'Report: {path}',flush=True)
        return str(path)
