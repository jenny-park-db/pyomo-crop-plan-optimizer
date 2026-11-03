-- One scenario's inputs for the Inputs validation panel, as one row of JSON arrays (one round trip).
-- @param catalog STRING = pyomo_crop_plan_demo_catalog
-- @param schema STRING = crop_plan
-- @param refresh INT = 0
-- @param scenario_id STRING = baseline-2027
SELECT
  (SELECT season FROM IDENTIFIER(:catalog || '.' || :schema || '.scenarios') WHERE scenario_id = :scenario_id) AS season,
  (SELECT to_json(collect_list(struct(field_id, grower_id, region, acres, lat, lon, soil_class, rm_min, rm_max)))
     FROM IDENTIFIER(:catalog || '.' || :schema || '.fields') WHERE scenario_id = :scenario_id) AS fields_json,
  (SELECT to_json(collect_list(struct(hybrid_id, relative_maturity, units_per_acre)))
     FROM IDENTIFIER(:catalog || '.' || :schema || '.hybrids') WHERE scenario_id = :scenario_id) AS hybrids_json,
  (SELECT to_json(collect_list(struct(season, hybrid_id, units_available)))
     FROM IDENTIFIER(:catalog || '.' || :schema || '.seed_supply') WHERE scenario_id = :scenario_id) AS seed_supply_json,
  (SELECT to_json(collect_list(struct(region, soil_class, hybrid_id, `window`)))
     FROM IDENTIFIER(:catalog || '.' || :schema || '.yield_forecast') WHERE scenario_id = :scenario_id) AS yield_forecast_json,
  (SELECT to_json(collect_list(struct(region, `window`, acres_capacity)))
     FROM IDENTIFIER(:catalog || '.' || :schema || '.planting_capacity') WHERE scenario_id = :scenario_id) AS planting_capacity_json,
  (SELECT to_json(collect_list(struct(field_id, hybrid_id, `window`)))
     FROM IDENTIFIER(:catalog || '.' || :schema || '.fixed_requests') WHERE scenario_id = :scenario_id) AS fixed_requests_json,
  :refresh AS refresh
