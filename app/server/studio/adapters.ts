/** Real SqlRunner / JobsClient over AppKit and the Databricks SDK (the parts the unit tests fake). */
import { getExecutionContext, sql as marker } from '@databricks/appkit';
import type { JobRun, JobsClient, ListedRun } from './jobs';
import type { Row, SqlParam, SqlParams, SqlRunner } from './sql';

function toMarker(value: SqlParam) {
  if (typeof value === 'boolean') return marker.boolean(value);
  if (typeof value === 'number') return Number.isInteger(value) ? marker.bigint(value) : marker.double(value);
  return marker.string(value);
}

/** The subset of the analytics plugin's export used here: query(statement, params) → { data: rows }. */
export interface UserQuery {
  query(statement: string, parameters?: Record<string, ReturnType<typeof toMarker>>): Promise<unknown>;
}

export function userSql(asUser: UserQuery): SqlRunner {
  return {
    async run(statement: string, params: SqlParams = {}): Promise<Row[]> {
      const markers = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, toMarker(v)]));
      const result = (await asUser.query(statement, markers)) as { data?: Row[] } | undefined;
      return result?.data ?? [];
    },
  };
}

/** Jobs API as the app service principal (the service context's client, never the user's). */
export function serviceJobs(): JobsClient {
  const client = () => getExecutionContext().client;
  return {
    async runNow(jobId, jobParameters) {
      const r = await client().jobs.runNow({ job_id: jobId, job_parameters: jobParameters });
      if (!r.run_id) throw new Error('runNow returned no run_id');
      return Number(r.run_id);
    },
    async getRun(runId) {
      try {
        return (await client().jobs.getRun({ run_id: runId })) as JobRun;
      } catch (e) {
        if (/does not exist|RESOURCE_DOES_NOT_EXIST|not found/i.test(String(e))) return null;
        throw e;
      }
    },
    async taskError(taskRunId) {
      const out = await client().jobs.getRunOutput({ run_id: taskRunId });
      return out.error ?? null;
    },
    async listRuns(jobId, limit) {
      const out: ListedRun[] = [];
      // listRuns pages lazily; stop after `limit` rows instead of walking the job's whole history.
      for await (const run of client().jobs.listRuns({ job_id: jobId, limit })) {
        out.push(run as ListedRun);
        if (out.length >= limit) break;
      }
      return out;
    },
  };
}
