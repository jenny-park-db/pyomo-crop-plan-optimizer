/**
 * useAnalyticsQuery with the three parameters every config/queries/*.obo.sql file declares: catalog and
 * schema (from the bundle, via /api/studio/config) and refresh (bumped after writes; useAnalyticsQuery has
 * no refetch, and a remount reuses its client-side entry). While a refresh is in flight the previous rows
 * for the same query and parameters stay on screen, so polling never flashes a skeleton.
 * Rows come back untyped on purpose: numbers arrive as strings at runtime, so each screen maps rows
 * through its model's parser (num(), toMs(), …).
 */
import { useMemo, useState } from 'react';
import { useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useStudio } from './StudioContext';

export type Row = Record<string, unknown>;

/** Every query file in config/queries (keys come from the generated QueryRegistry). */
export type StudioQueryKey = Parameters<typeof useAnalyticsQuery>[0];

export function useStudioQuery(key: StudioQueryKey, params: Record<string, string> = {}, enabled = true) {
  const { config, refresh } = useStudio();
  const paramsKey = JSON.stringify(params);
  const parameters = useMemo(() => {
    const extra = JSON.parse(paramsKey) as Record<string, string>;
    return {
      catalog: sql.string(config.catalog),
      schema: sql.string(config.schema),
      refresh: sql.int(refresh),
      ...Object.fromEntries(Object.entries(extra).map(([k, v]) => [k, sql.string(v)])),
    };
  }, [config.catalog, config.schema, refresh, paramsKey]);
  const result = useAnalyticsQuery(key, parameters, { autoStart: enabled });
  const fresh = Array.isArray(result.data) ? (result.data as Row[]) : null;

  // "Store information from previous renders" (react.dev): setState during render, no refs or effects.
  const identity = `${key}:${paramsKey}`;
  const [last, setLast] = useState<{ key: string; rows: Row[] } | null>(null);
  if (fresh && (last?.key !== identity || last.rows !== fresh)) setLast({ key: identity, rows: fresh });
  const rows = fresh ?? (last?.key === identity ? last.rows : null);
  return {
    rows,
    loading: enabled && result.loading && rows === null,
    refreshing: enabled && result.loading && rows !== null,
    error: result.error,
    warehouse: result.warehouseStatus,
  };
}
