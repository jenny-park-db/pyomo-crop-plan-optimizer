import { expect, test } from 'vitest';
import writeXlsxFile from 'write-excel-file/node';
import { detailSheet, exportFileName, summarySheet } from './exportXlsx';
import { groupPlan, toPlanRow } from './resultsModel';

const rows = [
  toPlanRow({ field_id: 'F-1', grower_id: 'G-1', region: 'IA', soil_class: 'A', acres: '100', lat: '41', lon: '-93',
    hybrid_id: 'H-112', planting_window: 'W1', exp_yield: '200', exp_margin: '1000.4', is_fixed: 'true' }),
  toPlanRow({ field_id: 'F-3', grower_id: 'G-2', region: 'NE', soil_class: 'B', acres: '200', lat: '41', lon: '-99',
    hybrid_id: null, planting_window: null, exp_yield: '0', exp_margin: '0', is_fixed: 'false' }),
];

test('sheets have a bold header and typed cells; unplanted fields keep empty hybrid/window', () => {
  const summary = summarySheet(groupPlan(rows, 'region'), 'region');
  expect(summary[0][0]).toEqual({ value: 'region', fontWeight: 'bold' });
  expect(summary[1].map((c) => (c && typeof c === 'object' && 'value' in c ? c.value : c))).toEqual(['IA', 1, 100, 100, 0, 1000, 200]);
  const detail = detailSheet(rows);
  expect(detail).toHaveLength(3);
  expect(detail[2][5]).toBeNull();
  expect(exportFileName('baseline-2027', 'run-1')).toBe('crop-plan_baseline-2027_run-1.xlsx');
});

test('the workbook writes (same library, Node build)', async () => {
  const buffer = await writeXlsxFile([
    { data: summarySheet(groupPlan(rows, 'hybrid'), 'hybrid'), sheet: 'By hybrid' },
    { data: detailSheet(rows), sheet: 'Fields' },
  ]).toBuffer();
  expect(buffer.subarray(0, 2).toString()).toBe('PK'); // .xlsx is a zip
});
