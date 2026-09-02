# EC/SN research evidence audit — 2026-09-02

This package reconciles the mentor-facing August report with the underlying result files and makes the reporting boundary explicit.

## Contents

| File | Purpose |
|---|---|
| `SHFE公告事件研究_8月工作内容汇报_证据对应与双语修订版_20260902.docx` | Revised mentor-facing report with calibrated claims and appendices |
| `SHFE公告事件研究_Word-CSV证据映射与双语结果表_20260902.xlsx` | Consolidated workbook containing all audit and bilingual result sheets |
| `word_csv_conclusion_mapping.csv` | 25 report claims mapped to source files, filters, fields and methods |
| `factor_significance_audit_bilingual.csv` | 30 factor tests with raw p-values, BH q-values and identification limits |
| `bilingual_event_forward_table.csv` | 59 real-world events linked to subsequent anomalies and policy adjustments |
| `bilingual_policy_backward_table.csv` | 37 policy clusters linked to prior anomalies and candidate events |
| `methodology_matrix_bilingual.csv` | Bilingual distinction among the five analysis layers |

## Core reporting rules

1. Non-significant factors are retained rather than deleted.
2. Raw p-values, within-family BH q-values, sample sizes and limitations are reported together.
3. Sparse multi-category factors are descriptive when expected-cell assumptions fail.
4. Product is a design contrast, not an actionable risk trigger; source level is not independently identified where it is perfectly aligned with product.
5. Event-window associations and policy timing do not, by themselves, establish causal effects.
6. Current forward and backward prediction models are exploratory and not ready for risk-control deployment.

## Key results

- SN five-day direction-aligned event returns are about 0.51% and remain significant after global BH correction.
- SN volume falls about 20.7% after non-routine tightening, but policy pre-trends and global multiple-testing adjustment weaken a causal interpretation.
- SN returns show a candidate negative association with USD changes after within-family BH correction.
- Event severity precode is a candidate correlate of policy action within 20 days, pending independent coding review.
- Ten-day return/range/anomaly indicators have raw `p < 0.05` but BH `q ≈ 0.055–0.058`; they are monitoring candidates, not validated warning signals.
