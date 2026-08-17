-- 1. Fuel-oil price-limit event candidates
SELECT *
FROM parameter_events
WHERE product_code = 'FU'
  AND parameter_code = 'price_limit'
ORDER BY announcement_date DESC;

-- 2. Holiday-related margin notices
SELECT *
FROM v_notice_query
WHERE primary_reason_code = '01'
  AND parameter_codes LIKE '%margin%'
ORDER BY publish_date DESC;

-- 3. Consecutive-limit / expansion candidates
SELECT *
FROM parameter_events
WHERE reason_code = '03'
   OR expansion_trigger LIKE '%规则触发%'
ORDER BY announcement_date DESC;

-- 4. Priority-zero tasks for five research products
SELECT r.priority,n.notice_id,n.title,n.publish_date,
       q.product_codes,q.parameter_names,n.source_url
FROM review_tasks r
JOIN notices n USING (notice_id)
LEFT JOIN v_notice_query q USING (notice_id)
WHERE r.priority = 'P0'
  AND EXISTS (
      SELECT 1
      FROM notice_products p
      WHERE p.notice_id = n.notice_id
        AND p.product_code IN ('AU','AG','CU','RB','FU')
  )
ORDER BY n.publish_date DESC;

-- 5. Date-range query for gold margin and price-limit events
SELECT *
FROM parameter_events
WHERE product_code = 'AU'
  AND parameter_code IN ('margin','price_limit')
  AND announcement_date BETWEEN '2020-01-01' AND '2026-12-31'
ORDER BY announcement_date;

-- 6. Full-text query
SELECT n.notice_id,n.title,n.publish_date,n.source_url
FROM notices n
WHERE n.notice_id IN (
    SELECT notice_id
    FROM notice_fts
    WHERE notice_fts MATCH '连续 涨停'
)
ORDER BY n.publish_date DESC;

-- 7. Manually confirmed research-ready events
SELECT *
FROM v_event_research_ready
ORDER BY effective_date_candidate DESC;
