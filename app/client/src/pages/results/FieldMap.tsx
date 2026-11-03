import { useMemo } from 'react';
import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { cssVar, hybridColors } from '../../studio/cssVar';
import { useStudio } from '../../studio/StudioContext';
import { boundsOf, radiusFor, type PlanRow } from './resultsModel';
import { SvgFieldMap } from './SvgFieldMap';

export interface FieldMapProps {
  rows: PlanRow[];
  /** Fields to emphasize (Compare's change map); others are drawn muted. Null = all normal. */
  highlight?: Set<string> | null;
  selected?: string | null;
  onSelect?: (fieldId: string) => void;
  height?: number;
}

/** Field map (spec §6.3): color = hybrid, size = acres, red outline = unplanted, click → detail. */
export function FieldMap(props: FieldMapProps) {
  const { config } = useStudio();
  if (config.mapMode === 'svg') return <SvgFieldMap {...props} />;
  return <TileMap {...props} />;
}

function TileMap({ rows, highlight = null, selected = null, onSelect, height = 420 }: FieldMapProps) {
  const colors = useMemo(() => hybridColors(rows.flatMap((r) => (r.hybrid_id ? [r.hybrid_id] : []))), [rows]);
  const b = boundsOf(rows);
  const maxAcres = Math.max(0, ...rows.map((r) => r.acres));
  const red = cssVar('--destructive', 'red');
  const muted = cssVar('--muted-foreground', 'gray');
  return (
    <div style={{ height }} className="rounded-md overflow-hidden border">
      <MapContainer bounds={[[b.minLat, b.minLon], [b.maxLat, b.maxLon]]} style={{ height: '100%' }} scrollWheelZoom={false}>
        <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
        {rows.map((r) => {
          const dim = highlight !== null && !highlight.has(r.field_id);
          const fill = r.hybrid_id ? colors.get(r.hybrid_id) ?? muted : 'transparent';
          return (
            <CircleMarker key={r.field_id} center={[r.lat, r.lon]} radius={radiusFor(r.acres, maxAcres)}
              eventHandlers={{ click: () => onSelect?.(r.field_id) }}
              pathOptions={{
                color: r.hybrid_id ? (r.field_id === selected ? cssVar('--foreground', 'black') : fill) : red,
                weight: r.hybrid_id ? (r.field_id === selected ? 3 : 1) : 2.5,
                fillColor: fill, fillOpacity: dim ? 0.15 : 0.75, opacity: dim ? 0.3 : 1,
              }}>
              <Tooltip>{r.field_id} · {r.hybrid_id ? `${r.hybrid_id} ${r.window}` : 'unplanted'} · {r.acres} ac</Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}

export function HybridLegend({ rows }: { rows: PlanRow[] }) {
  const colors = useMemo(() => hybridColors(rows.flatMap((r) => (r.hybrid_id ? [r.hybrid_id] : []))), [rows]);
  return (
    <div className="flex flex-wrap gap-3 text-xs" aria-label="Hybrid colors">
      {[...colors.entries()].map(([h, c]) => (
        <span key={h} className="flex items-center gap-1">
          <span className="inline-block size-3 rounded-full" style={{ backgroundColor: c }} />{h}
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span className="inline-block size-3 rounded-full border-2" style={{ borderColor: 'var(--destructive)' }} />unplanted
      </span>
      <span className="text-muted-foreground">size = acres</span>
    </div>
  );
}
