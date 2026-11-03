-- Every stored stress test (Scenarios → Stress test tab).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
SELECT stress_id, scenario_id, n, n_solved, n_invalid, n_infeasible, n_failed, p10_gross_margin, p50_gross_margin,
       p90_gross_margin, to_json(fragile_fields) AS fragile_fields_json, to_json(fragile_hybrids) AS fragile_hybrids_json,
       seed, job_run_id, mlflow_run_id, triggered_by, unix_millis(created_at) AS created_ms, :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.stress_test_summary')
ORDER BY created_at DESC
