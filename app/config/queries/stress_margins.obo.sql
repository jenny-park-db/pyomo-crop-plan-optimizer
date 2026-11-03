-- Per-sample gross margins of one stress test (distribution chart).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
-- @param stress_id STRING = stress-baseline-2027-n500
SELECT gross_margin, status, :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.stress_test_results')
WHERE stress_id = :stress_id
