"""Seven SEC data steps followed by four isolated equity-research model roles."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import io
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
SEC = 'https://www.sec.gov'
DATA = 'https://data.sec.gov'
# Ordered tie-breakers only: a newer annual period always beats tag order.
CONCEPTS = {
    'revenue': ('USD', True, ['RevenueFromContractWithCustomerExcludingAssessedTax',
                             'RevenueFromContractWithCustomerIncludingAssessedTax',
                             'Revenues', 'SalesRevenueNet']),
    'operating_income': ('USD', True, ['OperatingIncomeLoss']),
    'net_income': ('USD', True, ['NetIncomeLoss', 'ProfitLoss']),
    'diluted_eps': ('USD/shares', True, ['EarningsPerShareDiluted']),
    'equity': ('USD', False, ['StockholdersEquity',
                            'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']),
    'long_term_debt': ('USD', False, ['LongTermDebtNoncurrent', 'LongTermDebt']),
    'current_debt': ('USD', False, ['LongTermDebtCurrent',
                                  'LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths']),
    'operating_cash_flow': ('USD', True, ['NetCashProvidedByUsedInOperatingActivities']),
    'capex': ('USD', True, ['PaymentsToAcquirePropertyPlantAndEquipment']),
}


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


class SecClient:
    """All requests, including retries and redirects, carry the configured User-Agent."""
    def __init__(self, user_agent):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent, 'Accept-Encoding': 'gzip, deflate'})
        self.last_request = 0.0
        self.cache = {}

    def get(self, url):
        if url in self.cache:
            return self.cache[url]
        # Stay well below SEC's 10 requests/second limit, including retries.
        for attempt in range(4):
            time.sleep(max(0, .25 - (time.monotonic() - self.last_request)))
            if urlparse(url).hostname not in {'www.sec.gov', 'data.sec.gov'}:
                raise ValueError('Refusing a non-SEC document URL.')
            self.last_request = time.monotonic()
            response = self.session.get(url, timeout=(15, 90), allow_redirects=False)
            if response.is_redirect:
                return self.get(urljoin(url, response.headers['Location']))
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code == 403:
                raise RuntimeError(f'SEC denied access (403): {url}. Check SEC_USER_AGENT and try later.')
            response.raise_for_status()
            self.cache[url] = response
            return response
        raise RuntimeError('SEC request failed after retries.')

    def json(self, url):
        return self.get(url).json()


def plain_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.find_all(['script', 'style', 'noscript', 'ix:header']):
        node.decompose()
    # Preserve a financial table row as one line, including column values.
    for row in soup.find_all('tr'):
        row.replace_with('\n' + ' | '.join(c.get_text(' ', strip=True)
                         for c in row.find_all(['th', 'td'], recursive=False)) + '\n')
    for node in soup.find_all(['p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4']):
        node.insert_before('\n')
        node.insert_after('\n')
    return '\n'.join(line for raw in soup.get_text(' ').splitlines()
                     if (line := re.sub(r'\s+', ' ', raw).strip()))


def document_text(response):
    if response.content.startswith(b'%PDF'):
        # Imported only for PDF exhibits; also supported by the install command.
        from pypdf import PdfReader
        return '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(response.content)).pages)
    return plain_text(response.content)


def resolve(mapping, ticker):
    normalized = ticker.upper().replace('.', '-')
    for company in mapping.values():
        if company['ticker'].upper().replace('.', '-') == normalized:
            return {**company, 'cik': f"{int(company['cik_str']):010d}"}
    raise ValueError(f'Ticker {ticker!r} was not found in SEC company_tickers.json.')


def column_rows(columns):
    for i in range(len(columns.get('accessionNumber', []))):
        yield {key: values[i] for key, values in columns.items()
               if isinstance(values, list) and i < len(values)}


def filing_history(client, cik):
    submissions = client.json(f'{DATA}/submissions/CIK{cik}.json')
    rows = list(column_rows(submissions['filings']['recent']))
    for archive in submissions['filings'].get('files', []):
        rows.extend(column_rows(client.json(f"{DATA}/submissions/{archive['name']}")))
    unique = {r['accessionNumber']: r for r in rows}
    return sorted(unique.values(), key=lambda r: (r.get('filingDate', ''),
                   r.get('acceptanceDateTime', ''), r['accessionNumber']), reverse=True)


def filing_urls(cik, row):
    accession = row['accessionNumber']
    base = f"{SEC}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    return base, base + accession + '-index.html'


def index_details(html, index_url):
    soup = BeautifulSoup(html, 'html.parser')
    accepted = None
    for label in soup.select('.infoHead'):
        if label.get_text(' ', strip=True).lower() == 'accepted':
            value = label.find_next_sibling(class_='info')
            if value:
                accepted = value.get_text(' ', strip=True)
                break
    if not accepted:
        raise ValueError(f'Accepted time not found on {index_url}')
    documents = []
    for row in soup.select('table.tableFile tr'):
        cells = row.find_all('td')
        if len(cells) >= 4 and cells[2].find('a', href=True):
            href = cells[2].find('a', href=True)['href']
            # The index may link through the inline XBRL viewer.
            if 'doc=' in href:
                from urllib.parse import parse_qs
                href = parse_qs(urlparse(href).query).get('doc', [href])[0]
            documents.append({'description': cells[1].get_text(' ', strip=True),
                              'type': cells[3].get_text(' ', strip=True),
                              'url': urljoin(index_url, href)})
    return accepted, documents


def has_item_202(text):
    return bool(re.search(r'\bItem\s*2\s*\.\s*02\b', text, re.I))


def select_filings(client, cik, rows):
    selected = {}
    # Primary annual and quarterly reports, not amendments.
    for form in ('10-K', '10-Q', '8-K'):
        for row in rows:
            if row['form'] != form:
                continue
            base, index_url = filing_urls(cik, row)
            if not row.get('primaryDocument'):
                continue
            primary_url = base + row['primaryDocument']
            if form == '8-K':
                items = str(row.get('items', '')).strip()
                if items and not re.search(r'(?<!\d)2\.02(?!\d)', items):
                    continue
                if not has_item_202(document_text(client.get(primary_url))):
                    continue
            accepted, documents = index_details(client.get(index_url).content, index_url)
            release = next((d['url'] for d in documents
                            if re.fullmatch(r'EX-99\.0?1', d['type'], re.I)), None)
            selected[form] = {**row, 'index_url': index_url, 'primary_url': primary_url,
                              'accepted': accepted, 'release_url': release}
            break
        if form not in selected:
            raise ValueError(f'No {form}' + (' reporting Item 2.02' if form == '8-K' else '') + ' was found.')
    return selected


def is_annual(row):
    if row.get('form') not in {'10-K', '10-K/A'} or not row.get('start'):
        return False
    days = (date.fromisoformat(row['end']) - date.fromisoformat(row['start'])).days
    return 300 <= days <= 400


def fact_rows(facts, tag, unit, duration):
    values = facts.get('facts', {}).get('us-gaap', {}).get(tag, {}).get('units', {}).get(unit, [])
    return [r for r in values if (is_annual(r) if duration else
            r.get('form') in {'10-K', '10-K/A'} and 'start' not in r)]


def choose_tag(facts, tags, unit, duration):
    choices = []
    for priority, tag in enumerate(tags):
        rows = fact_rows(facts, tag, unit, duration)
        if rows:
            choices.append((max(r['end'] for r in rows), -priority, tag, rows))
    return max(choices, key=lambda x: (x[0], x[1]))[2:] if choices else (None, [])


def pick_period(rows, period, duration, tag, unit):
    if period is None:
        return None
    candidates = [r for r in rows if r['end'] == period['end']
                  and (not duration or r.get('start') == period['start'])]
    if not candidates:
        return None
    # Most recently filed comparative incorporates later restatements.
    row = max(candidates, key=lambda r: (r.get('filed', ''), r.get('accn', '')))
    return {**row, 'tag': f'us-gaap:{tag}', 'unit': unit,
            'filing_url': f"{SEC}/Archives/edgar/data/{int(period['cik'])}/"
                          f"{row['accn'].replace('-', '')}/{row['accn']}-index.html"}


def extract_facts(raw, cik):
    _, revenue_rows = choose_tag(raw, CONCEPTS['revenue'][2], 'USD', True)
    if not revenue_rows:
        raise ValueError('No supported annual USD revenue tag in company facts. Custom tags are not inferred.')
    latest = max(revenue_rows, key=lambda r: (r['end'], r.get('filed', '')))
    current = {'start': latest['start'], 'end': latest['end'], 'cik': cik}
    older = [r for r in revenue_rows if 300 <= (date.fromisoformat(current['end']) -
                                              date.fromisoformat(r['end'])).days <= 400]
    prior_row = max(older, key=lambda r: (r['end'], r.get('filed', ''))) if older else None
    prior = {'start': prior_row['start'], 'end': prior_row['end'], 'cik': cik} if prior_row else None
    # fy on a comparative fact is the filing's FY, not necessarily the fact's FY.
    direct = [r for r in revenue_rows if r['end'] == current['end'] and r.get('fp') == 'FY'
              and r.get('fy') is not None and r.get('filed', '')[:4] >= current['end'][:4]]
    first = min(direct, key=lambda r: (r.get('filed', ''), r.get('accn', ''))) if direct else latest
    result = {'cik': cik, 'entity_name': raw.get('entityName'), 'fiscal_year': first.get('fy'),
              'current_period': current, 'prior_period': prior, 'concepts': {},
              'selection_policy': 'Newest annual period wins among candidate tags; ordered tags break ties. '
                 'Every value matches revenue dates; latest-filed comparative wins. Missing is not zero.'}
    for name, (unit, duration, tags) in CONCEPTS.items():
        tag, rows = choose_tag(raw, tags, unit, duration)
        result['concepts'][name] = {'selected_tag': f'us-gaap:{tag}' if tag else None,
            'latest_available_end': max((r['end'] for r in rows), default=None),
            'current': pick_period(rows, current, duration, tag, unit),
            'prior': pick_period(rows, prior, duration, tag, unit)}
    return result


def number(value):
    return f'{value:,.6f}'.rstrip('0').rstrip('.') if isinstance(value, (float, int)) else str(value)


def display_facts(facts):
    print(f"Fiscal year: {facts['fiscal_year']}; current: {facts['current_period']['start']} to "
          f"{facts['current_period']['end']}; prior: "
          f"{facts['prior_period']['end'] if facts['prior_period'] else 'unavailable'}")
    print('Each line shows CURRENT | PRIOR; values are USD, except EPS (USD/share).')
    for name, concept in facts['concepts'].items():
        parts = []
        for key in ('current', 'prior'):
            row = concept[key]
            parts.append((f"{number(row['val'])} {row['unit']}; {row['tag']}; "
                          f"end={row['end']}; filing={row['accn']}; filed={row.get('filed')}"
                          if row else f"unavailable ({concept['selected_tag'] or 'no supported tag'})"))
        print(f"  {name}: " + ' | '.join(parts))
        if name == 'long_term_debt' and concept['selected_tag'] == 'us-gaap:LongTermDebt':
            print('    LongTermDebt includes current maturities; the calculator will not add them again.')


def calculate(facts, price=None):
    def v(name, period='current'):
        row = facts['concepts'][name][period]
        return row['val'] if row else None
    results = {}

    def metric(name, operands, formula, operation, denominator=None, positive=False):
        if any(x is None for x in operands):
            results[name] = {'value': None, 'arithmetic': 'unavailable: required fact is missing'}
        elif denominator is not None and (denominator == 0 or (positive and denominator < 0)):
            results[name] = {'value': None, 'arithmetic': 'unavailable: denominator must be positive' if positive
                             else 'unavailable: denominator is zero'}
        else:
            value = operation()
            results[name] = {'value': value, 'arithmetic': formula + ' = ' + number(value)}
    r, old, op, net = v('revenue'), v('revenue', 'prior'), v('operating_income'), v('net_income')
    eq, prior_eq = v('equity'), v('equity', 'prior')
    debt, current, cfo, capex, eps = (v(k) for k in ('long_term_debt', 'current_debt',
                                                    'operating_cash_flow', 'capex', 'diluted_eps'))
    n = number
    metric('revenue_growth_pct', [r, old], f'({n(r)} / {n(old)} - 1) * 100',
           lambda: (r / old - 1) * 100, old)
    metric('operating_margin_pct', [op, r], f'{n(op)} / {n(r)} * 100', lambda: op / r * 100, r)
    average = (eq + prior_eq) / 2 if eq is not None and prior_eq is not None else None
    metric('return_on_average_equity_pct', [net, eq, prior_eq],
           f'{n(net)} / (({n(eq)} + {n(prior_eq)}) / 2) * 100', lambda: net / average * 100, average, True)
    debt_row = facts['concepts']['long_term_debt']['current']
    if debt_row and debt_row['tag'] == 'us-gaap:LongTermDebt':
        metric('debt_to_equity', [debt, eq], f'{n(debt)} / {n(eq)} (current maturities already included)',
               lambda: debt / eq, eq, True)
    else:
        metric('debt_to_equity', [debt, current, eq], f'({n(debt)} + {n(current)}) / {n(eq)}',
               lambda: (debt + current) / eq, eq, True)
    metric('free_cash_flow_USD', [cfo, capex], f'{n(cfo)} - {n(capex)}', lambda: cfo - capex)
    metric('price_to_earnings', [price, eps], f'{n(price)} / {n(eps)}', lambda: price / eps, eps, True)
    if price is None:
        results['price_to_earnings']['arithmetic'] = 'unavailable: supply --price in USD; uses fiscal-year diluted EPS'
    return results


def print_calculations(results):
    for name, result in results.items():
        print(f"  {name}: {result['arithmetic']}")


def release_lines(text):
    """Rank source lines, favoring consolidated quarter results over segments/outlook.

    This is a rule-based locator, not a general financial-table interpreter. Keep
    the surrounding labels/columns so that no GAAP or period claim is invented.
    """
    lines = text.splitlines()
    matches = {'revenue': [], 'diluted_eps': []}
    for i, line in enumerate(lines):
        before = ' '.join(lines[max(0, i-20):i])
        nearby = ' '.join(lines[max(0, i-3):i+5])
        revenue = re.search(r'\b(total\s+(net\s+)?(revenue|sales)|net\s+(revenue|sales)|revenues?)\b', line, re.I)
        eps = re.search(r'dilut', line, re.I) and re.search(r'(earnings|income|loss|EPS|per.share)', nearby, re.I)
        for key, matched in [('revenue', revenue), ('diluted_eps', eps)]:
            if not matched or not re.search(r'\d', nearby):
                continue
            score = 0
            if re.search(r'(quarter|three\s+months)', before + ' ' + line, re.I):
                score += 10
            if re.search(r'\b(total|consolidated)\b', line, re.I):
                score += 20
            if key == 'diluted_eps':
                # A consolidated EPS table may put "TOTAL" below "Assuming dilution".
                if re.search(r'\bTOTAL\b', ' '.join(lines[i:i+5]), re.I):
                    score += 25
                if re.search(r'continuing.operations', line, re.I):
                    score -= 10
            if key == 'revenue' and re.search(r'^\W*(total\s+)?(net\s+)?(revenue|sales)s?\s+(of|was|were)\s+\$', line, re.I):
                score += 25
            if re.search(r'(segment|business\s+unit)', before, re.I):
                score -= 20
            if re.search(r'(expect|outlook|guidance|forecast|constant.currency|growth)', line, re.I):
                score -= 15
            # The most recent explicit period heading governs a later table row.
            headings = re.findall(r'(three\s+months|nine\s+months|six\s+months|twelve\s+months|full.year|quarter)', before, re.I)
            if headings and re.search(r'(nine|six|twelve|full)', headings[-1], re.I):
                score -= 25
            matches[key].append({'line': i + 1, 'text': line, 'score': score,
                                'period_labels': [s for s in lines[max(0, i-100):i+1]
                                    if re.search(r'(months\s+ended|quarter|years?\s+ended|except.*per.share)', s, re.I)
                                    and len(s) < 400][-6:],
                                'context': lines[max(0, i-5):min(len(lines), i+5)]})
    for key, candidates in matches.items():
        # Earliest source line breaks equal scores; never fabricate a value.
        matches[key] = [max(candidates, key=lambda c: (c['score'], -c['line']))] if candidates else []
    return matches


class Desk:
    def __init__(self, client, args):
        self.client, self.args = client, args
        self._company = self._mapping = self._rows = self._selected = self._facts = None
        self._folder = None
        self._release = None
        self.stamp = datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S_%f%z')

    def company(self):
        if self._company is None:
            self._mapping = self.client.json(f'{SEC}/files/company_tickers.json')
            self._company = resolve(self._mapping, self.args.ticker)
        return self._company

    def folder(self):
        if self._folder is None:
            company = self.company()
            name = re.sub(r'[^\w.-]+', '_', company['title']).strip('._') or company['cik']
            self._folder = ROOT / 'research_data' / f'{name}_{self.stamp}'
            self._folder.mkdir(parents=True, exist_ok=False)
            save_json(self._folder / 'run.json', {'company': company, 'run_time': self.stamp,
                      'ticker': self.args.ticker, 'peers': self.args.peers, 'price_USD': self.args.price,
                      'step': self.args.step})
        return self._folder

    def selections(self):
        if self._selected is None:
            cik = self.company()['cik']
            self._rows = filing_history(self.client, cik)
            folder = self.folder()
            save_json(folder / 'filings.json', self._rows)
            with (folder / 'filings.csv').open('w', newline='', encoding='utf-8') as stream:
                fields = ['form', 'filingDate', 'accessionNumber', 'primaryDocument', 'items']
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(self._rows)
            self._selected = select_filings(self.client, cik, self._rows)
            save_json(folder / 'selected_filings.json', self._selected)
        return self._selected

    def facts(self):
        if self._facts is None:
            cik = self.company()['cik']
            raw = self.client.json(f'{DATA}/api/xbrl/companyfacts/CIK{cik}.json')
            save_json(self.folder() / 'companyfacts_raw.json', raw)
            self._facts = extract_facts(raw, cik)
            save_json(self.folder() / 'facts.json', self._facts)
        return self._facts

    def download(self, name, url):
        response = self.client.get(url)
        suffix = '.pdf' if response.content.startswith(b'%PDF') else '.html'
        (self.folder() / (name + suffix)).write_bytes(response.content)
        text = document_text(response)
        (self.folder() / (name + '.txt')).write_text(text + '\n', encoding='utf-8')
        return text

    def release(self):
        if self._release is None:
            url = self.selections()['8-K']['release_url']
            if not url:
                raise ValueError('Latest Item 2.02 8-K has no Exhibit 99.1. No older release was substituted.')
            self._release = self.download('earnings_release_99_1', url)
        return self._release

    def step1(self):
        c = self.company()
        print(f"{c['ticker']} -> CIK {c['cik']} ({c['title']})")
        save_json(self.folder() / 'company.json', c)

    def step2(self):
        selected = self.selections()
        print(f'Filing history: {len(self._rows)} filings; full list in filings.csv and filings.json')
        for row in self._rows:
            print(f"  {row.get('filingDate')} {row['form']} {row['accessionNumber']}")
        for form, row in selected.items():
            print(f"SELECTED {form}: {row['accessionNumber']}; Accepted: {row['accepted']} (as displayed by EDGAR)")
            print(f"  {row['index_url']}")

    def step3(self):
        for form, row in self.selections().items():
            self.download(form, row['primary_url'])
            print(f'Saved {form} source and plain text.')
        self.release()
        print('Saved Exhibit 99.1 source and plain text.')

    def step4(self):
        display_facts(self.facts())

    def step5(self):
        results = calculate(self.facts(), self.args.price)
        print_calculations(results)
        save_json(self.folder() / 'calculations.json', results)

    def step6(self):
        matches = release_lines(self.release())
        print('Quarter revenue and diluted-EPS source lines, selected by rules, with adjacent context.')
        print('Check the displayed period columns and GAAP/non-GAAP labels; no values are inferred.')
        for key, entries in matches.items():
            print(f'{key}:')
            if not entries:
                print('  No matching line found. Review earnings_release_99_1.txt; no value was inferred.')
            for entry in entries:
                for label in entry['period_labels']:
                    print(f'    Period label: {label}')
                print(f"  Line {entry['line']}: {entry['text']}")
                print('    Context: ' + ' / '.join(entry['context']))
        save_json(self.folder() / 'release_lines.json', matches)

    def step7(self):
        if not self.args.peers:
            print('No peers supplied. Use --peers followed by tickers.')
            return
        peers = {}
        for ticker in self.args.peers:
            try:
                company = resolve(self._mapping or self.client.json(f'{SEC}/files/company_tickers.json'), ticker)
                print(f"Peer {company['ticker']} — {company['title']}")
                raw = self.client.json(f"{DATA}/api/xbrl/companyfacts/CIK{company['cik']}.json")
                facts = extract_facts(raw, company['cik'])
                display_facts(facts)
                margin = calculate(facts)['operating_margin_pct']
                print(f"  operating_margin_pct: {margin['arithmetic']}")
                peers[ticker] = {'company': company, 'facts': facts, 'operating_margin_pct': margin}
                save_json(self.folder() / f"peer_{company['cik']}_companyfacts_raw.json", raw)
            except (ValueError, RuntimeError, requests.RequestException) as exc:
                peers[ticker] = {'error': str(exc)}
                print(f'  Peer {ticker}: unavailable: {exc}')
            save_json(self.folder() / 'peers.json', peers)
        print('Peer fiscal-year dates are shown above; fiscal calendars may differ.')


STEPS = ['Resolve ticker to CIK', 'List and select filings; read Accepted times',
         'Download documents and convert to plain text', 'Annual company facts with prior year',
         'Financial calculator', 'Quarter revenue and diluted EPS from release',
         'Peer facts and operating margins']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ticker')
    parser.add_argument('--peers', nargs='+', default=[], help='Space- or comma-separated tickers')
    parser.add_argument('--price', type=float, help='USD price per share for fiscal-year P/E')
    parser.add_argument('--step', type=int, choices=range(1, 8), help='Print/run only this step; fetch its prerequisites quietly')
    parser.add_argument('--data-only', action='store_true', help='Run the seven data steps without model calls')
    parser.add_argument('--model', default='gpt-5.4', help='OpenAI model for each isolated role (default: gpt-5.4)')
    args = parser.parse_args()
    args.peers = list(dict.fromkeys(t.upper() for item in args.peers for t in item.split(',') if t))
    if args.price is not None and (not math.isfinite(args.price) or args.price <= 0):
        parser.error('--price must be a finite positive number in USD')
    config = dotenv_values(ROOT / '.env')
    use_roles = args.step is None and not args.data_only
    api_key = (config.get('API_KEY') or '').strip() if use_roles else None
    if use_roles and (not api_key or api_key == 'paste-here'):
        parser.error('Set API_KEY in .env for model roles, or use --data-only for SEC data only.')
    user_agent = (config.get('SEC_USER_AGENT') or '').strip()
    if not user_agent or 'your-email@' in user_agent.lower() or not re.search(r'\S+@\S+\.\S+', user_agent):
        parser.error('Set SEC_USER_AGENT in .env to your name and real contact email.')
    desk = Desk(SecClient(user_agent), args)
    failures = []
    for step in ([args.step] if args.step else range(1, 8)):
        print(f'\nSTEP {step}/7: {STEPS[step-1]}', flush=True)
        try:
            getattr(desk, f'step{step}')()
        except (ValueError, KeyError, RuntimeError, requests.RequestException) as exc:
            failures.append(step)
            print(f'Step {step} failed: {exc}', file=sys.stderr)
    if use_roles and not failures:
        try:
            from research_roles import run_roles
            run_roles(desk, api_key, args.model)
        except (ValueError, KeyError, RuntimeError, OSError, ImportError) as exc:
            failures.append('roles')
            print(f'Research roles failed: {exc}', file=sys.stderr)
    elif use_roles:
        print('Research roles skipped because a required data step failed.', file=sys.stderr)
    if desk._folder:
        print(f'\nSaved data: {desk._folder}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
