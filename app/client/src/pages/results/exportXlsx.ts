/** Export to Excel (spec §6.3): a grouped summary sheet and a field-level detail sheet, built in the browser. */
import type { Cell, SheetData } from 'write-excel-file/browser';
import type { GroupRow, Grouping, PlanRow } from './resultsModel';

export type SheetRows = SheetData;

const head = (labels: string[]): Cell[] => labels.map((value) => ({ value, fontWeight: 'bold' as const }));
/** A missing value is an empty cell (null), never the text "null". */
const n = (value: number | null): Cell => (value === null ? null : { value, type: Number });
const s = (value: string | null): Cell => (value === null ? null : { value, type: String });

export function summarySheet(groups: GroupRow[], by: Grouping): SheetRows {
  return [
    head([by, 'fields', 'acres', 'planted acres', 'unplanted fields', 'gross margin (USD)', 'yield (bu/ac)']),
    ...groups.map((g) => [s(g.key), n(g.fields), n(g.acres), n(g.planted_acres), n(g.unplanted_fields),
      n(Math.round(g.gross_margin)), n(g.yield_bu_ac === null ? null : Math.round(g.yield_bu_ac * 10) / 10)]),
  ];
}

export function detailSheet(rows: PlanRow[]): SheetRows {
  return [
    head(['field_id', 'grower_id', 'region', 'soil_class', 'acres', 'hybrid_id', 'window', 'exp_yield (bu/ac)',
      'exp_margin (USD)', 'is_fixed']),
    ...rows.map((r) => [s(r.field_id), s(r.grower_id), s(r.region), s(r.soil_class), n(r.acres), s(r.hybrid_id),
      s(r.window), n(r.exp_yield), n(Math.round(r.exp_margin)), { value: r.is_fixed, type: Boolean }]),
  ];
}

export function exportFileName(scenarioId: string, runId: string): string {
  return `crop-plan_${scenarioId}_${runId}.xlsx`;
}

/** Writes the workbook and triggers a download (write-excel-file is loaded on demand). */
export async function downloadPlan(scenarioId: string, runId: string, groups: GroupRow[], by: Grouping, rows: PlanRow[]): Promise<void> {
  const { default: writeXlsxFile } = await import('write-excel-file/browser');
  await writeXlsxFile([
    { data: summarySheet(groups, by), sheet: `By ${by}` },
    { data: detailSheet(rows), sheet: 'Fields' },
  ]).toFile(exportFileName(scenarioId, runId));
}
