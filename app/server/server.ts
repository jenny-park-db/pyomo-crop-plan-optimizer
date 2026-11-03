import { analytics, createApp, genie, server } from '@databricks/appkit';
import type { Request } from 'express';
import { serviceJobs, userSql, type UserQuery } from './studio/adapters';
import { loadConfig } from './studio/config';
import { createHandlers } from './studio/routes';

const cfg = loadConfig();
const jobs = serviceJobs();

createApp({
  // The analytics plugin caches query results for an hour by default; this app's data changes on every run.
  cache: { enabled: false },
  // No jobs() plugin: its public POST /api/jobs/:key/run would let a browser choose triggered_by.
  plugins: [analytics(), genie(), server()],
  async onPluginsReady(appkit) {
    const h = createHandlers(cfg, (req) => ({
      sql: userSql(appkit.analytics.asUser(req as Request) as UserQuery),
      jobs,
    }));
    appkit.server.extend((app) => {
      app.get('/api/studio/config', h.config);
      app.get('/api/studio/whoami', h.whoami);
      app.post('/api/studio/runs', h.submitRun);
      app.post('/api/studio/runs/sync', h.syncRuns);
      app.post('/api/studio/stress', h.startStress);
      app.get('/api/studio/stress/:jobRunId', h.stressStatus);
      // What the planning agent reads after it submits, and the Agent tab's proxy to the agent.
      app.get('/api/studio/runs/:runId/report', h.runReport);
      app.get('/api/studio/scenarios/:scenarioId/report', h.scenarioReport);
      app.get('/api/studio/stress-tests/:stressId', h.stressResult);
      app.post('/api/studio/agent/turns', h.agentStart);
      app.get('/api/studio/agent/turns/:id', h.agentPoll);
    });
  },
}).catch(console.error);
