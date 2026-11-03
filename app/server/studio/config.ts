/** Runtime configuration from the app's environment (bundle `config.env` on deploy, `.env` locally). */

export type MapMode = 'tiles' | 'svg';

export interface StudioConfig {
  catalog: string;
  schema: string;
  solveJobId: number;
  stressJobId: number;
  /** Workspace URL, e.g. https://my-workspace.cloud.databricks.com (for job-run and MLflow links). */
  host: string;
  experimentId: string | null;
  mapMode: MapMode;
  /** The planning agent's app URL; null until the agent is deployed. */
  agentUrl: string | null;
}

/** What the browser gets from GET /api/studio/config. */
export type ClientConfig = StudioConfig;

const NAME = /^[A-Za-z0-9_]+$/;

function required(env: Record<string, string | undefined>, key: string): string {
  const value = env[key]?.trim();
  if (!value) throw new Error(`Missing environment variable ${key}`);
  return value;
}

function jobId(env: Record<string, string | undefined>, key: string): number {
  const n = Number(required(env, key));
  if (!Number.isSafeInteger(n) || n <= 0) throw new Error(`${key} must be a job ID, got ${env[key]}`);
  return n;
}

/**
 * The user's token is forwarded to this URL, so only an https URL is accepted. Empty or "none" (the bundle's
 * default until scripts/deploy_agent.py records the agent; the Apps API rejects an empty env value) = not deployed.
 */
function agentUrl(env: Record<string, string | undefined>): string | null {
  const raw = env.CROP_PLAN_AGENT_URL?.trim().replace(/\/+$/, '');
  if (!raw || raw === 'none') return null;
  if (!/^https:\/\/[A-Za-z0-9.-]+$/.test(raw)) throw new Error(`CROP_PLAN_AGENT_URL must be an https app URL, got ${raw}`);
  return raw;
}

export function loadConfig(env: Record<string, string | undefined> = process.env): StudioConfig {
  const catalog = required(env, 'CROP_PLAN_CATALOG');
  const schema = required(env, 'CROP_PLAN_SCHEMA');
  for (const [k, v] of [['CROP_PLAN_CATALOG', catalog], ['CROP_PLAN_SCHEMA', schema]]) {
    if (!NAME.test(v)) throw new Error(`${k} must be letters, digits, or underscores, got ${v}`);
  }
  const rawHost = required(env, 'DATABRICKS_HOST').replace(/\/+$/, '');
  return {
    catalog,
    schema,
    solveJobId: jobId(env, 'CROP_PLAN_SOLVE_JOB_ID'),
    stressJobId: jobId(env, 'CROP_PLAN_STRESS_JOB_ID'),
    host: rawHost.startsWith('http') ? rawHost : `https://${rawHost}`,
    experimentId: env.MLFLOW_EXPERIMENT_ID?.trim() || null,
    mapMode: env.CROP_PLAN_MAP_MODE === 'svg' ? 'svg' : 'tiles',
    agentUrl: agentUrl(env),
  };
}

export type StudioTable =
  | 'scenarios' | 'runs' | 'fields' | 'hybrids' | 'seed_supply' | 'yield_forecast' | 'planting_capacity'
  | 'fixed_requests' | 'run_summary' | 'seed_utilization' | 'violations' | 'stress_test_summary' | 'plan_assignments';

/** Fully qualified, backtick-quoted table name. */
export type Tables = (table: StudioTable) => string;

export function tablesFor(cfg: Pick<StudioConfig, 'catalog' | 'schema'>): Tables {
  return (table) => `\`${cfg.catalog}\`.\`${cfg.schema}\`.\`${table}\``;
}
