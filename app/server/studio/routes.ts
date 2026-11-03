/** HTTP handlers for /api/studio/*. Thin: parse the request, pick the identity, call the tested modules. */
import { IdError } from '../../shared/studio/ids';
import { OverridesError } from '../../shared/studio/overrides';
import { pollTurn, startTurn, type AgentFetch } from './agentProxy';
import { tablesFor, type StudioConfig } from './config';
import type { JobsClient } from './jobs';
import { createThrottle, syncActiveRuns, type SyncResult } from './reconcile';
import { runReport, scenarioReport } from './report';
import type { SqlRunner } from './sql';
import { stressResult } from './stressResult';
import { createStressStarter, stressStatus } from './stress';
import { createSubmitter, SubmitError, type SubmitRequest } from './submit';

export interface Req {
  header(name: string): string | undefined;
  body?: unknown;
  params: Record<string, string>;
}
export interface Res {
  status(code: number): Res;
  json(body: unknown): unknown;
}
export type Handler = (req: Req, res: Res) => Promise<void>;

/** sql runs as the requesting user (OBO); jobs runs as the app service principal. */
export type DepsFor = (req: Req) => { sql: SqlRunner; jobs: JobsClient };

/** The platform sets x-forwarded-email on every request; the body never decides who a run belongs to. */
export function userEmail(req: Req, env: Record<string, string | undefined> = process.env): string {
  const email = req.header('x-forwarded-email')?.trim();
  if (email) return email;
  if (env.NODE_ENV === 'development' && env.CROP_PLAN_DEV_USER) return env.CROP_PLAN_DEV_USER;
  throw new SubmitError(401, 'No signed-in user on this request (x-forwarded-email is missing)');
}

function fail(res: Res, e: unknown): void {
  if (e instanceof SubmitError) {
    res.status(e.status).json({ error: e.message, path: e.path ?? null });
  } else if (e instanceof OverridesError) {
    res.status(400).json({ error: e.message, path: e.path });
  } else if (e instanceof IdError) {
    res.status(400).json({ error: e.message, path: null });
  } else {
    res.status(500).json({ error: e instanceof Error ? e.message : String(e), path: null });
  }
}

const wrap = (fn: (req: Req, res: Res) => Promise<unknown>): Handler => async (req, res) => {
  try {
    res.status(200).json(await fn(req, res));
  } catch (e) {
    fail(res, e);
  }
};

export function createHandlers(cfg: StudioConfig, depsFor: DepsFor, env: Record<string, string | undefined> = process.env,
                               agentFetch: AgentFetch = (url, init) => fetch(url, init)) {
  const t = tablesFor(cfg);
  const submit = createSubmitter();
  const syncThrottle = createThrottle<SyncResult>();
  const startStress = createStressStarter();

  return {
    config: wrap(async () => cfg),
    whoami: wrap(async (req) => ({
      email: userEmail(req, env),
      name: req.header('x-forwarded-preferred-username') ?? null,
      // Matches bundle/resources/app.yml user_api_scopes; the Genie panel states this to the user.
      obo_scopes: ['sql', 'dashboards.genie'],
    })),
    submitRun: wrap(async (req) => {
      const { sql, jobs } = depsFor(req);
      return submit({ sql, jobs, t, solveJobId: cfg.solveJobId }, (req.body ?? {}) as SubmitRequest, userEmail(req, env));
    }),
    syncRuns: wrap(async (req) => {
      const { sql, jobs } = depsFor(req);
      userEmail(req, env);
      return syncThrottle(() => syncActiveRuns({ sql, jobs, t }));
    }),
    startStress: wrap(async (req) => {
      const { sql, jobs } = depsFor(req);
      return startStress({ sql, jobs, t, stressJobId: cfg.stressJobId }, (req.body ?? {}) as Record<string, unknown>, userEmail(req, env));
    }),
    runReport: wrap(async (req) => {
      const { sql, jobs } = depsFor(req);
      userEmail(req, env);
      const first = await runReport({ sql, t }, req.params.runId);
      if (first.final) return first;
      // Same reconciliation the Runs screen triggers, so a job that died is reported as failed, not "solving".
      // If reconciliation itself hits a blip, answer from the first read: the run is still healthy to wait on.
      try {
        await syncThrottle(() => syncActiveRuns({ sql, jobs, t }));
      } catch (e) {
        console.error('run report sync failed', e);
        return first;
      }
      return runReport({ sql, t }, req.params.runId);
    }),
    scenarioReport: wrap(async (req) => {
      const { sql } = depsFor(req);
      userEmail(req, env);
      return scenarioReport({ sql, t }, req.params.scenarioId);
    }),
    stressResult: wrap(async (req) => {
      const { sql, jobs } = depsFor(req);
      userEmail(req, env);
      return stressResult({ sql, jobs, t, stressJobId: cfg.stressJobId }, req.params.stressId);
    }),
    agentStart: wrap(async (req) => {
      userEmail(req, env);
      return startTurn({ agentUrl: cfg.agentUrl, fetch: agentFetch }, req.header('x-forwarded-access-token'), req.body);
    }),
    agentPoll: wrap(async (req) => {
      userEmail(req, env);
      return pollTurn({ agentUrl: cfg.agentUrl, fetch: agentFetch }, req.header('x-forwarded-access-token'), req.params.id);
    }),


    stressStatus: wrap(async (req) => {
      const { jobs } = depsFor(req);
      userEmail(req, env);
      return stressStatus({ jobs, stressJobId: cfg.stressJobId }, req.params.jobRunId);
    }),
  };
}
