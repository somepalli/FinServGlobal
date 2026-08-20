# Task 09 — Sample transaction runs

## Build
`samples/` with the four assignment payloads as JSON, and
`scripts/run_samples.py` writing each `ComplianceAssessment` to
`samples/output/<name>.json` and a readable markdown summary.

Payloads:
1. Cross-border payment, $2M, non-KYC counterparty, high-risk jurisdiction
2. Intra-group derivative above the large exposure threshold
3. Retail investment in a complex product, no appropriateness assessment
4. NBFC lending requiring priority sector reporting

## Acceptance
- Each output cites at least one clause from the document the manifest says
  covers that scenario. This is the end-to-end correctness check.
- Outputs are committed. They are the "sample outputs" the submission asks for.
