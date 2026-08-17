# Database schema guide

## Recommended views

- `v_notice_query`: notice-level multidimensional search.
- `v_final_products`: product tags after manual overrides.
- `v_final_parameters`: parameter tags after manual overrides.
- `v_review_queue`: notices requiring review.
- `v_event_research_ready`: manually confirmed events suitable for analysis.

## Core tables

### `notices`

Primary key: `notice_id`. Stores title, publication date, official URL, local source path, extracted body text, primary reason and review status.

### `notice_products`

Composite key: `notice_id`, `product_code`. Stores product names, contract codes, matched text, evidence, confidence and review status.

### `notice_parameters`

Composite key: `notice_id`, `parameter_code`. Stores parameter names, evidence, candidate values, confidence and review status.

### `notice_dates`

Stores publication-date and body-date candidates with evidence and confidence.

### `parameter_events`

Stores product-by-parameter event candidates. Important fields include `announcement_date`, `effective_date_candidate`, `restore_date_candidate`, `old_value`, `new_value`, `monthly_match`, `daily_match`, `expansion_trigger`, `validation_conclusion` and `manual_review_status`.

### `review_tasks`

Stores P0-P3 review priority, task type, reason, status, assignee and review notes.

### `manual_overrides`

Stores persistent human corrections without deleting automatic labels. Supported actions include adding, removing or replacing product/parameter labels.
