# Changelog

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
