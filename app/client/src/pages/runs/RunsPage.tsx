import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Table, TableBody, TableCell, TableHead,
  TableHeader, TableRow,
} from '@databricks/appkit-ui/react';
import { duration, when } from '../../../../shared/studio/format';
import { QueryState } from '../../components/QueryState';
import { StatusChip } from '../../components/StatusChip';
import { studioApi } from '../../studio/api';
import { usePolling } from '../../studio/usePolling';
import { useStudio } from '../../studio/StudioContext';
import { useStudioQuery } from '../../studio/useStudioQuery';
import { anyActive, DIAGNOSIS_LABEL, elapsedMs, sortRuns, terminationLabel, toRunView } from './runsModel';

export function RunsPage() {
  const { config, bump } = useStudio();
  const [params] = useSearchParams();
  const highlight = params.get('run');
  const scenarioFilter = params.get('scenario');
  const { rows, loading, error, warehouse } = useStudioQuery('runs');
  const [syncError, setSyncError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const runs = useMemo(() => {
    const all = sortRuns((rows ?? []).map((r) => toRunView(r, config)));
    return scenarioFilter ? all.filter((r) => r.scenario_id === scenarioFilter) : all;
  }, [rows, config, scenarioFilter]);
  const active = anyActive(runs);

  // While anything is active: reconcile with the Jobs API, then re-read the table (spec §3, §6.2).
  const tick = useCallback(async () => {
    try {
      await studioApi.sync();
      setSyncError(null);
    } catch (e) {
      setSyncError((e as Error).message);
    }
    setNow(Date.now());
    bump();
  }, [bump]);
  usePolling(active, tick, 5000);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Runs</CardTitle>
        <CardDescription>
          Every solve attempt, newest first. {active ? 'Refreshing every 5 s while runs are active.' : 'No active runs.'}
          {scenarioFilter && (
            <> Showing {scenarioFilter} only — <Link className="underline" to="/runs">show all</Link>.</>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {syncError && <p className="text-sm text-destructive">Couldn’t check job status: {syncError}</p>}
        <QueryState loading={loading} error={error} warehouseState={warehouse?.state} empty={runs.length === 0}
          emptyTitle="No runs yet" emptyDescription="Start one from Inputs."
          emptyAction={<Button asChild><Link to="/inputs">Go to Inputs</Link></Button>}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Scenario</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Triggered by</TableHead>
                <TableHead>Solver / model</TableHead>
                <TableHead>Submitted</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Termination</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>Links</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((r) => (
                <TableRow key={r.run_id} data-state={r.run_id === highlight ? 'selected' : undefined}>
                  <TableCell><StatusChip status={r.status} /></TableCell>
                  <TableCell>
                    <Link className="underline" to={`/results/${r.scenario_id}?run=${r.run_id}`}>{r.scenario_name}</Link>
                    <div className="text-xs text-muted-foreground">{r.run_id}</div>
                  </TableCell>
                  <TableCell>{r.source ?? '–'}</TableCell>
                  <TableCell>{r.triggered_by ?? '–'}</TableCell>
                  <TableCell>
                    {r.solver ?? '–'}
                    <div className="text-xs text-muted-foreground">{r.model_version ?? ''}</div>
                  </TableCell>
                  <TableCell>{when(r.submitted_ms ?? r.started_ms)}</TableCell>
                  <TableCell>{duration(elapsedMs(r, now))}</TableCell>
                  <TableCell>{terminationLabel(r)}</TableCell>
                  <TableCell className="max-w-sm whitespace-normal">
                    {r.reason ?? '–'}
                    {r.diagnosis && <div className="text-xs text-muted-foreground">{DIAGNOSIS_LABEL[r.diagnosis] ?? r.diagnosis}</div>}
                  </TableCell>
                  <TableCell className="space-x-2 whitespace-nowrap">
                    {r.job_run_url && <a className="underline" href={r.job_run_url} target="_blank" rel="noreferrer">Job run</a>}
                    {r.mlflow_url && <a className="underline" href={r.mlflow_url} target="_blank" rel="noreferrer">MLflow</a>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryState>
      </CardContent>
    </Card>
  );
}
