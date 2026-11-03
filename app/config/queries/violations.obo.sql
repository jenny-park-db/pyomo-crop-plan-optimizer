-- Validation issues, the binding constraint of an infeasible run, and post-solve checks for one run.
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
-- @param run_id STRING = run-234567890123456
SELECT rule, entity, severity, detail, :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.violations')
WHERE run_id = :run_id
ORDER BY CASE severity WHEN 'binding' THEN 0 WHEN 'error' THEN 1 WHEN 'hard' THEN 2 WHEN 'warning' THEN 3 ELSE 4 END, entity
