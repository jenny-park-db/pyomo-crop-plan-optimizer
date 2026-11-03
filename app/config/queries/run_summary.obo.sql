-- KPIs of one run (Results tiles, Compare columns).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
-- @param run_id STRING = run-123456789012345
SELECT r.run_id, r.scenario_id, r.status, unix_millis(r.ended_at) AS ended_ms, r.termination, r.mip_gap,
       m.gross_margin, m.net_margin, m.unplanted_penalty_total, m.acres_planted_pct, m.unplanted_fields,
       m.violations_count,
       (SELECT count(*) FROM IDENTIFIER(:catalog || '.' || :schema || '.seed_utilization') u WHERE u.run_id = r.run_id AND u.pct >= 0.99) AS hybrids_at_limit,
       :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.runs') r
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.run_summary') m ON m.run_id = r.run_id
WHERE r.run_id = :run_id
