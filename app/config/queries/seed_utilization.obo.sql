-- Seed use by hybrid for one run (Results chart).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
-- @param run_id STRING = run-123456789012345
SELECT hybrid_id, units_used, units_available, pct, :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.seed_utilization')
WHERE run_id = :run_id
ORDER BY hybrid_id
