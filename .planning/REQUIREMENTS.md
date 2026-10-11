# Requirements

- JSON-01: Versioned typed page/text/table/cell/figure JSON; true blanks distinguished from unknowns.
- DIRECT-01: AnyDoc first, automatic difficult-page routing to Vision.
- AGENT-01: Actual FastAgent extraction and review, explicit configured providers.
- REVIEW-01: Independent context; source-image audit of all 11 categories and independent row/column counts.
- REPAIR-01: Defects lead to bounded automatic repair; no silent fixes/manual edits.
- STATE-01: Durable drafts, reviews, errors, source identity, resumable verified pages and finite run deadlines.
- EXPORT-01: HTML and XLSX derive only from JSON; unreviewed results refused by default.
- DELIVERY-01: Public source, no attached/user documents, no provider credentials; published main and real CLI proof.

Acceptance: source page 78 yields JSON through the real CLI, source numbers/nulls remain faithful, reviewer catches a deliberately corrupted candidate, JSON exports reopen correctly, no fake GREEN for timeout/unresolved issue.
