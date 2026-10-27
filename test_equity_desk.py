"""Offline checks for selection rules and arithmetic; no SEC access or credentials."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import equity_desk as desk


def annual(value, end='2025-12-31', start='2025-01-01', filed='2026-02-01', **extra):
    return dict(val=value, start=start, end=end, filed=filed, form='10-K',
                accn='0000000001-26-000001', fy=2025, fp='FY', **extra)


def fixture():
    facts = {'facts': {'us-gaap': {}}}
    current = [120, 24, 12, 3, 60, 20, 10, 30, 8]
    prior = [100, 15, 8, 2, 40, 18, 5, 25, 7]
    for (name, (unit, duration, tags)), a, b in zip(desk.CONCEPTS.items(), current, prior):
        rows = [annual(a), annual(b, '2024-12-31', '2024-01-01')]
        if not duration:
            for row in rows:
                row.pop('start')
        facts['facts']['us-gaap'][tags[0]] = {'units': {unit: rows}}
    return facts


class FactTests(unittest.TestCase):
    def test_newest_candidate_wins_over_priority(self):
        raw = fixture()
        raw['facts']['us-gaap']['Revenues'] = {'units': {'USD': [annual(200, '2026-12-31', '2026-01-01')]}}
        tag, rows = desk.choose_tag(raw, desk.CONCEPTS['revenue'][2], 'USD', True)
        self.assertEqual(tag, 'Revenues')
        self.assertEqual(rows[0]['val'], 200)

    def test_aligns_dates_not_comparative_fy_and_excludes_quarters(self):
        raw = fixture()
        rows = raw['facts']['us-gaap']['OperatingIncomeLoss']['units']['USD']
        rows.append(annual(999, '2026-12-31', '2026-01-01'))
        quarter = annual(888, '2026-09-30', '2026-07-01')
        quarter['form'] = '10-Q'
        raw['facts']['us-gaap'][desk.CONCEPTS['revenue'][2][0]]['units']['USD'].append(quarter)
        result = desk.extract_facts(raw, '0000000001')
        self.assertEqual(result['current_period']['end'], '2025-12-31')
        self.assertEqual(result['concepts']['operating_income']['current']['val'], 24)
        self.assertEqual(result['concepts']['revenue']['prior']['val'], 100)

    def test_restated_comparative_uses_latest_filing(self):
        raw = fixture()
        rows = raw['facts']['us-gaap']['NetIncomeLoss']['units']['USD']
        row = annual(9, '2024-12-31', '2024-01-01', filed='2026-03-01')
        rows.append(row)
        self.assertEqual(desk.extract_facts(raw, '0000000001')['concepts']['net_income']['prior']['val'], 9)

    def test_arithmetic_and_current_debt(self):
        results = desk.calculate(desk.extract_facts(fixture(), '0000000001'), 60)
        for key, expected in [('revenue_growth_pct', 20), ('operating_margin_pct', 20),
                              ('return_on_average_equity_pct', 24), ('debt_to_equity', .5),
                              ('free_cash_flow_USD', 22), ('price_to_earnings', 20)]:
            self.assertAlmostEqual(results[key]['value'], expected)
            self.assertIn(' = ', results[key]['arithmetic'])

    def test_missing_is_not_zero_and_nonpositive_eps_has_no_pe(self):
        raw = fixture()
        del raw['facts']['us-gaap']['LongTermDebtCurrent']
        raw['facts']['us-gaap']['EarningsPerShareDiluted']['units']['USD/shares'][0]['val'] = -1
        results = desk.calculate(desk.extract_facts(raw, '0000000001'), 60)
        self.assertIsNone(results['debt_to_equity']['value'])
        self.assertIsNone(results['price_to_earnings']['value'])

    def test_total_long_term_debt_does_not_double_count_current(self):
        raw = fixture()
        values = raw['facts']['us-gaap'].pop('LongTermDebtNoncurrent')
        raw['facts']['us-gaap']['LongTermDebt'] = values
        results = desk.calculate(desk.extract_facts(raw, '0000000001'))
        self.assertAlmostEqual(results['debt_to_equity']['value'], 20 / 60)
        self.assertIn('already included', results['debt_to_equity']['arithmetic'])

    def test_zero_denominator_and_missing_prior(self):
        raw = fixture()
        raw['facts']['us-gaap'][desk.CONCEPTS['revenue'][2][0]]['units']['USD'] = [annual(0)]
        facts = desk.extract_facts(raw, '0000000001')
        self.assertIsNone(facts['prior_period'])
        results = desk.calculate(facts)
        self.assertIsNone(results['operating_margin_pct']['value'])
        self.assertIsNone(results['return_on_average_equity_pct']['value'])


class FilingTests(unittest.TestCase):
    def test_index_accepted_and_exhibit(self):
        html = '''<div class="infoHead">Accepted</div><div class="info">2026-01-02 16:12:34</div>
        <table class="tableFile"><tr><td>2</td><td>Earnings release</td>
        <td><a href="/Archives/edgar/data/1/release.htm">release.htm</a></td><td>EX-99.1</td></tr></table>'''
        accepted, documents = desk.index_details(html, 'https://www.sec.gov/index.html')
        self.assertEqual(accepted, '2026-01-02 16:12:34')
        self.assertEqual(documents[0]['type'], 'EX-99.1')
        self.assertTrue(desk.has_item_202('Item 2.02 Results of Operations'))
        self.assertFalse(desk.has_item_202('Item 2.020'))

    def test_text_keeps_inline_prose_and_table_values(self):
        text = desk.plain_text('<p>Total revenue was <b>$120</b> million.</p>'
                              '<table><tr><td>Diluted EPS</td><td>$3.00</td></tr></table>')
        self.assertIn('Total revenue was $120 million.', text)
        self.assertIn('Diluted EPS | $3.00', text)

    def test_release_prefers_total_quarter_over_segments_and_outlook(self):
        text = ('Third-quarter results\nTotal revenue was $120 million.\n'
                'Diluted earnings per share were $3.00.\n'
                'Segment results\nSoftware revenue was $20 million.\n'
                'Full-year outlook\nTotal revenue expected to be $500 million.')
        result = desk.release_lines(text)
        self.assertEqual(result['revenue'][0]['text'], 'Total revenue was $120 million.')
        self.assertEqual(result['diluted_eps'][0]['text'], 'Diluted earnings per share were $3.00.')

    def test_submissions_archives_are_included(self):
        class Client:
            def json(self, url):
                if url.endswith('archive.json'):
                    return {'accessionNumber': ['old'], 'form': ['10-K'], 'filingDate': ['2020-01-01']}
                return {'filings': {'recent': {'accessionNumber': ['new'], 'form': ['8-K'],
                        'filingDate': ['2026-01-01']}, 'files': [{'name': 'archive.json'}]}}
        self.assertEqual([r['accessionNumber'] for r in desk.filing_history(Client(), '0000000001')], ['new', 'old'])

    def test_release_retains_total_eps_and_continuing_operations_labels(self):
        text = ('Third quarter\nDiluted earnings per share: continuing operations | $3.01\n'
                'EARNINGS PER SHARE\nAssuming dilution\nContinuing operations | $3.01\n'
                'Discontinued operations | ($0.01)\nTOTAL | $3.00')
        result = desk.release_lines(text)['diluted_eps'][0]
        self.assertEqual(result['text'], 'Assuming dilution')
        self.assertIn('TOTAL | $3.00', result['context'])

    def test_item_202_verified_in_document_not_only_metadata(self):
        class Response:
            def __init__(self, text):
                self.content = text.encode()
        class Client:
            def get(self, url):
                if url.endswith('-index.html'):
                    return Response('<div class="infoHead">Accepted</div><div class="info">2026-01-01 12:00:00</div>')
                return Response('<p>Item 2.02 Results of Operations</p>' if 'good' in url else '<p>Item 8.01 Other Events</p>')
        rows = [dict(form=f, accessionNumber=f'0000000001-26-00000{i}', primaryDocument=p)
                for i, (f, p) in enumerate([('10-K', 'annual.htm'), ('10-Q', 'quarter.htm'),
                                           ('8-K', 'bad.htm'), ('8-K', 'good.htm')], 1)]
        result = desk.select_filings(Client(), '0000000001', rows)
        self.assertEqual(result['8-K']['primaryDocument'], 'good.htm')

    def test_user_agent_present_on_requests_redirects_and_retries(self):
        class Response:
            content = b'{}'
            def __init__(self, status, location=None):
                self.status_code = status
                self.is_redirect = location is not None
                self.headers = {'Location': location} if location else {}
            def raise_for_status(self):
                pass
        client = desk.SecClient('Fixture contact fixture@example.invalid')
        headers = []
        replies = iter([Response(302, 'https://data.sec.gov/redirect'), Response(429), Response(200)])
        def get(url, **kwargs):
            headers.append(client.session.headers['User-Agent'])
            return next(replies)
        with patch.object(client.session, 'get', side_effect=get), patch.object(desk.time, 'sleep'):
            client.get('https://www.sec.gov/start')
        self.assertEqual(headers, ['Fixture contact fixture@example.invalid'] * 3)

    def test_step_five_fetches_only_facts_and_saves_beside_run(self):
        class Client:
            def __init__(self):
                self.urls = []
            def json(self, url):
                self.urls.append(url)
                if url.endswith('company_tickers.json'):
                    return {'0': {'ticker': 'TEST', 'cik_str': 1, 'title': 'Fixture issuer'}}
                if 'companyfacts' in url:
                    return fixture()
                raise AssertionError('Unneeded prerequisite fetched')
        args = desk.argparse.Namespace(ticker='TEST', peers=[], price=60, step=5)
        with tempfile.TemporaryDirectory() as directory, patch.object(desk, 'ROOT', Path(directory)):
            client = Client()
            run = desk.Desk(client, args)
            with contextlib.redirect_stdout(io.StringIO()):
                run.step5()
            self.assertEqual(len(client.urls), 2)
            self.assertTrue((run.folder() / 'facts.json').exists())
            self.assertTrue((run.folder() / 'calculations.json').exists())


if __name__ == '__main__':
    unittest.main()
