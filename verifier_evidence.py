"""Lossless numerical-claim coverage with source-focused, original-line excerpts.

The independent code verifier still reads ALL original saved texts and facts.
This module selects source material for each bounded semantic batch; it never
approves a number, truncates a quote, changes a fact, or drops a number ID.
"""
from __future__ import annotations

import re
import json
from collections import Counter
from copy import deepcopy

CONCEPTS = {
    'revenue': r'total\s+revenues?|net\s+sales|membership\s+fees|revenuefromcontract|\brevenues?\b',
    'operating': r'operating\s+(?:income|loss|profit)|operatingincomeloss',
    'income': r'\bnet\s+(?:income|earnings|loss)|netincomeloss|profitloss',
    'eps': r'dilut|earnings\s+per|assuming\s+dilution',
    'equity': r'equity|noncontrolling',
    'debt': r'long.term\s*debt|longtermdebt|current\s+(?:portion|maturities)',
    'cash_flow': r'operating\s+(?:activities|cash\s+flow)|cashprovidedbyusedinoperating',
    'capex': r'property.*equipment|capital\s+expenditures|paymentstoacquire',
}
DEFINITIONS = re.compile(r'non.?GAAP|\bGAAP\b|adjusted\s+(?:earnings|income|cash|EPS)|'
                         r'continuing\s+operations|discontinued\s+operations|noncontrolling|'
                         r'current\s+(?:portion|maturities)|excluding.*(?:tax|debt|cash)|'
                         r'total\s+revenues?|net\s+sales',re.I)
HEADERS = re.compile(r'weeks?\s+ended|months?\s+ended|years?\s+ended|unaudited|'
                    r'in\s+(?:millions|thousands)|per.share|\b20\d{2}\b',re.I)
EXPLICIT_DEFINITION = re.compile(r'defin|refer\s+to|represent|consist|includ|exclud|'
                                r'non.?GAAP|\bGAAP\b|recogniz|current\s+(?:portion|maturities)|'
                                r'continuing\s+operations|discontinued\s+operations|noncontrolling',re.I)
STOP = {'the','that','this','with','from','were','was','which','have','has','their',
        'company','issuer','fiscal','year','annual','quarter','claim','definition',
        'period','current','prior','income','revenue','value','dollars','million','billion'}


def all_sources(entry):
    source=entry.get('source')
    if isinstance(source,dict): yield source
    for operand in entry.get('inputs',[]):
        if isinstance(operand.get('source'),dict): yield operand['source']


def ranges(indices):
    result=[]
    for index in sorted(indices):
        if result and index == result[-1][1]+1: result[-1][1]=index
        else: result.append([index,index])
    return [[start+1,end+1] for start,end in result]


def select_evidence(texts, entries, documents=None):
    signals=' '.join(str(e.get('claim',''))+' '+str(e.get('definition',''))+' '+
                     ' '.join(str(s.get('tag','')) for s in all_sources(e)) for e in entries)
    active={name for name,pattern in CONCEPTS.items() if re.search(pattern,signals,re.I)}
    concept_re=re.compile('|'.join(CONCEPTS[name] for name in sorted(active)),re.I) if active else None
    unknown=[e for e in entries if e.get('source',{}).get('kind') in {None,'none'} and e.get('kind')!='ratio']
    quarter_correction_needed=any(re.search(r'quarter|10-Q|three\s+months|year.to.date',e.get('claim',''),re.I)
                                  for e in unknown)
    keyword_sets=[]
    for entry in unknown:
        words={w.lower() for w in re.findall(r'[A-Za-z]{4,}',entry.get('claim',''))} - STOP
        if len(words)>=2: keyword_sets.append(words)
    excerpts,manifest={},{}
    referenced_filings={source.get('filing') for entry in entries for source in all_sources(entry)
                        if source.get('filing')}
    for document,text in texts.items():
        lines=text.splitlines(); selected=set(); anchors=set(); cited=set(); definitions=set()
        def window(index,before=2,after=2):
            selected.update(range(max(0,index-before),min(len(lines),index+after+1)))
        # Preserve every actual cited line and the adjoining rows/labels.
        for entry in entries:
            for source in all_sources(entry):
                if source.get('kind')=='line' and source.get('document')==document:
                    try: index=int(source['line'])-1
                    except (KeyError,TypeError,ValueError): continue
                    if 0<=index<len(lines):
                        cited.add(index); anchors.add(index); window(index,5,5)
        # An uncited 10-Q is not evidence for facts sourced to an annual 10-K.
        # It remains available to the independent code checks and in the run.
        irrelevant_quarter=(document=='10-Q' and documents and referenced_filings and
                            documents.get(document) not in referenced_filings and not cited and not quarter_correction_needed)
        if irrelevant_quarter:
            pass
        elif document=='8-K' and not cited:
            # An uncited cover filing is not the release. Retain any accounting
            # definition it supplies; the full Exhibit 99.1 is kept separately.
            for index,line in enumerate(lines):
                if DEFINITIONS.search(line) and (concept_re is None or concept_re.search(line)):
                    definitions.add(index);window(index,1,1)
        # Small releases and 8-Ks contain key competing definitions and quarter tables.
        elif len(text)<=16000:
            selected.update(range(len(lines)))
        else:
            for index,line in enumerate(lines):
                # Statement rows and short headings, rather than every incidental
                # occurrence of a concept in the annual report's narrative.
                if concept_re and concept_re.search(line) and ('|' in line or len(line)<250):
                    anchors.add(index);window(index,0,0)
                # Keep ALL matching alternative-definition statements, without a
                # silent top-N cutoff or a character truncation of long paragraphs.
                if (DEFINITIONS.search(line) and (concept_re is None or concept_re.search(line))
                        and ('|' in line or EXPLICIT_DEFINITION.search(line))):
                    definitions.add(index);anchors.add(index);window(index,0,0)
                if keyword_sets:
                    words={w.lower() for w in re.findall(r'[A-Za-z]{4,}',line)}
                    if any(len(words & wanted)>=min(3,len(wanted)) for wanted in keyword_sets):
                        anchors.add(index);window(index,1,1)
            # Retain the original period, currency/scale and column headings.
            for index in sorted(anchors):
                possible=[]
                for header in range(max(0,index-100),index+1):
                    line=lines[header]
                    if len(line)<300 and HEADERS.search(line) and ('|' in line or len(line)<100):
                        possible.append(header)
                # Keep the closest header group, with all year/unit cells next to
                # each header. Earlier unrelated tables do not define this row.
                for header in possible[-3:]: window(header,0,2)
            if selected: selected.update(range(min(10,len(lines))))
        excerpts[document]='\n'.join(f'L{index+1}: {lines[index]}' for index in sorted(selected))
        manifest[document]={'original_lines':len(lines),'selected_lines':len(selected),
                            'cited_lines':[i+1 for i in sorted(cited)],
                            'definition_lines':[i+1 for i in sorted(definitions)],
                            'uncited_quarter_not_used_for_annual_claims':bool(irrelevant_quarter),
                            'line_ranges':ranges(selected)}
    return excerpts,{'number_ids':[e['id'] for e in entries],'active_concepts':sorted(active),
                     'documents':manifest,'code_checks_use_full_saved_files':True,
                     'selection_policy':'All cited windows, competing-definition matches, relevant statement rows, period/scale headings and uncited-claim correction context. No number or fact is dropped.'}


def compact_facts(files):
    """Deduplicate repeated taxonomy text without changing any value/period/tag."""
    result=deepcopy(files); texts={}; indices={}
    definitions=result.get('verification_facts.json',{}).get('definitions',{})
    for record in definitions.values():
        quote=record.get('quote')
        if not isinstance(quote,str): continue
        if quote not in indices:
            key=f'D{len(indices)+1:03d}';indices[quote]=key;texts[key]=quote
        record['quote']={'definition_text_ref':indices[quote]}
    result['_shared_definition_texts']=texts
    return result


def expand_facts(files):
    result=deepcopy(files);texts=result.pop('_shared_definition_texts',{})
    for record in result.get('verification_facts.json',{}).get('definitions',{}).values():
        quote=record.get('quote')
        if isinstance(quote,dict) and 'definition_text_ref' in quote:
            record['quote']=texts[quote['definition_text_ref']]
    return result


def compact_report(report):
    """Intern only repeated prose inside hidden number annotations; keep all IDs,
    displayed numbers, tags, periods, arithmetic, and visible report text intact.
    """
    from desk_verifier import ANNOTATION,marker
    counts=Counter()
    def collect(value,key=None):
        if isinstance(value,dict):
            for k,v in value.items(): collect(v,k)
        elif isinstance(value,list):
            for item in value: collect(item,key)
        elif key in {'claim','definition','quote'} and isinstance(value,str) and len(value)>=48:
            counts[value]+=1
    for match in ANNOTATION.finditer(report):
        try: collect(json.loads(match[1]))
        except (ValueError,TypeError): pass
    shared={};lookup={}
    def compact(value,key=None):
        if isinstance(value,dict): return {k:compact(v,k) for k,v in value.items()}
        if isinstance(value,list): return [compact(v,key) for v in value]
        if key in {'claim','definition','quote'} and isinstance(value,str) and counts[value]>1:
            if value not in lookup:
                identifier=f'R{len(lookup)+1:03d}';lookup[value]=identifier;shared[identifier]=value
            return {'report_text_ref':lookup[value]}
        return value
    def replace(match):
        try: return marker(compact(json.loads(match[1])))
        except (ValueError,TypeError): return match.group()
    markdown=ANNOTATION.sub(replace,report)
    return {'markdown':markdown,'_shared_texts':shared}


def expand_report(packet):
    from desk_verifier import ANNOTATION,marker
    shared=packet['_shared_texts']
    def restore(value):
        if isinstance(value,dict):
            if set(value)=={'report_text_ref'}: return shared[value['report_text_ref']]
            return {k:restore(v) for k,v in value.items()}
        if isinstance(value,list): return [restore(v) for v in value]
        return value
    def replace(match):
        try: return marker(restore(json.loads(match[1])))
        except (ValueError,TypeError): return match.group()
    return ANNOTATION.sub(replace,packet['markdown'])
