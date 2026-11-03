import { CHART_COLOR_VARS_CATEGORICAL } from '@databricks/appkit-ui/react';

/** Resolve an AppKit-ui CSS variable to a concrete color (Leaflet and SVG attributes can't use var()). */
export function cssVar(name: string, fallback = 'currentColor'): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Stable categorical color per hybrid: sorted hybrid IDs → --chart-cat-1 … --chart-cat-8. */
export function hybridColors(hybrids: string[]): Map<string, string> {
  const sorted = [...new Set(hybrids)].sort();
  return new Map(sorted.map((h, i) => [h, cssVar(CHART_COLOR_VARS_CATEGORICAL[i % CHART_COLOR_VARS_CATEGORICAL.length])]));
}
