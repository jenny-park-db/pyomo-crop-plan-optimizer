import { useMemo, useState } from 'react';
import {
  Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Table, TableBody, TableCell, TableHead,
  TableHeader, TableRow,
} from '@databricks/appkit-ui/react';
import { money } from '../../../../shared/studio/format';
import { WINDOWS } from '../../../../shared/studio/types';
import { downloadPlan } from './exportXlsx';
import { filterPlan, groupPlan, GROUPINGS, type Filters, type Grouping, type PlanRow } from './resultsModel';

const ALL = '__all__';

function FilterSelect({ label, value, options, onChange }: { label: string; value: string | null; options: string[]; onChange: (v: string | null) => void }) {
  return (
    <Select value={value ?? ALL} onValueChange={(v) => onChange(v === ALL ? null : v)}>
      <SelectTrigger aria-label={label} className="w-36"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>All {label.toLowerCase()}s</SelectItem>
        {options.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

/** Drill-down by region/grower/field/hybrid/window with filters and Export to Excel (spec §6.3). */
export function DrillDown({ rows, scenarioId, runId }: { rows: PlanRow[]; scenarioId: string; runId: string }) {
  const [by, setBy] = useState<Grouping>('region');
  const [filters, setFilters] = useState<Filters>({ region: null, hybrid: null, window: null });
  const [exportError, setExportError] = useState<string | null>(null);
  const filtered = useMemo(() => filterPlan(rows, filters), [rows, filters]);
  const groups = useMemo(() => groupPlan(filtered, by), [filtered, by]);
  const regions = [...new Set(rows.map((r) => r.region))].sort();
  const hybrids = [...[...new Set(rows.flatMap((r) => (r.hybrid_id ? [r.hybrid_id] : [])))].sort(), 'Unplanted'];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm">Group by</span>
        <Select value={by} onValueChange={(v) => setBy(v as Grouping)}>
          <SelectTrigger aria-label="Group by" className="w-32"><SelectValue /></SelectTrigger>
          <SelectContent>{GROUPINGS.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}</SelectContent>
        </Select>
        <FilterSelect label="Region" value={filters.region} options={regions} onChange={(region) => setFilters({ ...filters, region })} />
        <FilterSelect label="Hybrid" value={filters.hybrid} options={hybrids} onChange={(hybrid) => setFilters({ ...filters, hybrid })} />
        <FilterSelect label="Window" value={filters.window} options={[...WINDOWS, 'Unplanted']} onChange={(window) => setFilters({ ...filters, window })} />
        <Button variant="outline" className="ml-auto" disabled={filtered.length === 0}
          onClick={() => void downloadPlan(scenarioId, runId, groups, by, filtered).catch((e: Error) => setExportError(e.message))}>
          Export to Excel
        </Button>
      </div>
      {exportError && <p className="text-sm text-destructive">Export failed: {exportError}</p>}
      {filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">No fields match these filters.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{by}</TableHead><TableHead className="text-right">Fields</TableHead>
              <TableHead className="text-right">Acres</TableHead><TableHead className="text-right">Planted acres</TableHead>
              <TableHead className="text-right">Unplanted fields</TableHead><TableHead className="text-right">Gross margin</TableHead>
              <TableHead className="text-right">Yield (bu/ac)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((g) => (
              <TableRow key={g.key}>
                <TableCell>{g.key}</TableCell><TableCell className="text-right tabular-nums">{g.fields}</TableCell>
                <TableCell className="text-right tabular-nums">{g.acres.toLocaleString('en-US')}</TableCell>
                <TableCell className="text-right tabular-nums">{g.planted_acres.toLocaleString('en-US')}</TableCell>
                <TableCell className="text-right tabular-nums">{g.unplanted_fields}</TableCell>
                <TableCell className="text-right tabular-nums">{money(g.gross_margin, false)}</TableCell>
                <TableCell className="text-right tabular-nums">{g.yield_bu_ac === null ? '–' : g.yield_bu_ac.toFixed(1)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
