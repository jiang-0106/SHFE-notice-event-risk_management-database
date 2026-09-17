# SHFE Notice Event & Risk-Parameter Database

上海期货交易所公告标签与风险参数事件数据库。项目基于上海期货交易所公开公告，构建可按“调整原因、调整参数、时间、品种/合约”组合查询的SQLite数据库，并提供Excel入口、Python查询工具、参数事件候选和人工复核机制。

> **Independent research project.** This repository is not affiliated with or endorsed by the Shanghai Futures Exchange (SHFE). It does not constitute investment advice.

## Project snapshot

- Coverage: `2000-10-08` to `2026-08-10`
- Notices indexed: `4,963`
- Automatically generated parameter-event candidates: `6,473`
- Products identified: `25`
- Reason taxonomy: `8` adjustment categories plus code `00`
- Parameter taxonomy: `13` parameter types
- Priority review queue: P0 `372`, P1 `580`, P2 `748`, P3 `3,263`
- Five priority products: gold (`AU`), silver (`AG`), copper (`CU`), rebar (`RB`), fuel oil (`FU`)

The database is not limited to the five priority products. Other SHFE/INE products can also be queried; the five-product list only determines the current manual-review priority.

## Repository contents

```text
database/
  SHFE_notice_event_database_v2.2.sqlite3
  SHFE_notice_query_v2.1.xlsx
  five_products_P0_review_queue.csv
docs/
  SHFE公告标签与参数事件数据库使用说明_v2.1.docx
scripts/
  query_shfe_notices.py
  query_shfe_parameter_events.py
  upgrade_shfe_notice_db.py
  upgrade_notice_event_layer.py
  preserve_notice_manual_work.py
data_dictionary/
  REASON_CODES.md
  PARAMETER_CODES.md
  DATABASE_SCHEMA.md
examples/
  example_queries.sql
audits/
research_outputs/
  2026-09-02_evidence_audit/
  2026-09-15_parameter_change_alignment/
```

The original HTML pages, attachments and large archive packages are intentionally excluded from Git history. Versioned full-data packages should be distributed through [GitHub Releases](https://github.com/jiang-0106/SHFE-notice-event-risk_management-database/releases).

## Research evidence audit (2026-09-02)

The folder [`research_outputs/2026-09-02_evidence_audit`](research_outputs/2026-09-02_evidence_audit) adds a transparent research-reporting layer for the EC/SN notice-event study. It contains:

- a 25-item Word-to-CSV claim map;
- a bilingual audit of 30 tested factors, retaining both significant and non-significant results;
- 59 bilingual event-to-policy records with specific event names, dates, background and parameter adjustments;
- 37 bilingual policy-to-event records with pre-policy anomalies and candidate real-world events;
- a revised mentor-facing report and a consolidated Excel workbook.

These files distinguish descriptive statistics, event studies, dynamic regressions, robust inference and prediction. Associations and temporal ordering are not presented as causal effects. The database release remains **v2.2.0**; this research-output update does not replace or delete v2.1/v2.2 history.

## Official parameter-change alignment (2026-09-15)

The folder [`research_outputs/2026-09-15_parameter_change_alignment`](research_outputs/2026-09-15_parameter_change_alignment) adds a synchronous correspondence layer for source-verified AO/BU margin and price-limit notices.

- 152,730 normalized contract-field parameter changes;
- 24,636 descriptive change clusters, including 1,795 AO/BU clusters;
- 30 verified notice-parameter records and 504 contract-field evidence rows;
- separate handling of post-close parameter dates and initial listing observations;
- bilingual summary, detail and cluster tables;
- 46/46 independent validation checks passed.

The full v0.15 SQLite database is about 805 MB and is not committed to ordinary Git history. Review-sized CSV/JSON results and reproducible scripts are published instead. This layer remains descriptive: it does not perform prediction or causal attribution.

## Quick start with DB Browser for SQLite

1. Install [DB Browser for SQLite](https://sqlitebrowser.org/).
2. Open `database/SHFE_notice_event_database_v2.2.sqlite3`.
3. Select **Browse Data**.
4. Choose `v_notice_query` for notice-level search, or `parameter_events` for event candidates.
5. Filter `product_codes`, `parameter_codes`, `primary_reason_code` or date fields.

Example: query fuel-oil price-limit events.

```sql
SELECT *
FROM parameter_events
WHERE product_code = 'FU'
  AND parameter_code = 'price_limit'
ORDER BY announcement_date DESC;
```

More examples are available in [`examples/example_queries.sql`](examples/example_queries.sql).

## Four query dimensions

| Question | Main fields | Meaning |
|---|---|---|
| Why was it adjusted? | `primary_reason_code`, `reason_code` | Holiday, temporary risk control, consecutive limit moves, listing, delivery, limits, rule change, other special handling |
| What was adjusted? | `parameter_code`, `parameter_name` | Price limit, margin, trading/position/opening limits, hours, listing, delivery, fees, options |
| When was it adjusted? | `publish_date`, `announcement_date`, `effective_date_candidate` | Publication date is confirmed; effective/restore dates remain candidates until reviewed |
| Which product/contract? | `product_code`, `contract_codes` | Product-level and contract-level identification |

## Key tables and views

- `notices`: all notice metadata and extracted text.
- `notice_products`: product and contract tags with evidence.
- `notice_parameters`: parameter tags, candidate values and evidence.
- `notice_dates`: dates extracted from notice text.
- `parameter_events`: product-by-parameter event candidates.
- `review_tasks`: P0-P3 manual-review queue.
- `manual_overrides`: persistent manual corrections.
- `v_notice_query`: recommended notice-level query view.
- `v_final_products`, `v_final_parameters`: automatic tags merged with manual overrides.
- `v_event_research_ready`: manually confirmed events with effective dates.

## Python usage

The query scripts use only the Python standard library.

```powershell
python scripts/query_shfe_notices.py `
  --db database/SHFE_notice_event_database_v2.2.sqlite3 `
  --product FU --parameter price_limit `
  --from-date 2020-01-01 --to-date 2026-12-31 `
  --out fuel_oil_notices.csv
```

```powershell
python scripts/query_shfe_parameter_events.py `
  --db database/SHFE_notice_event_database_v2.2.sqlite3 `
  --product FU --parameter price_limit `
  --out fuel_oil_events.csv
```

## Quality boundary

Automatic labels and `parameter_events` are research-screening candidates, not verified facts. Before an event is used in formal analysis, users should verify:

1. the official notice and attachment;
2. the affected product and contract range;
3. effective and restoration dates;
4. old/new parameter values and units;
5. monthly and daily parameter records;
6. whether a limit expansion was rule-triggered or separately announced.

At this release, `v_event_research_ready` contains no records because formal manual confirmation has not yet been completed.

## Data source and rights

Source notices originate from the official SHFE website: <https://www.shfe.com.cn/publicnotice/notice/>. Official notice text, attachments, trademarks and website content remain the property of their respective rights holders. See [`DATA_NOTICE.md`](DATA_NOTICE.md).

The MIT license in this repository applies to the original source code and project documentation, not to third-party official notices or attachments.

## Citation

If you use this project, please cite the repository and record the database version and access date. A formal citation file can be added after the first public release and DOI assignment.

## Disclaimer

This project is for academic and technical research only. It is not an official SHFE database, and no warranty is provided regarding completeness, classification accuracy or fitness for trading and investment decisions.


## Version 2.2 completeness update

Version 2.2 adds notice-body recovery, source provenance, body-resource archiving, and reproducible completeness checks.

- Notices: `4,963`
- Coverage: `2000-10-08` to `2026-08-10`
- Parameter-event candidates: `6,473`
- Research-ready events: `0`
- Remaining empty notice bodies: `40`
- Empty bodies individually classified: `40`
- Early official-boundary parameter gaps: `27`
- Body-resource coverage: `97.88%`
- SQLite integrity check: `ok`
- Completeness gate: `PASS_WITH_DOCUMENTED_GAPS`

The 27 research-relevant empty-body records are monthly settlement-parameter notices from 2003-05 through 2005-08. They precede the confirmed starting boundary of the parallel official monthly structured dataset. Parameter-value analyses should therefore use 2005-09 as the recommended starting boundary unless independent primary-source validation is completed.

All 6,473 parameter events remain automatically generated candidates. The `v_event_research_ready` view remains empty until event-level manual validation is completed.

See:

- `audits/v22_completeness_gate.json`
- `audits/v22_completeness_gate_full_hash.json`
- `audits/remaining_empty_body_gap_classification.csv`
- `audits/v2.2_body_gap_classification.md`
