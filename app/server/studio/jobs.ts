/** The Jobs API calls the app makes, always as the app service principal (`jobs` is not an
 * Apps user-authorization scope, so the signed-in user's token can't start runs). */

export interface JobRunState {
  life_cycle_state?: string;
  result_state?: string;
  state_message?: string;
}

export interface JobRun {
  job_id?: number;
  state?: JobRunState;
  end_time?: number;
  run_page_url?: string;
  tasks?: Array<{ run_id?: number; task_key?: string; state?: JobRunState }>;
}

/** A row of jobs.listRuns: enough to find a run by one of its job parameters. */
export interface ListedRun extends JobRun {
  run_id?: number;
  job_parameters?: Array<{ name?: string; value?: string; default?: string }>;
}


export interface JobsClient {
  /** jobs.runNow with job-level parameters; returns the job run ID. */
  runNow(jobId: number, jobParameters: Record<string, string>): Promise<number>;
  /** jobs.getRun; null when the run doesn't exist. */
  getRun(runId: number): Promise<JobRun | null>;
  /** jobs.getRunOutput(task run).error, e.g. "RuntimeError: …"; null when there is none. */
  taskError(taskRunId: number): Promise<string | null>;
  /** The job's most recent runs, newest first, at most `limit`. */
  listRuns(jobId: number, limit: number): Promise<ListedRun[]>;

}

export const TERMINAL_LIFE_CYCLE = ['TERMINATED', 'INTERNAL_ERROR', 'SKIPPED'];

export function isTerminal(run: JobRun): boolean {
  return TERMINAL_LIFE_CYCLE.includes(run.state?.life_cycle_state ?? '');
}

/** The first task that didn't succeed, whose run output carries the real exception text. */
export function failedTaskRunId(run: JobRun): number | null {
  const task = (run.tasks ?? []).find((t) => t.run_id && t.state?.result_state && t.state.result_state !== 'SUCCESS');
  return task?.run_id ?? null;
}
