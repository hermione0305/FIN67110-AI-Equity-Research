Company: Netflix, Inc. (NFLX); filings read: FY2025 10-K 0001065280-26-000034; Q3 2026 earnings release, Exhibit 99.1 to 8-K 0001065280-26-000290; peer company-facts extracts: DIS 0001744489-25-000155 and CMCSA 0001628280-26-004994.
fallback

Partner check 1 — claim: [partner fills]; filing evidence/location: [partner fills]; mark: [partner fills]; reviewer/date: [partner fills].
Partner check 2 — claim: [partner fills]; filing evidence/location: [partner fills]; mark: [partner fills]; reviewer/date: [partner fills].

# Netflix Equity Research Report

Generated: 2026-10-29T15:25:06-04:00. Data run: October 29, 2026, 15:21:27 -04:00.

Method: course-authorized chat fallback. The four role tasks are carried out in this chat; this is not a successful run of four isolated API model calls. Research Analyst uses the supplied business/MD&A text and earnings release; Financial Analyst uses the statements, saved facts and Python calculations; Investment Advisor uses their findings; Strategy Manager compiles the five sections. Human audit and partner checks remain pending. No marks are supplied by AI.

Source key: **K** = supplied `10-K.txt`, accession 0001065280-26-000034, filed January 23, 2026; **E** = supplied `earnings_release_99_1.txt`, Exhibit 99.1 to accession 0001065280-26-000290, filed October 20, 2026. Line references count physical lines in these exact text files from 1. SEC originals are linked below. The selected-filings metadata also lists a 10-Q, but that text was not used to author this fallback and is not represented as read. Peer information is from saved SEC company-facts extracts, not independently read full peer filings.

## Overview

*Research Analyst.* Netflix describes an entertainment offering spanning “TV series, films, games and live programming” [K L99]. Its membership model is explicit: revenues are “primarily derived from monthly membership fees” [K L102]. Its stated strategy combines compelling content, a range of plans including advertising, and an improved discovery experience [K L100: “including our ad-supported subscription plan”]. Analyst inference: recurring memberships and multiple monetization options support the business model, while retention depends on continually delivering entertainment value.

*Financial Analyst.* The latest annual filing supplied is for the year ended December 31, 2025; it must not be confused with the newer quarterly release. Annual flow periods are January 1–December 31, 2025 and January 1–December 31, 2024. Balance-sheet figures are at those respective year ends. USD thousands below reproduce the statement units, except EPS, which is USD/share. Every row is sourced to the Netflix 10-K accession given above. XBRL tags have the `us-gaap:` prefix.

| Annual fact | FY2025 / year end | FY2024 / year end | Tag or original statement definition | Source |
|---|---:|---:|---|---|
| Total revenues | 45,183,036.000 | 39,000,966.000 | `us-gaap:Revenues` | K L693 |
| Operating income | 13,326,603.000 | 10,417,614.000 | `us-gaap:OperatingIncomeLoss` | K L698 |
| Net income | 10,981,201.000 | 8,711,631.000 | `us-gaap:NetIncomeLoss` | K L704 |
| GAAP diluted EPS | 2.530 | 1.980 | `us-gaap:EarningsPerShareDiluted` | K L708 |
| Stockholders’ equity | 26,615,488.000 | 24,743,567.000 | `us-gaap:StockholdersEquity` | K L821 |
| Noncurrent long-term debt | 13,463,971.000 | 13,798,351.000 | `us-gaap:LongTermDebtNoncurrent` | K L811 |
| Cash provided by operating activities | 10,149,273.000 | 7,361,364.000 | `us-gaap:NetCashProvidedByUsedInOperatingActivities` | K L759 |
| Purchases of property and equipment: outflow magnitude | 688,220.000 | 439,538.000 | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` | K L761 |
| Short-term debt, balance-sheet carrying amount | 998,865 | 1,784,453 | Statement line “Short-term debt”; supplemental extraction from original text | K L808 |

The debt figures are carrying amounts, not the notes' aggregate principal amount. They exclude content obligations, lease liabilities, and other liabilities. The original statement shows purchases of property and equipment as negative cash flows; the table uses their positive magnitude for the free-cash-flow subtraction.

The latest quarter is the three months ended September 30, 2026, compared with September 30, 2025. The release's income statement uses USD thousands except per-share data [E L128–133]:

| Quarterly claim | Q3 2026 | Q3 2025 | Source |
|---|---:|---:|---|
| Total revenue, USD thousands | 12,874,176 | 11,510,307 | E L134 |
| GAAP diluted EPS, USD/share | 0.87 | 0.59 | E L148 |

Quarterly revenue growth, calculated in Python from the release's two comparable quarter columns, is `(12,874,176 / 11,510,307 - 1) * 100 = 11.849111%`. This is reported-currency growth, not foreign-exchange-neutral growth. The release's rounded summary reports 11.8% [E L20]. Share and per-share figures in the release are retroactively split-adjusted, as stated in its footnote [E L152]; do not mix them with unadjusted historical EPS.

## Market Positioning and Growth Outlook

*Research Analyst.* Netflix competes for both audience time and content. The annual filing calls its market “intensely competitive and subject to rapid change” [K L104], while management aims to improve both technology and content [K L105: “including both our technology and our content offerings”]. Analyst inference: Disney and Comcast are useful diversified entertainment comparators, but their consolidated businesses are not pure streaming comparables.

The latest release attributes growth to memberships, pricing, advertising and currency effects, stating “revenue growth was driven primarily by subscription revenue” [E L35]. Advertising technology is a prospective catalyst: management says it will “introduce our advertising tier to 15 new countries in 2027” [E L63]. This is a forward-looking management plan, not an achieved result. The release also cautions that growth in view hours needs improvement [E L64: “we do seek to accelerate growth in view hours”].

*Financial Analyst.* The saved peer calculator uses annual operating income / annual revenue, not adjusted EBITDA or segment profit. The values below are desk-selected XBRL facts, with their provenance retained for human review. The tags and periods are shown so that a reviewer can check whether each selected concept represents consolidated revenue and consolidated GAAP operating income in the underlying filing. A matching tag name alone is not proof of full accounting comparability.

| Company | Annual period | USD arithmetic: operating income / revenue × 100 | Source accession and tags |
|---|---|---|---|
| NFLX | 2025-01-01 to 2025-12-31 | `13,326,603,000 / 45,183,036,000 * 100 = 29.494705%` | K L693, L698; `Revenues`, `OperatingIncomeLoss` |
| DIS | 2024-09-29 to 2025-09-27 | `17,551,000,000 / 94,425,000,000 * 100 = 18.587239%` | [0001744489-25-000155](https://www.sec.gov/Archives/edgar/data/1744489/000174448925000155/0001744489-25-000155-index.html); `us-gaap:Revenues`, `us-gaap:OperatingIncomeLoss` |
| CMCSA | 2025-01-01 to 2025-12-31 | `20,672,000,000 / 123,707,000,000 * 100 = 16.710453%` | [0001628280-26-004994](https://www.sec.gov/Archives/edgar/data/1166691/000162828026004994/0001628280-26-004994-index.html); `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`, `us-gaap:OperatingIncomeLoss` |

Fiscal calendars and business mixes differ; the peer figures are not contemporaneous-quarter comparisons and do not establish relative valuation. No peer P/E figures were provided.

## Valuation Insights

*Financial Analyst.* The following ratios reproduce `calculations.json`, except the clearly labeled supplemental debt/equity calculation. USD operands are used below; the original statements above are in USD thousands. Annual flow and balance-sheet periods are the same as in Overview.

| Metric | Python arithmetic | Definitions and filing evidence |
|---|---|---|
| Annual revenue growth | `(45,183,036,000 / 39,000,966,000 - 1) * 100 = 15.851069` | Current/prior total revenue; K L693; percent |
| Operating margin | `13,326,603,000 / 45,183,036,000 * 100 = 29.494705` | Operating income / total revenue; K L698, L693; percent |
| Return on average equity | `10,981,201,000 / ((26,615,488,000 + 24,743,567,000) / 2) * 100 = 42.762473` | Net income / average of beginning and ending stockholders’ equity; K L704, L821; percent |
| Free cash flow | `10,149,273,000 - 688,220,000 = 9,461,053,000` | Operating cash flow minus purchases of property/equipment; K L759, L761; USD |
| Debt/equity — supplemental fallback calculator | `(13,463,971,000 + 998,865,000) / 26,615,488,000 = 0.543399` | Noncurrent debt plus current debt carrying amount / year-end stockholders’ equity; K L811, L808, L821; times |

The desk's original debt/equity output was unavailable because its supported current-maturities tag was missing. Fallback supplements it with the 10-K balance-sheet debt lines. The debt note reports no borrowings under the revolving facility or commercial-paper program at year end [K L494, L1148; see evidence file], supporting treatment of the reported short-term balance as current debt rather than adding unrelated commercial-paper borrowing. The MD&A separately lists short-term plus long-term debt of $14,462,836 thousand [K L487], consistent with the components used here. This supplement does not imply that the automated extraction has been fixed.

Free cash flow is a non-GAAP liquidity measure; the release defines it as operating cash flow less purchases of property and equipment [E L81]. Content-related cash payments remain reflected in operating cash flow; this definition does not subtract all content spending again. Return on equity uses average equity, not year-end equity alone.

**P/E is not calculated:** no share price was supplied in this data run. Annual GAAP EPS alone is insufficient to calculate P/E. No market-based fair value, target price, or forecast valuation multiple is invented.

## Future Developments and Strategic Recommendations

*Research Analyst.* Monitor execution of advertising, content discovery and pricing while distinguishing guidance from actual results. The annual strategy is to grow “within the parameters of our operating margin target” [K L100]. The latest release describes technology and monetization as priorities [E L42: “leveraging technology to improve all aspects of our service” and “improving our monetization”]. These are plausible growth levers, not guaranteed outcomes.

Advertising execution is a specific watch item: management reduced its advertising-revenue expectation “due to slightly slower than expected rollout of some ad product capabilities” [E L39]. Meanwhile, the latest quarter benefited from expense timing [E L36: “ahead of forecast due primarily to the timing of expenses”]. Analyst inference: the latest-quarter profitability should not automatically be treated as the sustainable full-year run rate.

*Investment Advisor.* Prioritize evidence of durable revenue growth, cash conversion and successful advertising execution before increasing exposure. Monitor debt alongside content commitments, rather than treating debt/equity as a complete measure of future cash obligations. These are conditional recommendations derived from the analyses above, not new numerical forecasts or management commitments.

## Investment Recommendation

*Investment Advisor: Hold.* The deciding number is the latest-quarter reported revenue growth of **11.849111%**, calculated by the Financial Analyst above from the earnings release. It supports continued business momentum. The Financial Analyst also reports positive annual free cash flow, while the Research Analyst identifies advertising execution and expense timing as reasons for caution. Without a market-price input or forward valuation model, this is a provisional qualitative Hold, not a conclusion that the shares are fairly priced. It assigns no price target.

*Strategy Manager.* The compiled report contains the five required parts, distinguishes annual and quarterly periods, states both revenue-growth calculations, uses average equity, and discloses the supplemental debt calculation and absent P/E input. Source citations and calculations are AI-prepared and remain subject to human audit. The partner-check fields above must be completed by the partner after checking two core claims against the original filings. The student's full eleven-claim audit remains due before Session 4.

Source links: [Netflix FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1065280/000106528026000034/nflx-20251231.htm); [October 2026 earnings release](https://www.sec.gov/Archives/edgar/data/1065280/000106528026000290/ex991_q326.htm).
