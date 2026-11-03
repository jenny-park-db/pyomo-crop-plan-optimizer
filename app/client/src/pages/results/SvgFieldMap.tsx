import { useMemo } from 'react';
import { cssVar, hybridColors } from '../../studio/cssVar';
import type { FieldMapProps } from './FieldMap';
import { boundsOf, project, radiusFor } from './resultsModel';

const W = 900;
const H = 420;

/** Offline fallback (CROP_PLAN_MAP_MODE=svg): field points on a 1° lat/lon graticule, no tiles. */
export function SvgFieldMap({ rows, highlight = null, selected = null, onSelect, height = H }: FieldMapProps) {
  const colors = useMemo(() => hybridColors(rows.flatMap((r) => (r.hybrid_id ? [r.hybrid_id] : []))), [rows]);
  const b = boundsOf(rows);
  const maxAcres = Math.max(0, ...rows.map((r) => r.acres));
  const grid = cssVar('--border', 'lightgray');
  const red = cssVar('--destructive', 'red');
  const regions = [...new Set(rows.map((r) => r.region))].map((region) => {
    const rs = rows.filter((r) => r.region === region);
    return { region, ...project(rs.reduce((s, r) => s + r.lat, 0) / rs.length, rs.reduce((s, r) => s + r.lon, 0) / rs.length, b, W, H) };
  });
  const lats = Array.from({ length: Math.floor(b.maxLat) - Math.ceil(b.minLat) + 1 }, (_, i) => Math.ceil(b.minLat) + i);
  const lons = Array.from({ length: Math.floor(b.maxLon) - Math.ceil(b.minLon) + 1 }, (_, i) => Math.ceil(b.minLon) + i);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ height, width: '100%' }} role="img" aria-label="Field map (offline)" className="border rounded-md">
      {lats.map((lat) => {
        const a = project(lat, b.minLon, b, W, H);
        const z = project(lat, b.maxLon, b, W, H);
        return <line key={`lat${lat}`} x1={a.x} y1={a.y} x2={z.x} y2={z.y} stroke={grid} strokeWidth={0.5} />;
      })}
      {lons.map((lon) => {
        const a = project(b.minLat, lon, b, W, H);
        const z = project(b.maxLat, lon, b, W, H);
        return <line key={`lon${lon}`} x1={a.x} y1={a.y} x2={z.x} y2={z.y} stroke={grid} strokeWidth={0.5} />;
      })}
      {regions.map((r) => (
        <text key={r.region} x={r.x} y={r.y - 40} textAnchor="middle" fontSize={22} fill={cssVar('--muted-foreground', 'gray')}>{r.region}</text>
      ))}
      {rows.map((r) => {
        const p = project(r.lat, r.lon, b, W, H);
        const dim = highlight !== null && !highlight.has(r.field_id);
        const fill = r.hybrid_id ? colors.get(r.hybrid_id) ?? grid : 'none';
        return (
          <circle key={r.field_id} cx={p.x} cy={p.y} r={radiusFor(r.acres, maxAcres)} fill={fill} fillOpacity={dim ? 0.15 : 0.8}
            stroke={r.hybrid_id ? (r.field_id === selected ? cssVar('--foreground', 'black') : fill) : red}
            strokeWidth={r.hybrid_id ? (r.field_id === selected ? 3 : 1) : 2.5} opacity={dim ? 0.4 : 1}
            onClick={() => onSelect?.(r.field_id)} style={{ cursor: 'pointer' }}>
            <title>{r.field_id} · {r.hybrid_id ? `${r.hybrid_id} ${r.window}` : 'unplanted'} · {r.acres} ac</title>
          </circle>
        );
      })}
    </svg>
  );
}
