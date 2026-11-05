# FIN67110 - AI Equity Research

Course: Mastering AI for Finance
Purdue University - Fall 2026

This repository contains my coursework and AI-assisted equity research projects.

## Tools
- Python
- OpenAI Codex CLI
- Google Antigravity CLI
- Orca

## Research
Equity research, financial statements, earnings analysis, and AI coding agents.

## Lab 04: fixed CrewAI agent team

Checkpoint 2 evidence is in [checkpoint_evidence/lab04_checkpoint2](checkpoint_evidence/lab04_checkpoint2/README.md).
The seeded diluted EPS test passed: the Verifier marked $21.76 wrong and corrected
it to the saved 10-K value of $20.76 per share for the year ended August 30, 2026.
The full report still needs review: 59 numerical claims remain unresolved.

Use Python 3.10–3.13. From this folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run the team with a ticker, peers, and an example USD price:

```bash
.venv/bin/python equity_desk.py COST --peers WMT,TGT,BJ --price 1000
```

The tickers and price are example inputs. No company is hardcoded in the Python
implementation. Omit `--peers` or `--price` if not available. P/E is unavailable
without a price. Peers accept commas or spaces. All runs include verification.
There is no `--data-only`, `--step`, or skip-verification option in this CLI.

Set `API_KEY` and `SEC_USER_AGENT` in the existing `.env` beside `equity_desk.py`.
The key authenticates only to Purdue GenAI Studio via the OpenAI-compatible Python
SDK. It is not added to graph state, model input, or audit files. SEC requests use `SEC_USER_AGENT`, including
retries and redirects. Verify-only needs `API_KEY` and does not contact the SEC.
`purdue_genai.json` selects `gpt-oss:120b`, confirmed available to this account.
The base URL is `https://genai.rcac.purdue.edu/api`, and the model endpoint is
`/chat/completions`. The SDK default `/v1` and the Responses endpoint are not used.
Provider retries are disabled to keep one request per visit. No paid-provider
fallback is configured or permitted. See `PURDUE_MODELS.md` for all discovered IDs.

The graph is `EquityTeamFlow` in `desk_flow.py`:

```text
Steps -> Research Analyst -> Financial Analyst -> Investment Advisor
      -> Strategy Manager -> Verifier
```

These are CrewAI Flow `@start`/`@listen` edges. There is no model router, hierarchical
crew, delegation, shared model conversation, or persistent memory. Direct Chat Completions SDK
calls inside Flow methods keep each analyst/Manager visit to one model call. The
mandatory Verifier node makes one model call per bounded semantic batch. Each role gets
only its JSON `task`, `context`, and `expected_output` packet. Its instructions
come from its own file in `roles/`. `roles/verifier.md` supplies verifier instructions.
The scaffold created by `crewai create flow desk_team` forwards to this graph.

The Steps node runs seven actual CrewAI `BaseTool` objects in order:

1. Resolve ticker to CIK from SEC's ticker list.
2. Read current and archived submissions, select the latest original 10-K and
   10-Q and latest 8-K whose document contains Item 2.02, and read Accepted times
   from the EDGAR index pages.
3. Download those filings and Exhibit 99.1; save sources and plain text.
4. Select annual facts and prior-year facts, with tags, dates, units and filings.
5. Calculate revenue growth, operating margin, return on average equity,
   debt/equity, free cash flow, and annual-EPS P/E in Python.
6. Locate quarter revenue and diluted-EPS lines and their nearby context.
7. Fetch peer facts and operating margins using the same calculation.

Step 4 chooses among the four supported US-GAAP USD revenue tags by newest
annual period end, then by candidate order to break ties. Annual duration facts
must come from 10-K/10-K/A and span 300–400 days inclusive. Revenue fixes the
current and prior fiscal-year windows for every concept. Latest-filed matching
comparatives are used. Missing values are unavailable, never zero. Custom tags
are not inferred, and peer fiscal calendars can differ.

The Research Analyst receives only Business, MD&A and the earnings release,
with original text line numbers. A short Item 7 that incorporates an annual
report causes the desk to fetch Exhibit 13 and identify its MD&A. An unidentifiable
section is reported as missing instead of substituting unrelated text.

The Financial Analyst receives annual facts, Python ratios, quarter source lines,
peer facts, accounting definitions, and the user price. All supported extra ratios
are precomputed by the graph calculator: net margin, cash-flow/net-income
conversion and capex/revenue, for current/prior periods and subject/peers. The
model cannot run tools or perform arithmetic. It selects metric IDs and quotes;
Python supplies the numbers and equations. Selected input tags and definitions
are included so GAAP/non-GAAP, total/continuing operations, debt including/excluding
current maturities and equity with/without noncontrolling interests can be checked.

The Investment Advisor receives only the two analyst outputs. It returns a thesis,
Buy/Hold/Sell, and one deciding metric ID. It cannot introduce a target or cutoff.

The Manager checks exactly these parts:

- Overview
- Market Positioning and Growth Outlook
- Valuation Insights
- Future Developments and Strategic Recommendations
- Investment Recommendation

Failed parts map to fixed owners in code. Inside the Manager node, one bounded
repair block visits Research, Financial, then Advisor in that fixed order, calling
only roles needing repair. Changed analyst output refreshes the Advisor once.
The Manager can make one final check, then Python compiles the report. No role
runs more than twice. A model returns checks, never a next-node name. The primary
graph order is the same on every run. The Manager has one bounded repair pass;
the mandatory Verifier node schedules its own bounded semantic batches in code.
Unresolved issues remain marked DRAFT. The Verifier always follows this block,
including after a failed role or unavailable Manager response.

## Verification and saved runs

Every accepted run gets a new `research_data/<company>_<date>_<time>_<unique-id>/`
folder. It saves the filing texts, facts, role outputs, each node/tool input and
output under `nodes/`, `report.md`, `verified_report.md`, and verification marks.
Existing run directories and original reports are not overwritten.

The report's first line lists filings and accession numbers; its second line is
the run time. The verified report retains the filings line and puts its marks
table directly below that line. The original report contains hidden numerical
source annotations; normal Markdown rendering hides them. They are claims to
check, not trusted evidence. Visible numbers without annotations are also audited.

The Verifier receives only the compiled report, saved filing texts and saved facts.
It cannot read analyst outputs, the source registry, Manager reviews, `.env`, or
fetch replacement data. It skips only the marked Advisor thesis, not the deciding
number or other report parts. Filing identifiers, source-location metadata and
run timestamps are provenance, not analytical quantities.

Code first checks exact XBRL value/tag/start/end/unit/accession against saved
facts. Line checks allow presentation spacing, Unicode normalization and common
accounting negative formatting. Ratios are recomputed from their quoted inputs
with a restricted arithmetic grammar, Decimal arithmetic and explicit six-place
rounding. Each input is checked against saved facts or its filing line. A ratio
without a definition is unsupported. Saved user price is identified as user input,
not an SEC fact.

One verifier model call then checks whether the line actually states that number
for the claimed period, unit and definition, including competing filing definitions.
A model cannot override a failed code check. Marks are `correct`, `wrong`, or
`unsupported`. Corrections must pass the same source checks; ratio corrections
select an allowlisted formula and Python computes them. If saved evidence cannot
prove a correction, the verified text says unsupported instead of inventing one.
A model outage leaves claims unapproved and still produces an audit report. Semantic
interpretation depends on the model; passing checks is not a guarantee of accuracy.

An API rejection is not a parsing success or a completed analyst report. Each
model visit records its failure stage and redacted API status/code/message.
Returned provider responses are saved before JSON/schema validation, when a
response exists. A failed repair preserves earlier analyst content. `run_status.json`
and the CLI distinguish `passed`, `needs_review`, and `failed`; a report with no
analyst content or no auditable numbers fails. The earlier OpenAI runs failed
with exhausted paid-API credits; those previous runs are preserved. This project
now targets Purdue only and never retries against a paid service.

To verify a saved run, replace the path below with that run's actual folder:

```bash
.venv/bin/python equity_desk.py --verify-only "/absolute/path/to/research_data/SAVED_RUN_FOLDER"
```

This uses a separate one-node `VerificationFlow`. It copies only the report,
saved filing texts and facts into another unique run folder. It runs no data
tools or analyst/Manager calls and leaves the source run unchanged.

## Validation

```bash
.venv/bin/python -m unittest -v test_equity_desk.py test_research_roles.py test_desk_verifier.py test_desk_flow.py test_live_failures.py test_purdue_api.py test_verifier_evidence.py
.venv/bin/python -m pip check
```

Tests use saved synthetic filings and stubbed SDK responses with the real CrewAI
Flow. They do not need a live SEC request or model call. The source/ratio tests,
call bounds, fixed order, correction safeguards, mandatory verification and
verify-only preservation are checked. Live model interpretation has not been
validated by the offline suite.

Design reference: Francis & Zhang (2026), https://doi.org/10.1016/j.frl.2026.110127.
The supplied role/graph requirements define this implementation; full Figure 1
access was unavailable. CrewAI is pinned to 1.15.34 because its Flow/memory API
was checked against that installed version.


## Purdue API connection check

```bash
.venv/bin/python check_purdue.py --list-only
.venv/bin/python check_purdue.py
```

The first command lists account models without generating text. The second lists
models and sends one short JSON request; neither starts the research Flow or a
COST report. Both save a key-free record under `provider_checks/`. A configured
model missing from the returned account list fails instead of selecting an
alternate provider.

Purdue uses `response_format.json_schema` for the configured vLLM model. The adapter
also supports the documented Ollama `format` field via `extra_body` if configuration
is explicitly changed to an available Ollama model/backend. The output limit is
`max_tokens=8192`, not Responses' `max_output_tokens`; the short check uses 256.
Requests use `stream=false` and no remote tools. The final answer is read from
`choices[0].message.content`, not reasoning fields or `output_text`. Local JSON
Schema validation still enforces the same role contracts. Empty/null, truncated,
refused and tool-call responses fail closed without adding a hidden model call.

The first live short request succeeded with `gpt-oss:120b`: HTTP 200, reply
`{"ok": true}`, finish reason `stop`. Its record is in
`provider_checks/purdue_short_request_observed.json`. Only short connection tests and
model discovery were run during migration; the full COST report was not run.
Full-report context/output limits and model interpretation still require separate
live validation before a report can be claimed successful.

Official Purdue API documentation: https://docs.rcac.purdue.edu/services/genai/api/


## Deployed context limits and report recovery

Purdue's deployed `gpt-oss:120b` limit is 65,536 tokens, including input and output.
The previously saved HTTP 400 used 120,188 input tokens; changing JSON parsing or
raising `max_tokens` does not repair an oversized input. All model requests now
have a local token-budget check including schema tokens, the output allowance,
and a 2,048-token safety margin. Oversized requests stop before the API call;
there is no silent input truncation. The first local
count may download the public tokenizer vocabulary; no key or report is sent
with that vocabulary download. Cache it before running offline tests.

The Verifier still runs all independent code checks against the FULL saved texts
and original facts. Its semantic batches cover every eligible number ID exactly
once, with at most twelve claims per batch and recursive splitting if a batch
exceeds the context budget. An incomplete multi-claim response is rejected and
split into smaller batches, down to single claims, without repeating the same
packet. Failed parent attempts remain saved; only complete leaf responses count
toward final coverage. Each receives its report claims, original saved
facts, original line-numbered citation windows and relevant statement,
period/unit, competing-definition and correction context, and omits an uncited
quarterly filing from annual-only claims. An uncited quarter claim keeps quarterly
correction context. Releases and cited documents remain available. Repeated
report annotation prose and taxonomy text use lossless references. The original
report and facts are not rewritten; regression tests check exact round trips.
Every batch input, output, evidence-selection manifest and request budget is
saved in the new run. If one claim and its evidence still cannot fit, it is
recorded as a failed batch rather than truncated. Missing, duplicate or failed
semantic responses prevent completed verification. `code_status` is independent
of `semantic_status`; `semantic_completed` records whether all batch checks
finished, not whether every reported claim is correct.
Verify-only can reuse an earlier completed response only when its full packet
and instructions match exactly and its schema and claim coverage are valid.
The copied cache and batch output record that provenance. Code checks always run
again; changed facts, report claims or instructions prevent reuse.

Quote matching allows whitespace, line wrapping and equivalent hyphen glyphs.
It preserves numerical tokens, signs, units and other punctuation; a match alone
cannot establish period or definition. Accounting identifiers such as ASC 450-30
are excluded, including when report annotations split their digits. Nearby dollar
amounts and financial negative numbers remain eligible.

Purdue errors can use a `detail` field rather than `error.message`. Both are now
recorded, redacted, with the HTTP error body. A repair with empty sections or
no supported replacements cannot erase an earlier supported draft; the Manager still
checks the retained content and keeps any unresolved failures.

A transport repair does not repair a failed analyst report. Check the saved
Manager review and actual sections before using verify-only as a recovery step.
Verify-only audits numbers; it cannot regenerate missing research sections or
turn failed Manager findings into a complete equity-research report.
