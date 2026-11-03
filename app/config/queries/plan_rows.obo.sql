-- One run's plan joined to its scenario's fields (map, drill-down table, change map).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
-- @param run_id STRING = run-123456789012345
SELECT a.field_id, f.grower_id, f.region, f.soil_class, f.acres, f.lat, f.lon, f.rm_min, f.rm_max,
       a.hybrid_id, a.`window` AS planting_window, a.exp_yield, a.exp_margin, a.is_fixed, :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.plan_assignments') a
JOIN IDENTIFIER(:catalog || '.' || :schema || '.fields') f ON f.scenario_id = a.scenario_id AND f.field_id = a.field_id
WHERE a.run_id = :run_id
ORDER BY a.field_id
