import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@databricks/appkit-ui/react';
import { money, moneyDelta, pct, when } from '../../../../shared/studio/format';
import { delta, type Summary } from './resultsModel';

interface Tile {
  label: string;
  value: string;
  unit: string;
  comparison: string | null;
}

function tiles(s: Summary, base: Summary | null, baseName: string | null): Tile[] {
  const vs = (d: number | null, fmt: (x: number | null) => string) => (base && baseName ? `${fmt(d)} vs ${baseName}` : null);
  const pp = (d: number | null) => (d === null ? '–' : `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)} pts`);
  const count = (d: number | null) => (d === null ? '–' : `${d >= 0 ? '+' : ''}${d}`);
  return [
    { label: 'Gross margin', value: money(s.gross_margin), unit: 'USD, expected', comparison: vs(delta(s.gross_margin, base?.gross_margin ?? null), moneyDelta) },
    { label: 'Net margin', value: money(s.net_margin), unit: `USD, after ${money(s.unplanted_penalty_total)} unplanted penalty`, comparison: vs(delta(s.net_margin, base?.net_margin ?? null), moneyDelta) },
    { label: 'Planted', value: pct(s.acres_planted_pct), unit: 'of acres', comparison: vs(delta(s.acres_planted_pct, base?.acres_planted_pct ?? null), pp) },
    { label: 'Unplanted fields', value: String(s.unplanted_fields ?? '–'), unit: 'fields', comparison: vs(delta(s.unplanted_fields, base?.unplanted_fields ?? null), count) },
    { label: 'Hybrids at supply limit', value: String(s.hybrids_at_limit ?? '–'), unit: 'seed utilization ≥ 99%', comparison: vs(delta(s.hybrids_at_limit, base?.hybrids_at_limit ?? null), count) },
  ];
}

/** KPI tiles: value + unit + comparison + provenance (which run, when it finished). */
export function KpiTiles({ summary, baseline, baselineName }: { summary: Summary; baseline: Summary | null; baselineName: string | null }) {
  return (
    <div className="space-y-1">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {tiles(summary, baseline, baselineName).map((t) => (
          <Card key={t.label}>
            <CardHeader className="pb-1">
              <CardDescription>{t.label}</CardDescription>
              <CardTitle className="text-2xl tabular-nums">{t.value}</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground space-y-0.5">
              <div>{t.unit}</div>
              {t.comparison && <div>{t.comparison}</div>}
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Run {summary.run_id} · solved {when(summary.ended_ms)} · {summary.termination ?? ''}
        {summary.mip_gap !== null && summary.termination !== 'optimal' ? ` (gap ${(summary.mip_gap * 100).toFixed(2)}%)` : ''} · source: run_summary
      </p>
    </div>
  );
}
