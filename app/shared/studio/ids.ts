/** ID rules shared with cropplan_jobs.tables.check_id: IDs end up in SQL predicates and volume paths. */

export const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export class IdError extends Error {}

export function checkId(value: unknown, what = 'id'): string {
  if (typeof value !== 'string' || !ID_PATTERN.test(value)) {
    throw new IdError(`${what} must be 1-64 letters, digits, '.', '_' or '-', got ${JSON.stringify(value)}`);
  }
  return value;
}

function stamp(now: Date): string {
  return now.toISOString().replace(/[-:T]/g, '').slice(0, 14); // yyyymmddHHMMSS (UTC)
}

function suffix(random: () => number): string {
  return Array.from({ length: 6 }, () => 'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(random() * 36)]).join('');
}

/** Idempotency key for one submit: the browser makes it once per form and reuses it on a double click. */
export function newRunId(now: Date = new Date(), random: () => number = Math.random): string {
  return `app-${stamp(now)}-${suffix(random)}`;
}

/**
 * Scenario ID for "Run as new scenario": a slug of the name plus the run_id's random tail, so the same
 * submit always maps to the same scenario (dedupe) and two scenarios with one name never collide.
 */
export function scenarioIdFor(name: string, runId: string): string {
  const tail = runId.slice(-6);
  const slug = name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
    .replace(/-+$/g, '');
  return checkId(`${slug || 'scenario'}-${tail}`, 'scenario_id');
}

/** stress_id for a live run started from the app; the random part keeps two starts in one second apart. */
export function stressIdFor(scenarioId: string, n: number, now: Date = new Date(), random: () => number = Math.random): string {
  return checkId(`st-${stamp(now)}-${suffix(random)}-n${n}-${scenarioId}`.slice(0, 64).replace(/[-._]+$/, ''), 'stress_id');
}

export const NAME_MAX = 80;

/** A scenario name: trimmed, 1–80 characters, no control characters. Returns the cleaned name or an error. */
export function checkName(raw: unknown): { ok: true; name: string } | { ok: false; error: string } {
  if (typeof raw !== 'string') return { ok: false, error: 'Give the scenario a name.' };
  const name = raw.replace(/\s+/g, ' ').trim();
  if (!name) return { ok: false, error: 'Give the scenario a name.' };
  if (name.length > NAME_MAX) return { ok: false, error: `Keep the name under ${NAME_MAX} characters.` };
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(name)) return { ok: false, error: 'The name contains control characters.' };
  return { ok: true, name };
}
