# Changelog

## v0.24 bidirectional completeness audit - 2026-10-21

- Added product-level notice-corpus completeness for all 25 products.
- Added bilingual notice-to-parameter and parameter-to-notice audit records.
- Separated partial verified records from products whose notice corpus is not yet built.
- Limited policy-like parameter candidates to majority/all-active-contract changes.
- Added a focused high-priority retrieval queue for recent all-active-contract gaps.
- Added per-product CSV export and static full/review-queue exports.

## v0.23 maintenance workflow - 2026-10-21

- Added edit, approve, reject and withdraw transitions for user-entered notices with optimistic record versions.
- Added ratio/unit, duplicate, URL and overlapping-interval validation.
- Added small JSON recovery snapshots before every mutable write and an append-only audit trail.
- Added idempotent runtime schema migrations and query indexes.
- Added a safe one-command incremental updater with plan-only and resume modes.
- Incremental parameter integration now appends change clusters for new official dates.
- Official data checked through 2026-10-21; the three-source complete analysis date is 2026-10-20.

## v0.22 complete interaction - 2026-10-18

- Added audited multi-parameter notice entry with effective start/end dates and pending-review provenance.
- Added combined verified/user policy intervals and parameter-level change visualization.
- Changed the product selector to direct code input with suggestions.
- Added deterministic latest-data gating and non-personalized trade-research-condition classification.
- Extended AI context/schema while retaining `trade_decision=not_assessed`.
- Added v0.22 artifact and regression tests; 26 tests pass.

## v0.21 evidence quality and multi-window audit - 2026-10-17

### Added

- Separate 71 parameter-level rows from 51 unique policy events.
- Five AO/BU contextual or administrative event records and eight screened notice-event links.
- A/B/U evidence grades and explicit mentor-review status.
- 204 normalized 1/5/10/20-trading-day window rows.
- A 51-row policy-overlap audit with contract-roll diagnostics.
- A deduplicated 33-event human review queue.

### Validation and scope

- Every policy event has four window definitions; all 1/5/10-day windows and 50 of 51 20-day windows are symmetric and complete.
- 32 of 51 policy events overlap another same-product policy event within 20 trading days and are explicitly unsuitable for single-notice attribution.
- All bilingual policy-type fields and evidence-status fields are populated.
- 19/19 automated tests passed; SQLite integrity check: `ok`.

## v0.20 unified event-evidence master table - 2026-10-17

### Added

- 59 source-verified EC/SN real-world events with bilingual categories, transmission channels and provenance.
- 47 event-market-policy-postmarket mechanism-chain rows plus complete forward and backward research tables.
- A 71-row bilingual AO/BU/EC/SN master table with policy details, evidence status and five-day market windows.
- A review queue that retains unmatched or not-yet-assessed real-event evidence instead of silently dropping it.
- UI and AI-context support for the unified correspondence table.

### Validation and scope

- 16 policy records have a verified real-event chain link; 21 have market-anomaly/policy correspondence without a verified event; 4 are policy/postmarket only; 30 AO/BU rows await a real-event layer.
- All 71 master rows match a market trade date.
- 14/14 automated tests passed; SQLite integrity check: `ok`.
- Window differences are descriptive before/after summaries, not causal estimates or trading recommendations.

## v0.19 EC/SN verified episodes and mismatch classification - 2026-10-16

### Added

- Official-data increment through 2026-10-16 with a three-source latest-complete-date rule.
- 41 source-verified EC/SN policy episodes with bilingual event fields and official evidence provenance.
- Observable-pattern classification for 107,308 trade-parameter/settlement-parameter field differences.
- EC/SN verified episodes and mismatch-priority CSV exports.
- UI support for EC/SN verified events and latest complete synchronization date.

### Validation and scope

- Market and official trade parameters available through 2026-10-16; settlement parameters through 2026-10-15.
- Latest three-source complete date: 2026-10-15.
- AO, BU, EC and SN now pass the notice-parameter-market research-readiness rule.
- 10/10 automated tests passed; SQLite integrity check: `ok`.

## v0.18 audit-chain and completeness dashboard - 2026-10-05

### Added

- Full rebuild of market/trade-parameter and settlement/trade-parameter audits through 2026-09-30.
- A 25-product completeness dashboard with coverage, provenance agreement, notice-review and readiness fields.
- Separate `official_file_not_available` status for official 404/no-file dates.
- Four additional audit-oriented CSV exports.

### Validation and scope

- Official availability checked through 2026-10-05 with zero unresolved download or validation failures.
- 3,157 market-alignment days and 3,157 settlement-reconciliation days.
- All 13 newly added trade dates have exact market/trade-parameter key alignment.
- Source differences are preserved rather than overwritten.

## v0.17 incremental completeness update - 2026-10-04

### Added

- Reproducible incremental downloader for market, settlement and official trade-parameter daily files.
- Validated non-destructive integration into a new database version.
- `official_data_availability_check` provenance table for valid days, official no-file responses and unresolved failures.
- Availability-aware freshness logic and two focused tests.

### Validation and scope

- Official endpoints checked through 2026-10-02; latest valid date is 2026-09-30 for all three datasets.
- 865,652 contract-market rows, 706,348 settlement-parameter rows and 669,737 official trade-parameter rows.
- 73,494 product-day indicator rows, 2,279 intense/extreme days and 25 product snapshots.
- 8/8 tests passed; SQLite integrity check: `ok`.
- The result remains descriptive and does not predict direction or recommend trading.

## v0.16 market research assistant - 2026-10-02

### Added

- Notice-parameter policy intervals with derived start/end dates and an auditable manual-override layer.
- Product-day trading-intensity metrics and literature registry.
- Historical anomaly score using trailing product-specific percentiles without future observations.
- Local browser dashboard with parameter timelines, intense days, notices and product research summaries.
- Optional structured OpenAI interpretation grounded in database evidence, with no trade recommendation field.
- Six automated unit/integration smoke tests.

### Validation and scope

- 21 verified AO/BU policy intervals.
- 73,144 product-day indicator rows across 25 products.
- 2,271 historical intense/extreme days under the documented threshold rule.
- Source market data end on 2026-09-09; the build is explicitly marked stale on 2026-10-02.
- SQLite integrity check: `ok`.
- The score identifies research attention and historical abnormality; it does not predict direction or recommend trading.

## Official parameter-change alignment - 2026-09-15

### Added

- Contract-field changes derived from consecutive available official daily trade-parameter records.
- Product-date-value change clusters with affected-contract shares and lifecycle context.
- Bilingual AO/BU notice-parameter and contract-field alignment tables.
- Separate effective-date and post-close observation-date fields.
- Reproducible build and validation scripts with environment-variable path overrides.

### Validation and scope

- 30 source-verified AO/BU margin and price-limit parameter records aligned to 504 contract-field observations.
- Zero below-notice or missing values on selected post-close/listing observation dates.
- 290 lower pre-close effective-date fields retained as timing evidence.
- Independent validation: 46/46 checks passed.
- Full 805 MB v0.15 SQLite database excluded from ordinary Git history; its SHA-256 is documented in the release folder.
- Results are synchronous/descriptive and do not establish causality or prediction.

## Research evidence audit - 2026-09-02

### Added

- A 25-item Word-to-CSV evidence map with source files, row filters, fields, methods and interpretation limits.
- Bilingual event-to-policy (59 events) and policy-to-event (37 policy clusters) result tables.
- A bilingual 30-factor significance audit that retains non-significant and non-identifiable results.
- A methodology matrix separating descriptive statistics, event study, dynamic regression, robust inference and prediction.
- A revised mentor-facing Word report and consolidated Excel evidence workbook.

### Reporting boundary

- Significant, borderline and non-significant findings are all retained.
- Sparse categorical factors are descriptive only where inferential assumptions fail.
- Product and source-level effects are not treated as independently identified when perfectly confounded.
- Predictive models remain exploratory and are not suitable for operational deployment.
- Database version remains v2.2.0; historical v2.1 and v2.2 artifacts are preserved.

## v2.2.0 - 2026-08-21

### Added

- Full notice-body resource audit and recovery workflow.
- `notice_body_resources` provenance records.
- `body_text_provenance` records for OCR and official parallel datasets.
- `body_gap_classification` for all remaining empty notice bodies.
- Quick and full-hash completeness gates.
- Reproducible audit outputs for the v2.2 release.

### Improved

- Recovered 53 of 94 previously empty notice bodies.
- Archived 1,657 body-resource references as recovered or otherwise tracked.
- Classified all 40 remaining empty bodies.
- Documented 27 early monthly settlement-parameter notices as official pre-boundary gaps.

### Quality boundary

- The database contains 6,473 automatically generated event candidates.
- No events have yet been promoted to research-ready status.
- The recommended parameter-value sample boundary is 2005-09.
- Status: PASS_WITH_DOCUMENTED_GAPS.
