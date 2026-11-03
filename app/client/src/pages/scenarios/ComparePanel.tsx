import { useState } from 'react';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle, Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@databricks/appkit-ui/react';
import { money, moneyDelta, pct } from '../../../../shared/studio/format';
import { QueryState } from '../../components/QueryState';
import { useStudioQuery } from '../../studio/useStudioQuery';
import { FieldMap, HybridLegend } from '../results/FieldMap';
import { delta, toPlanRow, toSummary, type PlanRow, type Summary } from '../results/resultsModel';
import { diffPlans, type ScenarioView } from './scenariosModel';

/** One scenario's latest done run: summary + plan. Hooks per slot, because a hook can't be called in a loop. */
function useSlot(s: ScenarioView | undefined) {
  const runId = s?.latest_done_run_id ?? '';
  const summary = useStudioQuery('run_summary', { run_id: runId }, runId !== '');
  const plan = useStudioQuery('plan_rows', { run_id: runId }, runId !== '');
  return {
    scenario: s,
    summary: summary.rows?.[0] ? toSummary(summary.rows[0]) : null,
    plan: (plan.rows ?? []).map(toPlanRow),
    loading: summary.loading || plan.loading,
    error: summary.error ?? plan.error,
  };
}

type Slot = ReturnType<typeof useSlot>;

/** Compare 2–3 scenarios (spec §6.4): gross-margin deltas against the first, changed fields, change map. */
export function ComparePanel({ chosen }: { chosen: ScenarioView[] }) {
  const a = useSlot(chosen[0]);
  const b = useSlot(chosen[1]);
  const c = useSlot(chosen[2]);
  const slots = [a, b, c].filter((s): s is Slot & { scenario: ScenarioView } => s.scenario !== undefined);
  const [against, setAgainst] = useState(1);
  const other = slots[Math.min(against, slots.length - 1)];
  const changes = slots.length > 1 ? diffPlans(a.plan, other.plan) : [];
  const changedIds = new Set(changes.map((x) => x.field_id));
  const missingRun = slots.filter((s) => !s.scenario.latest_done_run_id);

  if (slots.length < 2) {
    return <p className="text-sm text-muted-foreground">Pick two or three scenarios in the lineage to compare them.</p>;
  }
  const rows: Array<[string, (s: Summary) => string, ((s: Summary, base: Summary) => string) | null]> = [
    ['Gross margin', (s) => money(s.gross_margin), (s, base) => moneyDelta(delta(s.gross_margin, base.gross_margin))],
    ['Net margin', (s) => money(s.net_margin), (s, base) => moneyDelta(delta(s.net_margin, base.net_margin))],
    ['Planted', (s) => pct(s.acres_planted_pct), null],
    ['Unplanted fields', (s) => String(s.unplanted_fields ?? '–'), null],
    ['Hybrids at supply limit', (s) => String(s.hybrids_at_limit ?? '–'), null],
  ];
  const base = a.summary;
  const gm = other?.summary && base ? delta(other.summary.gross_margin, base.gross_margin) : null;
  return (
    <div className="space-y-4">
      {missingRun.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {missingRun.map((s) => s.scenario.name).join(', ')} {missingRun.length > 1 ? 'have' : 'has'} no successful run yet.
        </p>
      )}
      <QueryState loading={slots.some((s) => s.loading)} error={slots.find((s) => s.error)?.error ?? null}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>KPI</TableHead>
              {slots.map((s, i) => <TableHead key={s.scenario.scenario_id} className="text-right">{s.scenario.name}{i === 0 ? ' (base)' : ''}</TableHead>)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([label, value, diff]) => (
              <TableRow key={label}>
                <TableCell>{label}</TableCell>
                {slots.map((s, i) => (
                  <TableCell key={s.scenario.scenario_id} className="text-right tabular-nums">
                    {s.summary ? value(s.summary) : '–'}
                    {i > 0 && diff && s.summary && base && <div className="text-xs text-muted-foreground">{diff(s.summary, base)}</div>}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </QueryState>
      <Card>
        <CardHeader>
          <CardTitle>
            {other ? `${changes.length} fields change from ${a.scenario?.name} to ${other.scenario.name}` : 'Changed fields'}
            {gm !== null && ` · gross margin ${moneyDelta(gm)}`}
          </CardTitle>
          <CardDescription className="flex items-center gap-2">
            Compare the base against
            {slots.length > 2 && (
              <Select value={String(against)} onValueChange={(v) => setAgainst(Number(v))}>
                <SelectTrigger aria-label="Compare against" className="w-56"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {slots.slice(1).map((s, i) => <SelectItem key={s.scenario.scenario_id} value={String(i + 1)}>{s.scenario.name}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="space-y-2">
            <FieldMap rows={other?.plan ?? ([] as PlanRow[])} highlight={changedIds} height={360} />
            <HybridLegend rows={other?.plan ?? []} />
            <p className="text-xs text-muted-foreground">Colors show the compared scenario’s plan; unchanged fields are faded.</p>
          </div>
          <div className="max-h-[400px] overflow-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Field</TableHead><TableHead>Region</TableHead><TableHead>From</TableHead><TableHead>To</TableHead><TableHead className="text-right">Margin Δ</TableHead></TableRow></TableHeader>
              <TableBody>
                {changes.map((x) => (
                  <TableRow key={x.field_id}>
                    <TableCell>{x.field_id}</TableCell><TableCell>{x.region}</TableCell><TableCell>{x.from}</TableCell><TableCell>{x.to}</TableCell>
                    <TableCell className="text-right tabular-nums">{moneyDelta(x.margin_delta)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
