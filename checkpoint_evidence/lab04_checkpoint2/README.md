Lab 04 — Checkpoint 2: seeded-error evidence

**The seeded EPS test passed. The full report still needs review.**

For the year ended August 30, 2026, the saved 10-K states diluted EPS of **$20.76 per share**. A separate test copy changed claim `N00157` and its quoted source text to **$21.76**, exactly $1.00 higher. The saved filing texts and facts were not changed.

The Verifier marked the seeded EPS **wrong** in both code and semantic checks and corrected it to **$20.76**, with the real per-share source at **10-K:L615** beside the correction. All eligible semantic checks finished. The correction uses the unchanged saved fact and independently checked original line; it does not trust the model’s malformed proposed number.

This result does **not** mean that the full report passed. Its final marks are **226 correct, 57 unsupported, and 4 wrong**, with **59 unresolved claims** and status **NEEDS_REVIEW**.

Files:

- `seeded_report.md`: complete test input report, including the false EPS quotation.
- `verified_report.md`: complete output report and marks table.
- `verification_marks.json`: every numerical verification mark.
- `run_status.json`: completion status; the final correction replay reused completed responses.
- `seeded_eps_result.json`: selected mark, period, accession, saved fact, source hashes and provenance.
- `original_eps_source.md`: exact original EPS line, period headers and official SEC links.
- `SHA256SUMS`: integrity hashes for the evidence files.

The reports and marks are byte-for-byte copies of the saved test artifacts. Raw run folders remain local and Git-ignored. No API key, `.env`, credential file or request header is included.
