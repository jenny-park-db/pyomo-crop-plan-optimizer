import { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import {
  Badge, BarChart, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@databricks/appkit-ui/react';
import { money, num, strOrNull } from '../../../../shared/studio/format';
import { BASELINE_ID } from '../../../../shared/studio/types';
import { QueryState } from '../../components/QueryState';
import { studioApi } from '../../studio/api';
import { usePolling } from '../../studio/usePolling';
import { useStudio } from '../../studio/StudioContext';
import { useStudioQuery } from '../../studio/useStudioQuery';
import { sortRuns, toRunView } from '../runs/runsModel';
import { DrillDown } from './DrillDown';
import { FieldMap, HybridLegend } from './FieldMap';
import { KpiTiles } from './KpiTiles';
import { pickResultRun, resultsShouldPoll, toPlanRow, toSummary } from './resultsModel';

export function ResultsPage() {
  const { scenarioId = BASELINE_ID } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { config, bump } = useStudio();
  const scenarios = useStudioQuery('scenarios');
  const runsQ = useStudioQuery('runs');
  const runs = useMemo(() => sortRuns((runsQ.rows ?? []).map((r) => toRunView(r, config)).filter((r) => r.scenario_id === scenarioId)),
    [runsQ.rows, config, scenarioId]);
  const pick = pickResultRun(runs, params.get('run'));
  // While the run shown here is active, reconcile with the Jobs API (a dead job must not stay "queued"), then re-read.
  const tick = useCallback(async () => {
    await studioApi.sync().catch(() => undefined);
    bump();
  }, [bump]);
  usePolling(resultsShouldPoll(pick), tick, 5000);
  const runId = pick.kind === 'show' ? pick.run.run_id : pick.run?.run_id ?? '';
  const baseline = scenarios.rows?.find((s) => s.scenario_id === BASELINE_ID);
  const baselineRunId = scenarioId !== BASELINE_ID ? strOrNull(baseline?.latest_done_run_id) ?? '' : '';

  const summaryQ = useStudioQuery('run_summary', { run_id: runId }, pick.kind === 'show');
  const baseQ = useStudioQuery('run_summary', { run_id: baselineRunId }, pick.kind === 'show' && baselineRunId !== '');
  const planQ = useStudioQuery('plan_rows', { run_id: runId }, pick.kind === 'show');
  const seedQ = useStudioQuery('seed_utilization', { run_id: runId }, pick.kind === 'show');
  const violationsQ = useStudioQuery('violations', { run_id: runId }, runId !== '');
  const plan = useMemo(() => (planQ.rows ?? []).map(toPlanRow), [planQ.rows]);
  const [selected, setSelected] = useState<string | null>(null);
  const field = plan.find((r) => r.field_id === selected) ?? null;
  const summary = summaryQ.rows?.[0] ? toSummary(summaryQ.rows[0]) : null;
  const baseSummary = baseQ.rows?.[0] ? toSummary(baseQ.rows[0]) : null;
  const atLimit = (seedQ.rows ?? []).filter((r) => num(r.pct) >= 0.99).map((r) => String(r.hybrid_id));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-xl font-semibold">Results</h2>
        <Select value={scenarioId} onValueChange={(v) => void navigate(`/results/${v}`)}>
          <SelectTrigger aria-label="Scenario" className="w-80"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(scenarios.rows ?? []).map((s) => (
              <SelectItem key={String(s.scenario_id)} value={String(s.scenario_id)}>{String(s.name)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {pick.kind === 'show' && pick.note && <span className="text-sm text-muted-foreground">{pick.note}</span>}
      </div>

      <QueryState loading={runsQ.loading} error={runsQ.error} warehouseState={runsQ.warehouse?.state}
        empty={pick.kind === 'empty'} emptyTitle={pick.kind === 'empty' ? pick.title : ''}
        emptyDescription={pick.kind === 'empty' ? pick.description : ''}
        emptyAction={<div className="flex gap-2">
          <Button asChild variant="outline"><Link to={`/runs?scenario=${scenarioId}`}>See runs</Link></Button>
          <Button asChild><Link to={`/inputs?source=${scenarioId}`}>Open in Inputs</Link></Button>
        </div>}>
        {pick.kind === 'show' && (
          <QueryState loading={summaryQ.loading} error={summaryQ.error} empty={!summary} emptyTitle="No summary for this run">
            {summary && <KpiTiles summary={summary} baseline={baseSummary} baselineName={baseSummary ? String(baseline?.name) : null} />}
          </QueryState>
        )}
      </QueryState>

      {pick.kind === 'empty' && pick.run && (violationsQ.rows?.length ?? 0) > 0 && (
        <ViolationsCard rows={violationsQ.rows ?? []} title="What the solver found" />
      )}

      {pick.kind === 'show' && (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>Field map</CardTitle>
                <CardDescription>{summary?.unplanted_fields ?? 0} fields unplanted. Click a field for details.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <QueryState loading={planQ.loading} error={planQ.error} empty={plan.length === 0} emptyTitle="This run has no plan rows"
                  skeletonClassName="h-[420px] w-full">
                  <FieldMap rows={plan} selected={selected} onSelect={setSelected} />
                  <HybridLegend rows={plan} />
                </QueryState>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{field ? field.field_id : 'Field detail'}</CardTitle>
                <CardDescription>{field ? `${field.grower_id} · ${field.region} · soil ${field.soil_class}` : 'Select a field on the map.'}</CardDescription>
              </CardHeader>
              {field && (
                <CardContent className="text-sm space-y-1">
                  <div>{field.acres} acres</div>
                  <div>{field.hybrid_id ? `${field.hybrid_id}, window ${field.window}` : <Badge variant="destructive">unplanted</Badge>}</div>
                  {field.hybrid_id && <div>{field.exp_yield.toFixed(1)} bu/ac expected · {money(field.exp_margin, false)} margin</div>}
                  {field.is_fixed && <Badge variant="outline">grower fixed request</Badge>}
                </CardContent>
              )}
            </Card>
          </div>
          <Card>
            <CardHeader>
              <CardTitle>{atLimit.length ? `${atLimit.join(', ')} ${atLimit.length > 1 ? 'are' : 'is'} at the supply limit` : 'Seed utilization'}</CardTitle>
              <CardDescription>Units used as a share of units available, by hybrid (source: seed_utilization).</CardDescription>
            </CardHeader>
            <CardContent>
              <QueryState loading={seedQ.loading} error={seedQ.error} empty={(seedQ.rows ?? []).length === 0}>
                <BarChart data={(seedQ.rows ?? []).map((r) => ({ hybrid: String(r.hybrid_id), utilization: Math.round(num(r.pct) * 1000) / 10 }))}
                  xKey="hybrid" yKey="utilization" colorPalette="categorical" height={220}
                  valueFormatter={(v) => `${v}%`} ariaLabel="Seed utilization by hybrid" />
              </QueryState>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Plan detail</CardTitle></CardHeader>
            <CardContent>
              <QueryState loading={planQ.loading} error={planQ.error} empty={plan.length === 0}>
                <DrillDown rows={plan} scenarioId={scenarioId} runId={runId} />
              </QueryState>
            </CardContent>
          </Card>
          <QueryState loading={violationsQ.loading} error={violationsQ.error}>
            <ViolationsCard rows={violationsQ.rows ?? []} title="Violations and warnings" />
          </QueryState>
        </>
      )}
    </div>
  );
}

function ViolationsCard({ rows, title }: { rows: Array<Record<string, unknown>>; title: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>binding = what made the plan infeasible · error/warning = pre-solve checks · penalized = unplanted fields</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? <p className="text-sm text-muted-foreground">No violations.</p> : (
          <Table>
            <TableHeader><TableRow><TableHead>Severity</TableHead><TableHead>Rule</TableHead><TableHead>Entity</TableHead><TableHead>Detail</TableHead></TableRow></TableHeader>
            <TableBody>
              {rows.map((v) => (
                <TableRow key={`${String(v.severity)}|${String(v.rule)}|${String(v.entity)}|${String(v.detail)}`}>
                  <TableCell><Badge variant={['binding', 'error', 'hard'].includes(String(v.severity)) ? 'destructive' : 'outline'}>{String(v.severity)}</Badge></TableCell>
                  <TableCell>{String(v.rule)}</TableCell><TableCell>{String(v.entity)}</TableCell>
                  <TableCell className="whitespace-normal">{String(v.detail)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
