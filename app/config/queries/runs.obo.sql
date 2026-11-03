-- The Runs screen: newest 300 solve attempts. Times are epoch ms (unix_millis), so the session time zone never matters.
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
SELECT r.run_id, r.scenario_id, s.name AS scenario_name, s.source, r.job_run_id, r.mlflow_run_id, r.triggered_by,
       r.status, r.solver, r.solver_version, r.model_version,
       unix_millis(r.submitted_at) AS submitted_ms, unix_millis(r.started_at) AS started_ms,
       unix_millis(r.ended_at) AS ended_ms, r.error, r.infeasibility_reason, r.diagnosis, r.mip_gap,
       r.termination, r.objective, r.runtime_s, :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.runs') r
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.scenarios') s ON s.scenario_id = r.scenario_id
ORDER BY coalesce(r.started_at, r.submitted_at) DESC NULLS LAST
LIMIT 300
