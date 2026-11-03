-- Every scenario with its latest run and latest successful run (Inputs source picker, Scenarios lineage).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
WITH ranked AS (
  SELECT scenario_id, run_id, status,
         row_number() OVER (PARTITION BY scenario_id ORDER BY coalesce(started_at, submitted_at) DESC) AS rn_any,
         CASE WHEN status = 'done' THEN row_number() OVER (PARTITION BY scenario_id, status = 'done' ORDER BY ended_at DESC) END AS rn_done
  FROM IDENTIFIER(:catalog || '.' || :schema || '.runs')
)
SELECT s.scenario_id, s.name, s.parent_scenario_id, s.source, s.created_by,
       unix_millis(s.created_at) AS created_ms, s.overrides,
       max(CASE WHEN r.rn_any = 1 THEN r.status END) AS latest_status,
       max(CASE WHEN r.rn_any = 1 THEN r.run_id END) AS latest_run_id,
       max(CASE WHEN r.rn_done = 1 THEN r.run_id END) AS latest_done_run_id,
       :refresh AS refresh
FROM IDENTIFIER(:catalog || '.' || :schema || '.scenarios') s
LEFT JOIN ranked r ON r.scenario_id = s.scenario_id
GROUP BY ALL
ORDER BY created_ms
