import { useEffect, useMemo, useReducer, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import {
  Alert, AlertDescription, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Select,
  SelectContent, SelectItem, SelectTrigger, SelectValue, Switch, Textarea,
} from '@databricks/appkit-ui/react';
import { parseOverridesText } from '../../../../shared/studio/overrides';
import { BASELINE_ID } from '../../../../shared/studio/types';
import { validateScenario } from '../../../../shared/studio/validate';
import { QueryState } from '../../components/QueryState';
import { ApiError, studioApi } from '../../studio/api';
import { useStudio } from '../../studio/StudioContext';
import { useStudioQuery } from '../../studio/useStudioQuery';
import { OverridesForm } from './OverridesForm';
import { ValidationPanel } from './ValidationPanel';
import {
  canRun, formFromOverrides, formToOverrides, inputsFromRow, sameOverrides, storedOverrides, submitReducer,
  type FormState, type RunMode, type SubmitEvent, type SubmitState,
} from './formModel';
import { newRunId } from '../../../../shared/studio/ids';

export function InputsPage() {
  const [params, setParams] = useSearchParams();
  const sourceId = params.get('source') ?? BASELINE_ID;
  const scenarios = useStudioQuery('scenarios');
  const inputsQ = useStudioQuery('scenario_inputs', { scenario_id: sourceId });
  const source = scenarios.rows?.find((s) => s.scenario_id === sourceId) ?? null;
  const sourceOverrides = useMemo(() => storedOverrides(source?.overrides), [source?.overrides]);
  const inputs = useMemo(() => (inputsQ.rows?.[0] ? inputsFromRow(inputsQ.rows[0]) : null), [inputsQ.rows]);

  const hybrids = useMemo(() => (inputs?.hybrids ?? []).map((h) => h.hybrid_id).sort(), [inputs]);
  const regions = useMemo(() => [...new Set((inputs?.fields ?? []).map((f) => f.region))].sort(), [inputs]);
  const [form, setForm] = useState<FormState | null>(null);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [name, setName] = useState('');
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submit, dispatch] = useReducer((s: SubmitState, e: SubmitEvent) => submitReducer(s, e), undefined,
    (): SubmitState => ({ runId: newRunId(), submitting: false }));
  const { bump } = useStudio();
  const navigate = useNavigate();

  // Reset the form whenever the source scenario (or its inputs) change.
  const formKey = `${sourceId}|${hybrids.join(',')}|${regions.join(',')}|${source ? 'loaded' : ''}`;
  const [loadedKey, setLoadedKey] = useState('');
  if (inputs && source && loadedKey !== formKey) {
    setLoadedKey(formKey);
    setForm(formFromOverrides(sourceOverrides, hybrids, regions));
    setJsonText(JSON.stringify(sourceOverrides, null, 2));
  }

  const parsed = jsonMode ? parseOverridesText(jsonText) : form ? formToOverrides(form) : parseOverridesText('');
  const issues = useMemo(() => (inputs && parsed.ok ? validateScenario(inputs, parsed.overrides) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [inputs, parsed.ok && JSON.stringify(parsed.overrides)]);
  const dirty = parsed.ok ? !sameOverrides(parsed.overrides, sourceOverrides) : true;
  const args = { parsed, issues: parsed.ok ? issues : [], name, dirty, submitting: submit.submitting };
  const runNew = canRun('new', args);
  const runSame = canRun('resolve', args);

  useEffect(() => setSubmitError(null), [sourceId]);

  async function go(mode: RunMode) {
    if (submit.submitting || !parsed.ok) return;
    dispatch({ type: 'start' });
    setSubmitError(null);
    try {
      const r = await studioApi.submit(mode === 'new'
        ? { mode, source_scenario_id: sourceId, run_id: submit.runId, name, overrides: parsed.overrides }
        : { mode, source_scenario_id: sourceId, run_id: submit.runId });
      dispatch({ type: 'succeeded' });
      bump();
      void navigate(`/runs?run=${encodeURIComponent(r.run_id)}`);
    } catch (e) {
      dispatch({ type: 'failed' });
      setSubmitError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle>Inputs</CardTitle>
          <CardDescription>Start from the 2027 Baseline or clone any scenario, adjust its settings, and run the solver.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Start from</Label>
              <Select value={sourceId} onValueChange={(v) => setParams({ source: v })}>
                <SelectTrigger aria-label="Source scenario"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(scenarios.rows ?? []).map((s) => (
                    <SelectItem key={String(s.scenario_id)} value={String(s.scenario_id)}>
                      {String(s.name)} ({String(s.scenario_id)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="name">New scenario name</Label>
              <Input id="name" placeholder="e.g. Revision A" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            </div>
          </div>
          <QueryState loading={inputsQ.loading || scenarios.loading} error={inputsQ.error ?? scenarios.error}
            warehouseState={inputsQ.warehouse?.state} empty={!!inputs && inputs.fields.length === 0}
            emptyTitle="This scenario has no inputs" emptyDescription="Pick another scenario to start from.">
            <div className="flex items-center gap-2">
              <Switch id="json" checked={jsonMode} onCheckedChange={(on) => {
                if (on && parsed.ok) setJsonText(JSON.stringify(parsed.overrides, null, 2));
                setJsonMode(on);
              }} />
              <Label htmlFor="json">Edit as JSON</Label>
            </div>
            {jsonMode ? (
              <Textarea aria-label="Overrides JSON" className="font-mono text-xs h-80" value={jsonText}
                onChange={(e) => setJsonText(e.target.value)} />
            ) : form && <OverridesForm form={form} onChange={setForm} disabled={submit.submitting} />}
          </QueryState>
          {submitError && <Alert variant="destructive"><AlertDescription>{submitError}</AlertDescription></Alert>}
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={!runNew.enabled} onClick={() => void go('new')}>Run as new scenario</Button>
            <Button variant="outline" disabled={!runSame.enabled} onClick={() => void go('resolve')}>
              Re-solve {source ? String(source.name) : sourceId} unchanged
            </Button>
            <span className="text-sm text-muted-foreground">{runNew.reason ?? runSame.reason ?? ''}</span>
          </div>
        </CardContent>
      </Card>
      <ValidationPanel issues={parsed.ok ? issues : null} parseError={parsed.ok ? null : parsed.error} />
    </div>
  );
}
