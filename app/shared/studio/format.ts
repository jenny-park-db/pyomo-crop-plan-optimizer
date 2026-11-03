/**
 * Parsing and display helpers. The Statement Execution API returns BIGINT/INT/DOUBLE as JSON strings
 * (verified: "n_runs":"7"), whatever the generated types say, so every number read from a query goes
 * through num()/numOrNull(). Timestamps are selected as unix_millis(...) and read with toMs().
 */

export function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function num(value: unknown, fallback = 0): number {
  return numOrNull(value) ?? fallback;
}

/** Epoch milliseconds from a unix_millis() column (string or number), or null. */
export function toMs(value: unknown): number | null {
  return numOrNull(value);
}

const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

/** $18.81M for big numbers, $930 for small ones; "–" when missing. */
export function money(value: number | null, compact = true): string {
  if (value === null) return '–';
  if (compact && Math.abs(value) >= 1e6) return `${value < 0 ? '-' : ''}$${(Math.abs(value) / 1e6).toFixed(2)}M`;
  if (compact && Math.abs(value) >= 1e4) return `${value < 0 ? '-' : ''}$${(Math.abs(value) / 1e3).toFixed(1)}K`;
  return usd0.format(value);
}

/** Signed money delta, e.g. "+$28.3K" / "-$1.20M" / "±$0". */
export function moneyDelta(value: number | null): string {
  if (value === null) return '–';
  if (Math.round(value) === 0) return '±$0';
  return `${value > 0 ? '+' : ''}${money(value)}`;
}

/** A 0–1 fraction as a percentage with one decimal: 0.973 → "97.3%". */
export function pct(fraction: number | null, digits = 1): string {
  return fraction === null ? '–' : `${(fraction * 100).toFixed(digits)}%`;
}

/** "42 s", "3 min 05 s", "1 h 02 min". */
export function duration(ms: number | null): string {
  if (ms === null || ms < 0) return '–';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')} min`;
}

/** Local date-time with the zone name, so a reader never guesses whether a time is UTC. */
export function when(ms: number | null): string {
  if (ms === null) return '–';
  return new Date(ms).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  });
}

/** Python's f"{x:,.0f}": round half to even, thousands separators. Used by validate.ts for identical text. */
export function pyFixed0(x: number): string {
  const floor = Math.floor(x);
  const diff = x - floor;
  let r = diff > 0.5 ? floor + 1 : diff < 0.5 ? floor : floor % 2 === 0 ? floor : floor + 1;
  if (Object.is(r, -0)) r = 0;
  return r.toLocaleString('en-US');
}

/** Python repr() of a JSON-ish value, for messages that must match cropplan's text. */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (value === true) return 'True';
  if (value === false) return 'False';
  if (typeof value === 'string') return value.includes("'") && !value.includes('"') ? `"${value}"` : `'${value}'`;
  if (typeof value === 'number') return String(value);
  return JSON.stringify(value);
}

/** BOOLEAN columns arrive as "true"/"false". */
export function bool(value: unknown): boolean {
  return value === true || value === 'true';
}

/** A nullable STRING column. */
/**
 * A JSON column (to_json(...), scenarios.overrides). AppKit's analytics plugin decodes JSON-looking strings
 * before they reach the browser (seen in the deployed app), while the Statement Execution API returns the raw
 * string, so accept either. Unparseable or empty -> null.
 */
export function jsonValue(value: unknown): unknown {
  if (typeof value !== 'string') return value ?? null;
  if (value === '') return null;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

export function strOrNull(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  return typeof value === 'string' ? value : typeof value === 'object' ? JSON.stringify(value) : String(value as number | boolean);
}
