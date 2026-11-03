import { useCallback, useMemo, useState } from 'react';
import {
  Alert, AlertDescription, BarChart, Button, Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@databricks/appkit-ui/react';
import { money, num, when } from '../../../../shared/studio/format';
import { QueryState } from '../../components/QueryState';
import { studioApi, type StressStatus } from '../../studio/api';
import { usePolling } from '../../studio/usePolling';
import { useStudio } from '../../studio/StudioContext';
import { useStudioQuery } from '../../studio/useStudioQuery';
import { canStartLive, histogram, pickStress, toStressView, type ScenarioView, type StressView } from './scenariosModel';

const LIVE_N = 50;

function useMargins(s: StressView | null) {
  const q = useStudioQuery('stress_margins', { stress_id: s?.stress_id ?? '' }, s !== null);
  return { values: (q.rows ?? []).filter((r) => r.status === 'done').map((r) => num(r.gross_margin)), loading: q.loading, error: q.error };
}

/** Stored stress tests side by side (spec §6.4, demo step 7), with an optional live N=50 run. */
export function StressTab({ chosen }: { chosen: ScenarioView[] }) {
  const { config, bump } = useStudio();
  const q = useStudioQuery('stress_summaries');
  const all = useMemo(() => (q.rows ?? []).map(toStressView), [q.rows]);
  const picked = chosen.slice(0, 2).map((s) => ({ scenario: s, stress: pickStress(all, s.scenario_id) }));
  const m0 = useMargins(picked[0]?.stress ?? null);
  const m1 = useMargins(picked[1]?.stress ?? null);
  const series: Record<string, number[]> = {};
  if (picked[0]?.stress) series[picked[0].scenario.name] = m0.values;
  if (picked[1]?.stress) series[picked[1].scenario.name] = m1.values;
  const bins = histogram(series);
  const withP10 = picked.filter((p) => p.stress?.p10 !== null && p.stress?.p10 !== undefined);
  const best = withP10.length === 2 ? [...withP10].sort((x, y) => (y.stress!.p10 ?? 0) - (x.stress!.p10 ?? 0))[0] : null;

  const [live, setLive] = useState<{ scenario: string; job_run_id: string; status: StressStatus | null } | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const tick = useCallback(async () => {
    if (!live) return;
    try {
      const status = await studioApi.stressStatus(live.job_run_id);
      setLive({ ...live, status });
      if (status.state === 'succeeded') bump();
    } catch (e) {
      setLiveError((e as Error).message);
    }
  }, [live, bump]);
  usePolling(live !== null && (live.status === null || live.status.state === 'running'), tick, 10_000);

  async function startLive(scenarioId: string) {
    if (starting) return;
    setStarting(true);
    setLiveError(null);
    try {
      const r = await studioApi.startStress(scenarioId, LIVE_N);
      setLive({ scenario: scenarioId, job_run_id: r.job_run_id, status: null });
    } catch (e) {
      setLiveError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  return (
    <QueryState loading={q.loading} error={q.error} empty={all.length === 0} emptyTitle="No stress tests stored"
      emptyDescription="The precompute job stores N=500 runs for the baseline and Revision 1.">
      <div className="space-y-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {picked.map(({ scenario, stress }) => (
            <Card key={scenario.scenario_id}>
              <CardHeader>
                <CardTitle>{scenario.name}</CardTitle>
                <CardDescription>
                  {stress ? `${stress.stress_id} · ${stress.n_solved}/${stress.n} samples solved · ${when(stress.created_ms)}` : 'No stress test for this scenario yet.'}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {stress && (
                  <>
                    <div className="grid grid-cols-3 gap-2 tabular-nums">
                      <div><div className="text-xs text-muted-foreground">P10 gross margin</div>{money(stress.p10)}</div>
                      <div><div className="text-xs text-muted-foreground">P50</div>{money(stress.p50)}</div>
                      <div><div className="text-xs text-muted-foreground">P90</div>{money(stress.p90)}</div>
                    </div>
                    <div><span className="text-muted-foreground">Fragile fields: </span>{stress.fragile_fields.join(', ') || '–'}</div>
                    <div><span className="text-muted-foreground">Fragile hybrids: </span>{stress.fragile_hybrids.join(', ') || '–'}</div>
                    {stress.mlflow_run_id && config.experimentId && (
                      <a className="underline" target="_blank" rel="noreferrer"
                        href={`${config.host}/ml/experiments/${config.experimentId}/runs/${stress.mlflow_run_id}`}>MLflow run</a>
                    )}
                  </>
                )}
                <Button size="sm" variant="outline" disabled={!canStartLive(starting, live)}
                  onClick={() => void startLive(scenario.scenario_id)}>
                  {starting ? 'Starting…' : `Run live stress test (N=${LIVE_N})`}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
        {live && (
          <Alert>
            <AlertDescription>
              Live stress test for {live.scenario}: {live.status?.state ?? 'starting'} (job run {live.job_run_id}). Takes a few minutes; results
              appear in the stress-test list when it finishes.
              {live.status?.run_page_url && <> <a className="underline" href={live.status.run_page_url} target="_blank" rel="noreferrer">Job run</a></>}
              {live.status?.state === 'failed' && <> Failed: {live.status.message}</>}
            </AlertDescription>
          </Alert>
        )}
        {liveError && <Alert variant="destructive"><AlertDescription>{liveError}</AlertDescription></Alert>}
        <Card>
          <CardHeader>
            <CardTitle>
              {best ? `${best.scenario.name}'s P10 gross margin holds up better: ${money(best.stress!.p10)}` : 'Gross margin across disruption samples'}
            </CardTitle>
            <CardDescription>Samples per gross-margin bin; both scenarios on the same bins.</CardDescription>
          </CardHeader>
          <CardContent>
            <QueryState loading={m0.loading || m1.loading} error={m0.error ?? m1.error} empty={bins.length === 0} emptyTitle="No samples to plot">
              <BarChart data={bins} xKey="label" yKey={Object.keys(series)} colorPalette="categorical" height={260}
                ariaLabel="Distribution of gross margin across stress samples" />
            </QueryState>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>All stress tests</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            {all.map((s) => (
              <div key={s.stress_id} className="flex gap-3 tabular-nums">
                <span className="w-80 truncate">{s.stress_id}</span><span>{s.scenario_id}</span><span>n={s.n}</span>
                <span>P10 {money(s.p10)}</span><span className="text-muted-foreground">{s.triggered_by ?? ''} · {when(s.created_ms)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </QueryState>
  );
}
