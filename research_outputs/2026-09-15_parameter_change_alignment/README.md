# SHFE official parameter-change alignment v0.15

This folder publishes the review-sized outputs of the v0.15 synchronous correspondence layer. It links source-verified AO/BU notices to official daily margin and price-limit records and derives contract-level parameter changes without making predictive or causal claims.

## Main results

- 152,730 contract-field changes derived from consecutive available official daily records.
- 24,636 descriptive product-date-value clusters, including 1,795 AO/BU clusters.
- 30 source-verified AO/BU notice-parameter records aligned to 504 contract-field observations.
- 17 notice parameters exactly match all scoped observations; 13 meet the notice floor with higher lifecycle values retained.
- 13 records show all fields changing on the selected observation date, 9 show partial change with pre-existing higher/equal values, 6 are initial listing observations, and 2 were already at the applicable level.
- 46 of 46 independent validation checks passed.

## Timing convention

For notices effective "from settlement at market close," the database retains the effective-date snapshot and tests the post-close trading level on the next available official trade-parameter date. For a contract effective from initial listing, the listing date itself is used. Initial listing observations are not mislabeled as within-contract changes.

This convention resolved 290 effective-date pre-close fields that were below the newly announced level. On the selected post-close/listing observation dates, the verified sample has zero below-notice values and zero missing observations.

## Files

| File | Purpose |
|---|---|
| `verified_notice_parameter_alignment_v15.csv` | Bilingual 30-row notice-parameter summary |
| `verified_notice_parameter_contract_detail_v15.csv` | Bilingual 504-row contract-field evidence table |
| `ao_bu_parameter_change_clusters_v15.csv` | Bilingual AO/BU descriptive parameter-change clusters |
| `official_product_parameter_change_clusters_v15.csv` | Bilingual all-product descriptive change clusters |
| `v15_build_summary.json` | Build counts, database hashes and scope |
| `v15_validation_summary.json` | Independent 46-check validation report |
| `阶段说明_公告参数变更点对应_v0.15.md` | Chinese stage note and interpretation boundaries |
| `scripts/apply_parameter_change_alignment_v15.py` | Build script for the local v0.14 source database |
| `scripts/validate_parameter_change_alignment_v15.py` | Independent validation script |

## Full database boundary

The complete v0.15 SQLite database is approximately 805 MB and is intentionally excluded from ordinary Git history because it exceeds GitHub's normal single-file limit. The published CSV files, JSON audits and scripts provide reviewable results and provenance. The local full database SHA-256 is:

`144ab85596c10e4a51e1a72cc49c2d94b19a755765b09becb85499b8c09b378b`

The preserved v0.14 source database SHA-256 is:

`a8a4ba1cdab8a3c3263825100ca9f6cf2bf5b8c945d688b08d4aeb503bf98982`

## Reproduction

The scripts use Python's standard library. Point them to the local full databases with environment variables:

```powershell
$env:SHFE_V15_SOURCE_DB = 'D:\path\source_v0.14.sqlite3'
$env:SHFE_V15_OUTPUT_DB = 'D:\path\output_v0.15.sqlite3'
$env:SHFE_V15_AUDIT_DIR = 'D:\path\v15_audits'
python scripts\apply_parameter_change_alignment_v15.py
python scripts\validate_parameter_change_alignment_v15.py
```

The build script refuses to overwrite an unrecognized existing output database. The official daily source files are not redistributed in this folder.

## Interpretation boundary

Parameter-change clusters are descriptive data groupings. Temporal alignment does not establish that a notice caused a parameter change, that a real-world event caused the notice, or that future parameter adjustments can be predicted.
