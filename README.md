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

## SEC equity-research data desk

Install and run from this folder (Python 3.10 or later):

```bash
python3 -m pip install -r requirements.txt
python3 equity_desk.py IBM --peers MSFT ORCL --price 250
```

The tickers and price above are example inputs. The code contains no company-specific
rules. Set `SEC_USER_AGENT` in `.env` to your name and real contact email. The program
reads that file beside the script and sends the value on every HTTP request,
including redirects and retries. For a full run, it reads `API_KEY` from the same `.env` file and uses the official OpenAI Python SDK. Neither credential is printed or included in model inputs.

The program prints seven steps: ticker resolution; filing history and selection;
source and text downloads; annual facts; arithmetic; quarterly release lines; and
peer facts and operating margins. It then runs the four model roles and prints the path to `report.md`. `--peers` accepts space-separated or comma-separated
tickers. `--price` is a positive USD price per share.

To run one step, use, for example:

```bash
python3 equity_desk.py IBM --step 5 --price 250
```

A single step fetches its necessary inputs quietly. It does not require an earlier
run or print other step headings. Model roles do not run with `--step`. Step 7 requires `--peers` to produce peer facts.

Each run saves its data under `research_data/<company>_<date>_<time>/`. This includes
run parameters, filing lists, selected filing URLs and Accepted timestamps, raw
company-facts JSON, selected facts and their source filings, calculations, release
line matches, and peer facts when those steps need them. Step 3 saves the 10-K,
10-Q, Item 2.02 8-K, and Exhibit 99.1 in both source and plain-text form. Generated
data and `.env` are excluded from Git. No commits are made.

The full submissions history, including older history files, is searched. The
latest original 10-K and 10-Q are selected; amendments are not substituted. The
8-K document itself must contain Item 2.02, and its index must identify Exhibit
99.1. Accepted times come from each index page and retain its displayed time.
If a selected filing or exhibit is absent, the program reports it; it does not
silently use an older release. Other independent steps can still run.

Facts use supported US-GAAP tags and USD units. The tag with the newest annual
period wins within each concept; the listed candidate order breaks ties. Revenue
sets the current and prior fiscal-year date ranges. Duration facts must match
both dates; balance-sheet facts must match the period end. The `fy` field on a
comparative fact is not used to assign its period. Latest-filed annual comparatives
are used, so later restatements can change prior-year values. The output is a
current-data run, not a historical as-of backtest. Unsupported custom tags, absent
facts, and unmatched periods appear as unavailable, never as zero. Some equity
and net-income fallback tags include noncontrolling interests; the printed tags
identify the actual definitions used. Peer fiscal calendars can differ.

The calculator prints these formulas with actual operands:

- Revenue growth: `(current revenue / prior revenue - 1) * 100`.
- Operating margin: `operating income / revenue * 100`.
- Return on average equity: `net income / ((current equity + prior equity) / 2) * 100`.
- Debt/equity: `(noncurrent long-term debt + current maturities) / equity`. If the
  selected tag is `LongTermDebt`, current maturities are already included and are
  not added a second time. This measure excludes unrelated short-term borrowings.
- Free cash flow: `operating cash flow - payments to acquire property, plant and equipment`.
- P/E: `--price / annual diluted EPS`. This uses fiscal-year EPS, not trailing
  twelve-month EPS. P/E is unavailable for zero or negative EPS. Return on equity
  and debt/equity are unavailable for zero or negative equity denominators.

Step 6 uses text rules to locate quarter revenue and diluted-EPS lines. It prints
verbatim lines and nearby labels/values. Review the context when tables contain
multiple periods, continuing operations, or GAAP and non-GAAP measures. PDF exhibits
with text are supported; image-only PDFs require OCR, which is not included.

Run offline checks with `python3 -m unittest -v test_equity_desk.py`.

SEC API reference: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

The requested design reference is Francis & Zhang (2026), Section 3.1,
https://doi.org/10.1016/j.frl.2026.110127. Full-text access was blocked during this
implementation. The seven-step requirements supplied in the task define this
program; equivalence to the paper's full Section 3.1 has not been verified.


## Four model roles

A full run now calls the official OpenAI SDK after all seven data steps succeed:

```bash
python3 -m pip install -r requirements.txt
python3 equity_desk.py COST --peers WMT,TGT,BJ --price 1000
```

The price is an example USD input. Set `API_KEY` and `SEC_USER_AGENT` in `.env`.
The default model is `gpt-5.4`; use `--model MODEL_ID` to change it. Each role has
separate instructions and its own stateless Responses API calls with strict JSON
output schemas. Tool continuations stay within the Financial Analyst's conversation.
`store=False` is used on Responses requests. The program does not log the API key.

The Strategy Manager first allocates tasks and approved source groups. The
coordinator expands those groups into a JSON packet with `task`, `context`, and
`expected_output`. There is no shared model history, browsing tool, file-access
tool, or automatically forwarded whole workspace.

- **Research Analyst:** Receives only the annual report's Item 1 Business and
  Item 7 MD&A and the earnings release, with original plain-text line numbers
  and accession numbers. It covers the business model, competitive position,
  catalysts and recent developments. Every claim must quote a supplied source
  line. The extractor selects the longest Item section to avoid the contents
  page. If a short Item 7 incorporates an annual report by reference, the desk
  downloads Exhibit 13 and locates its MD&A. If that section cannot be found,
  the role workflow stops instead of substituting unrelated text.
- **Financial Analyst:** Receives the annual facts, ratios, quarter source lines,
  peer facts/margins, definition records, and supplied price. Numerical literals
  are prohibited in model-authored claim prose. The report renderer inserts
  the selected numerical records, including their filing, tag or line, period,
  units, and Python arithmetic. Source quotes retain their original numbers.
  The analyst must state the definition used where the sources offer alternatives.
  It can call an allowlisted calculator for net margin, operating-cash-flow/net-income
  conversion, and capital-expenditure/revenue, for the current or prior period
  and the subject or a peer. Python uses registered facts; the model cannot supply
  numerical operands or executable expressions.
- **Investment Advisor:** Receives only the two analysts' outputs, including the
  Financial Analyst's approved numerical records. It supplies a thesis, Buy/Hold/Sell,
  and exactly one deciding metric ID. Python inserts that metric's actual value
  and provenance. The advisor cannot introduce numerical thresholds or calculate.
- **Strategy Manager:** Reviews presence and consistency of all five required
  parts. It sends failed parts to their owning role once. If an analyst changes,
  the advisor is refreshed once using the updated analyst outputs. A final review
  follows revisions. The manager's compiler assembles the report without another
  unconstrained prose rewrite. Code checks cannot be overridden by a model review.

The five report parts are Overview; Market Positioning and Growth Outlook;
Valuation Insights; Future Developments and Strategic Recommendations; and
Investment Recommendation. Research owns the first, second and fourth parts;
Financial owns Valuation Insights; the advisor owns Investment Recommendation.
The fourth part covers strategic developments and research implications; the
advisor supplies the final investment action.

The first report line lists the filings read and their accession numbers,
including any incorporated annual-report exhibit and the annual/peer fact
filings. The second line gives the run time. `report.md` is saved in the same
run folder as the texts and facts, and its path is printed.

The run folder also contains `roles/` request/response and calculator audit files,
`role_sources.json`, the three analyst/advisor JSON outputs, review JSON files,
and `additional_filings_read.json`. No API key or SEC User-Agent is sent as model
context. The model calls use the API key only for SDK authentication.

If a quote fails validation, that claim is withheld. If any issue remains after
the single revision pass, the report is marked DRAFT and lists the unresolved
issues. Its recommendation is withheld until all checks pass. Exact quotations,
source IDs, arithmetic and routing are checked in code; interpretation and
cross-role consistency also depend on the model review. This is not a guarantee
that every interpretation is correct.

To retain the original seven-step data workflow without OpenAI calls:

```bash
python3 equity_desk.py COST --peers WMT,TGT,BJ --price 1000 --data-only
```

Run offline tests without reading `.env` or calling either service:

```bash
python3 -m unittest -v test_equity_desk.py test_research_roles.py
```

The four roles follow the task's description of Francis & Zhang (2026), Figure 1.
Figure 1 itself was not accessible during implementation; the supplied role and
report requirements define this implementation.

Official SDK reference: https://developers.openai.com/api/reference/python
Structured outputs: https://developers.openai.com/api/docs/guides/structured-outputs
Function calling: https://developers.openai.com/api/docs/guides/function-calling
