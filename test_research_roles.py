"""Role isolation, tools, provenance, bounded repairs, and report checks without API calls."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import equity_desk
from research_roles import (ADVISOR, ADVISOR_SCHEMA, CATALOGUE, FINANCIAL, MANAGER, OWNERS,
                            PARTS, RESEARCH, ModelCalls, SourceBundle, StrategyManager,
                            check_claim, exhibit_mda_ranges, section_ranges)
from test_equity_desk import fixture


class FixtureDesk:
    def __init__(self, folder):
        self._folder = folder
        self.args = SimpleNamespace(ticker='TEST', price=60, peers=['PEER'])
        self.stamp = '2026-10-29_12-00-00-0400'
        self._facts = equity_desk.extract_facts(fixture(), '0000000001')
        annual = ('Item 1. Business | contents\nItem 1A. Risk Factors | contents\n'
                  'Item 7. MD&A | contents\nItem 8. Financial Statements | contents\n'
                  'Item 1. Business\nThe issuer sells products through a subscription model.\n'
                  + ('Competition depends on service and distribution capabilities.\n' * 4)
                  + 'Item 1A. Risk Factors\nRisk text.\nItem 7. Management Discussion\n'
                  + ('Management expects product investment to support growth, subject to demand risks.\n' * 4)
                  + 'Item 7A. Market Risk\nOther text.')
        (folder / '10-K.txt').write_text(annual)
        release = ('Quarter results\nThree months ended December\nTotal revenue was $120 million.\n'
                   'Diluted earnings per share were $3.00.\nGAAP and non-GAAP measures differ.\n'
                   'Management expects distribution investment to support growth, subject to execution risk.')
        (folder / 'earnings_release_99_1.txt').write_text(release)
        equity_desk.save_json(folder / 'release_lines.json', equity_desk.release_lines(release))
        equity_desk.save_json(folder / 'companyfacts_raw.json', fixture())
        equity_desk.save_json(folder / 'calculations.json', equity_desk.calculate(self._facts, 60))
        equity_desk.save_json(folder / 'peer_0000000002_companyfacts_raw.json', fixture())
        peer_facts = equity_desk.extract_facts(fixture(), '0000000002')
        equity_desk.save_json(folder / 'peers.json', {'PEER': {'company': {'cik': '0000000002',
                             'ticker': 'PEER', 'title': 'Peer fixture'}, 'facts': peer_facts,
                             'operating_margin_pct': equity_desk.calculate(peer_facts)['operating_margin_pct']}})

    def folder(self):
        return self._folder

    def company(self):
        return {'title': 'Subject fixture'}

    def facts(self):
        return self._facts

    def selections(self):
        return {form: {'accessionNumber': f'0000000001-26-00000{i}', 'reportDate': '2025-12-31'}
                for i, form in enumerate(['10-K', '10-Q', '8-K'], 1)}


class FakeCalls:
    def __init__(self, repair=False, invalid=False):
        self.requests = []
        self.repair = repair
        self.invalid = invalid
        self.reviews = 0

    def call(self, role, packet, schema, calculator=None):
        self.requests.append((role, deepcopy(packet)))
        if role == MANAGER and 'catalogue' in packet['context']:
            return {name: {'task': 'Perform your assigned analysis using only supplied context.',
                           'context': groups, 'expected_output': 'Return cited claims and limitations.'}
                    for name, groups in CATALOGUE.items()}
        if role == MANAGER:
            self.reviews += 1
            return {'checks': [{'part': part, 'passed': not (self.repair and self.reviews == 1
                                and part in [PARTS[1], PARTS[2]]),
                                'issues': ['Clarify the conditions.'] if self.repair and self.reviews == 1
                                and part in [PARTS[1], PARTS[2]] else []} for part in PARTS]}
        if role == RESEARCH:
            assert set(packet['context']) == {'business', 'mda', 'release'}
            source = next(s for s in packet['context']['business'] if 'subscription' in s['quote'])
            quote = 'not a real source quotation' if self.invalid else source['quote']
            return {'parts': [{'title': title, 'claims': [{'text': 'The business uses a subscription model.',
                    'evidence': [{'source_id': source['source_id'], 'quote': quote}], 'calculation_ids': []}]}
                    for title in packet['expected_output']['parts']], 'metric_ids': []}
        if role == FINANCIAL:
            assert set(packet['context']) == {'facts', 'ratios', 'quarter', 'peers', 'definitions', 'price'}
            source = packet['context']['ratios'][1]
            extra = calculator({'ratio': 'net_margin_pct', 'entity': 'subject', 'period': 'current'})
            return {'parts': [{'title': PARTS[2], 'claims': [{'text': 'Operating profitability is supported by the cited measure.',
                    'evidence': [{'source_id': source['source_id'], 'quote': source['quote']}],
                    'calculation_ids': [source['source_id']]}]}],
                    'metric_ids': packet['expected_output']['required_metric_ids'] + [extra['source_id']]}
        assert role == ADVISOR
        assert set(packet['context']) == {'research_analyst', 'financial_analyst'}
        return {'thesis': 'The cited profitability supports the thesis, subject to demand risk.',
                'recommendation': 'Hold', 'deciding_metric_id': 'ratio:subject:operating_margin_pct',
                'rationale': 'The cited operating margin is the deciding measure; the evidence does not establish a price target.'}


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.desk = FixtureDesk(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def test_section_selection_avoids_contents_and_other_items(self):
        text = (self.folder / '10-K.txt').read_text()
        selected = [text.splitlines()[i] for i in section_ranges(text, '1')]
        self.assertIn('The issuer sells products through a subscription model.', selected)
        self.assertNotIn('Item 1A. Risk Factors', selected)
        self.assertNotIn('Item 1. Business | contents', selected)

    def test_missing_section_fails_without_full_document_fallback(self):
        with self.assertRaises(ValueError):
            section_ranges('No recognizable section heading.', '7')

    def test_incorporated_mda_is_limited_to_its_section(self):
        text = ('Financial report\nManagement’s Discussion and Analysis\n' +
                'Management discusses operating results and liquidity, subject to execution risk.\n' * 4 +
                'Consolidated Income Statement\nOther financial statement text.')
        indices = exhibit_mda_ranges(text)
        lines = text.splitlines()
        self.assertTrue(lines[indices[0]].startswith('Management'))
        self.assertNotIn('Consolidated Income Statement', [lines[i] for i in indices])

    def test_incorporated_mda_download_has_same_accession_and_own_lines(self):
        annual = (self.folder / '10-K.txt').read_text()
        start = annual.index('Item 7. Management Discussion')
        (self.folder / '10-K.txt').write_text(annual[:start] +
            'Item 7. Management Discussion\nRefer to the annual report to stockholders for the complete '
            'discussion of financial results and liquidity, which is incorporated herein by reference.\n'
            'Item 7A. Market Risk\nOther text.')
        exhibit = ('Management’s Discussion and Analysis\n' +
                   'Operating results reflect investment and execution risk.\n' * 5 +
                   'Consolidated Income Statement\nStatement text.')
        selections = self.desk.selections()
        selections['10-K']['index_url'] = 'https://www.sec.gov/fixture-index.html'
        html = ('<div class="infoHead">Accepted</div><div class="info">2026-01-01 12:00:00</div>'
                '<table class="tableFile"><tr><td>2</td><td>Annual report</td>'
                '<td><a href="/fixture.htm">exhibit.htm</a></td><td>EX-13</td></tr></table>')
        self.desk.selections = lambda: selections
        self.desk.client = SimpleNamespace(get=lambda url: SimpleNamespace(content=html.encode()))
        def download(name, url):
            (self.folder / (name + '.txt')).write_text(exhibit)
            return exhibit
        self.desk.download = download
        bundle = SourceBundle(self.desk)
        record = bundle.sources[bundle.groups['mda'][1]]
        self.assertEqual(record['document'], '10-K_exhibit_13_1')
        self.assertEqual(record['filing'], selections['10-K']['accessionNumber'])
        self.assertEqual(len(bundle.additional_documents), 1)

    def test_sources_keep_line_numbers_filing_and_period(self):
        bundle = SourceBundle(self.desk)
        source = next(s for s in bundle.context(['business'])['business'] if 'subscription' in s['quote'])
        self.assertEqual(source['quote'], (self.folder / '10-K.txt').read_text().splitlines()[source['line']-1])
        self.assertEqual(source['filing'], '0000000001-26-000001')
        self.assertEqual(source['period_end'], '2025-12-31')
        self.assertNotIn('context', source)

    def test_calculator_uses_only_registered_operands_and_keeps_arithmetic(self):
        bundle = SourceBundle(self.desk)
        result = bundle.calculator({'ratio': 'net_margin_pct', 'entity': 'subject', 'period': 'current'})
        self.assertEqual(result['value'], 10)
        self.assertEqual(result['arithmetic'], '12 / 120 * 100 = 10')
        self.assertEqual(len(result['inputs']), 2)
        self.assertTrue(all(s['filing'] for s in result['inputs']))
        with self.assertRaises(ValueError):
            bundle.calculator({'ratio': 'net_margin_pct', 'entity': 'subject', 'period': 'current', 'value': 999})
        with self.assertRaises(ValueError):
            bundle.calculator({'ratio': '__import__', 'entity': 'subject', 'period': 'current'})

    def test_financial_model_cannot_publish_its_own_numerical_literals(self):
        bundle = SourceBundle(self.desk)
        source = bundle.context(['facts'])['facts'][1]
        claim = {'text': 'Revenue increased 999 percent.', 'evidence': [{'source_id': source['source_id'],
                 'quote': source['quote']}], 'calculation_ids': []}
        self.assertTrue(check_claim(claim, bundle.sources, set(bundle.sources), FINANCIAL))

    def test_complete_run_isolated_roles_and_report_header(self):
        calls = FakeCalls()
        manager = StrategyManager(self.desk, 'not-a-secret', 'fixture-model', calls=calls)
        with contextlib.redirect_stdout(io.StringIO()):
            path = manager.run()
        report = path.read_text()
        lines = report.splitlines()
        self.assertTrue(lines[0].startswith('Filings read: '))
        self.assertIn('Exhibit 99.1 0000000001-26-000003', lines[0])
        self.assertEqual(lines[1], 'Run time: ' + self.desk.stamp)
        for part in PARTS:
            self.assertEqual(report.count('## ' + part + '\n'), 1)
        self.assertIn('**Hold**', report)
        self.assertIn('period_end=2025-12-31', report)
        self.assertIn('tag=us-gaap:', report)
        self.assertIn('24 / 120 * 100 = 20', report)
        self.assertEqual([r for r, p in calls.requests], [MANAGER, RESEARCH, FINANCIAL, ADVISOR, MANAGER])
        self.assertTrue((self.folder / 'review_final.json').exists())
        advisor = next(p for r, p in calls.requests if r == ADVISOR)
        self.assertEqual(set(advisor['context']), {'research_analyst', 'financial_analyst'})
        self.assertNotIn('facts', advisor['context'])
        self.assertIn('metrics', advisor['context']['financial_analyst'])

    def test_failing_parts_return_to_owner_once_and_advisor_refreshes(self):
        calls = FakeCalls(repair=True)
        with contextlib.redirect_stdout(io.StringIO()):
            StrategyManager(self.desk, 'not-a-secret', 'fixture-model', calls=calls).run()
        roles = [r for r, p in calls.requests]
        self.assertEqual(roles.count(RESEARCH), 2)
        self.assertEqual(roles.count(FINANCIAL), 2)
        self.assertEqual(roles.count(ADVISOR), 2)
        research_packets = [p for r, p in calls.requests if r == RESEARCH]
        self.assertEqual(research_packets[-1]['expected_output']['parts'], [PARTS[1]])
        self.assertIn('Revise only these failing parts once.', research_packets[-1]['task'])

    def test_code_failures_cannot_be_overridden_and_invalid_claims_withheld(self):
        calls = FakeCalls(invalid=True)
        with contextlib.redirect_stdout(io.StringIO()):
            path = StrategyManager(self.desk, 'not-a-secret', 'fixture-model', calls=calls).run()
        report = path.read_text()
        self.assertIn('DRAFT', report)
        self.assertIn('Unsupported claim withheld', report)
        self.assertNotIn('> not a real source quotation', report)
        self.assertEqual(sum(r == RESEARCH for r, p in calls.requests), 2)

    def test_no_credentials_in_saved_role_data(self):
        calls = FakeCalls()
        with contextlib.redirect_stdout(io.StringIO()):
            StrategyManager(self.desk, 'unique-secret-test-key', 'fixture-model', calls=calls).run()
        for path in self.folder.glob('*.json'):
            self.assertNotIn('unique-secret-test-key', path.read_text())


class Response:
    def __init__(self, text='', calls=None):
        self.output_text = text
        self.status = 'completed'
        self.output = calls or []

    def model_dump(self, **kwargs):
        return {'status': self.status, 'output_text': self.output_text,
                'output': [item.model_dump() for item in self.output]}


class ToolCall:
    type = 'function_call'
    name = 'calculator'
    arguments = '{"ratio":"net_margin_pct","entity":"subject","period":"current"}'
    call_id = 'call_fixture'

    def model_dump(self, **kwargs):
        return {'type': self.type, 'name': self.name, 'arguments': self.arguments, 'call_id': self.call_id}


class SDKTests(unittest.TestCase):
    def test_responses_schema_stateless_calls_and_function_call_return(self):
        requests = []
        responses = iter([Response(calls=[ToolCall()]), Response('{"done":true}'), Response('{"done":true}')])
        def create(**kwargs):
            requests.append(deepcopy(kwargs))
            return next(responses)
        with tempfile.TemporaryDirectory() as folder:
            client = SimpleNamespace(responses=SimpleNamespace(create=create))
            caller = ModelCalls('never-saved', 'fixture-model', Path(folder), client=client)
            packet = {'task': 'Analyze.', 'context': {'facts': []}, 'expected_output': 'JSON'}
            with contextlib.redirect_stdout(io.StringIO()):
                caller.call(FINANCIAL, packet, ADVISOR_SCHEMA, calculator=lambda a: {'value': 10})
                caller.call(ADVISOR, packet, ADVISOR_SCHEMA)
            self.assertEqual(requests[0]['text']['format']['type'], 'json_schema')
            self.assertFalse(requests[0]['store'])
            self.assertEqual(requests[1]['input'][-1]['type'], 'function_call_output')
            self.assertEqual(requests[1]['input'][-1]['call_id'], 'call_fixture')
            self.assertEqual(set(json.loads(requests[1]['input'][-1]['output'])),
                             {'task', 'context', 'expected_output'})
            self.assertEqual(len(requests[2]['input']), 1)
            self.assertNotIn('tools', requests[2])
            for path in Path(folder).rglob('*.json'):
                self.assertNotIn('never-saved', path.read_text())

    def test_sdk_exception_body_is_not_printed_or_saved(self):
        def create(**kwargs):
            raise Exception('secret-from-error-body')
        with tempfile.TemporaryDirectory() as folder:
            caller = ModelCalls('key', 'fixture-model', Path(folder),
                                client=SimpleNamespace(responses=SimpleNamespace(create=create)))
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError) as error:
                    caller.call(RESEARCH, {'task': 'test', 'context': {}, 'expected_output': {}}, ADVISOR_SCHEMA)
            self.assertNotIn('secret-from-error-body', str(error.exception))


class CommandTests(unittest.TestCase):
    def test_full_command_runs_seven_steps_then_roles(self):
        order = []
        desk = SimpleNamespace(_folder=None)
        for step in range(1, 8):
            setattr(desk, f'step{step}', lambda step=step: order.append(step))
        config = {'SEC_USER_AGENT': 'Fixture fixture@example.invalid', 'API_KEY': 'fixture-api-key'}
        with patch.object(equity_desk.sys, 'argv', ['equity_desk.py', 'TEST', '--peers', 'PEER', '--price', '60']), \
             patch.object(equity_desk, 'dotenv_values', return_value=config), \
             patch.object(equity_desk, 'Desk', return_value=desk), \
             patch('research_roles.run_roles') as roles, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(equity_desk.main(), 0)
        self.assertEqual(order, list(range(1, 8)))
        roles.assert_called_once_with(desk, 'fixture-api-key', 'gpt-5.4')

    def test_data_only_needs_no_api_key_and_makes_no_model_calls(self):
        order = []
        desk = SimpleNamespace(_folder=None)
        for step in range(1, 8):
            setattr(desk, f'step{step}', lambda step=step: order.append(step))
        with patch.object(equity_desk.sys, 'argv', ['equity_desk.py', 'TEST', '--data-only']), \
             patch.object(equity_desk, 'dotenv_values', return_value={'SEC_USER_AGENT': 'Fixture fixture@example.invalid'}), \
             patch.object(equity_desk, 'Desk', return_value=desk), \
             patch('research_roles.run_roles') as roles, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(equity_desk.main(), 0)
        self.assertEqual(order, list(range(1, 8)))
        roles.assert_not_called()


if __name__ == '__main__':
    unittest.main()
