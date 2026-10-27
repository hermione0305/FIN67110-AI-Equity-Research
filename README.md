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
including redirects and retries. It does not use or print `API_KEY`.

The program prints seven steps: ticker resolution; filing history and selection;
source and text downloads; annual facts; arithmetic; quarterly release lines; and
peer facts and operating margins. `--peers` accepts space-separated or comma-separated
tickers. `--price` is a positive USD price per share.

To run one step, use, for example:

```bash
python3 equity_desk.py IBM --step 5 --price 250
```

A single step fetches its necessary inputs quietly. It does not require an earlier
run or print other step headings. Step 7 requires `--peers` to produce peer facts.

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
