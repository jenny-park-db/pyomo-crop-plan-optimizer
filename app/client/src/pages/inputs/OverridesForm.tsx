import { Input, Label, Switch } from '@databricks/appkit-ui/react';
import { WINDOWS } from '../../../../shared/studio/types';
import type { FormState } from './formModel';

interface Props {
  form: FormState;
  onChange: (next: FormState) => void;
  disabled?: boolean;
}

function NumberField({ id, label, value, suffix, onChange, disabled }: {
  id: string; label: string; value: string; suffix?: string; onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-1">
        <Input id={id} inputMode="decimal" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        {suffix && <span className="text-sm text-muted-foreground">{suffix}</span>}
      </div>
    </div>
  );
}

/** The overrides schema (spec §3 "Scenario settings") as a form. Blank multipliers mean 100%. */
export function OverridesForm({ form, onChange, disabled }: Props) {
  const set = (patch: Partial<FormState>) => onChange({ ...form, ...patch });
  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Seed supply (% of available units)</h3>
        <div className="grid grid-cols-4 gap-3">
          {Object.entries(form.supply).map(([h, v]) => (
            <NumberField key={h} id={`supply-${h}`} label={h} value={v} suffix="%" disabled={disabled}
              onChange={(text) => set({ supply: { ...form.supply, [h]: text } })} />
          ))}
        </div>
      </section>
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Planting capacity (% of acres per window)</h3>
        <div className="grid grid-cols-5 gap-2 items-end">
          <span />
          {WINDOWS.map((w) => <span key={w} className="text-xs text-muted-foreground">{w}</span>)}
          {Object.entries(form.capacity).map(([r, windows]) => (
            <div key={r} className="contents">
              <span className="text-sm">{r}</span>
              {WINDOWS.map((w) => (
                <Input key={w} aria-label={`Capacity ${r} ${w} %`} inputMode="decimal" value={windows[w] ?? ''} disabled={disabled}
                  placeholder="100"
                  onChange={(e) => set({ capacity: { ...form.capacity, [r]: { ...windows, [w]: e.target.value } } })} />
              ))}
            </div>
          ))}
        </div>
      </section>
      <section className="grid grid-cols-3 gap-3">
        <NumberField id="diversity" label="Diversity cap (share of a grower's acres)" value={form.diversity_cap_pct} suffix="%"
          disabled={disabled} onChange={(v) => set({ diversity_cap_pct: v })} />
        <NumberField id="penalty" label="Unplanted penalty" value={form.unplanted_penalty_per_acre} suffix="$/acre"
          disabled={disabled} onChange={(v) => set({ unplanted_penalty_per_acre: v })} />
        <NumberField id="price" label="Corn price" value={form.corn_price_per_bu} suffix="$/bu" disabled={disabled}
          onChange={(v) => set({ corn_price_per_bu: v })} />
        <NumberField id="time" label="Solver time limit" value={form.time_limit_s} suffix="s" disabled={disabled}
          onChange={(v) => set({ time_limit_s: v })} />
        <NumberField id="gap" label="MIP gap" value={form.mip_rel_gap_pct} suffix="%" disabled={disabled}
          onChange={(v) => set({ mip_rel_gap_pct: v })} />
        <div className="flex items-center gap-2 pt-6">
          <Switch id="fixed" checked={form.fixed_requests_enabled} disabled={disabled}
            onCheckedChange={(checked) => set({ fixed_requests_enabled: checked })} />
          <Label htmlFor="fixed">Honor grower fixed requests</Label>
        </div>
      </section>
      <p className="text-xs text-muted-foreground">
        Solver {form.rest.solver}, threads {form.rest.threads ?? 'auto'}, seed {form.rest.random_seed ?? 'none'} — edit these as JSON.
      </p>
    </div>
  );
}
