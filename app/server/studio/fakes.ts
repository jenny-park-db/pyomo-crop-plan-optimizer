/** Test doubles for SqlRunner and JobsClient. */
import type { JobRun, JobsClient, ListedRun } from './jobs';
import type { Row, SqlParams, SqlRunner } from './sql';

type Responder = Row[] | Error | ((params: SqlParams) => Row[] | Error);

export class FakeSql implements SqlRunner {
  readonly calls: Array<{ statement: string; params: SqlParams }> = [];
  private readonly rules: Array<{ match: RegExp; respond: Responder; times: number }> = [];

  /** Respond to statements matching `match` (first matching rule wins; `times` limits how often). */
  on(match: RegExp, respond: Responder, times = Infinity): this {
    this.rules.push({ match, respond, times });
    return this;
  }

  async run(statement: string, params: SqlParams = {}): Promise<Row[]> {
    this.calls.push({ statement, params });
    const rule = this.rules.find((r) => r.times > 0 && r.match.test(statement));
    if (!rule) return [];
    rule.times -= 1;
    const out = typeof rule.respond === 'function' ? rule.respond(params) : rule.respond;
    if (out instanceof Error) throw out;
    return out;
  }

  matching(match: RegExp) {
    return this.calls.filter((c) => match.test(c.statement));
  }
}

export class FakeJobs implements JobsClient {
  readonly started: Array<{ jobId: number; params: Record<string, string> }> = [];
  runs = new Map<number, JobRun>();
  taskErrors = new Map<number, string>();
  failRunNow: Error | null = null;
  failGetRun: Error | null = null;
  nextRunId = 9001;
  recent: ListedRun[] = [];
  readonly listed: Array<{ jobId: number; limit: number }> = [];


  async runNow(jobId: number, params: Record<string, string>): Promise<number> {
    if (this.failRunNow) throw this.failRunNow;
    this.started.push({ jobId, params });
    return this.nextRunId++;
  }
  async getRun(runId: number): Promise<JobRun | null> {
    if (this.failGetRun) throw this.failGetRun;
    return this.runs.get(runId) ?? null;
  }
  async taskError(taskRunId: number): Promise<string | null> {
    return this.taskErrors.get(taskRunId) ?? null;
  }
  async listRuns(jobId: number, limit: number): Promise<ListedRun[]> {
    this.listed.push({ jobId, limit });
    return this.recent.slice(0, limit);
  }
}
