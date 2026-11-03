import { useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Tabs, TabsContent, TabsList, TabsTrigger } from '@databricks/appkit-ui/react';
import { BASELINE_ID } from '../../../../shared/studio/types';
import { QueryState } from '../../components/QueryState';
import { useStudioQuery } from '../../studio/useStudioQuery';
import { ComparePanel } from './ComparePanel';
import { LineageTree } from './LineageTree';
import { StressTab } from './StressTab';
import { buildLineage, toScenarioView } from './scenariosModel';

const MAX = 3;

export function ScenariosPage() {
  const q = useStudioQuery('scenarios');
  const scenarios = useMemo(() => (q.rows ?? []).map(toScenarioView), [q.rows]);
  const tree = useMemo(() => buildLineage(scenarios), [scenarios]);
  const [selected, setSelected] = useState<string[]>([BASELINE_ID, 'revision-1-2027']);
  const chosen = selected.map((id) => scenarios.find((s) => s.scenario_id === id)).filter((s) => s !== undefined);
  const toggle = (id: string) => setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(0, MAX)));

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Scenarios</CardTitle>
          <CardDescription>Lineage of every scenario. Tick up to {MAX} to compare; the first ticked is the base.</CardDescription>
        </CardHeader>
        <CardContent>
          <QueryState loading={q.loading} error={q.error} empty={scenarios.length === 0} emptyTitle="No scenarios"
            emptyDescription="Run the seed_data job to create the three seeded scenarios.">
            <LineageTree tree={tree} selected={selected} onToggle={toggle} maxSelected={MAX} />
          </QueryState>
        </CardContent>
      </Card>
      <Card className="xl:col-span-2">
        <CardContent className="pt-6">
          <Tabs defaultValue="compare">
            <TabsList>
              <TabsTrigger value="compare">Compare</TabsTrigger>
              <TabsTrigger value="stress">Stress test</TabsTrigger>
            </TabsList>
            <TabsContent value="compare"><ComparePanel chosen={chosen} /></TabsContent>
            <TabsContent value="stress"><StressTab chosen={chosen} /></TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
