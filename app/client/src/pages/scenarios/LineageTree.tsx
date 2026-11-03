import { Link } from 'react-router';
import { Badge, Button, Checkbox } from '@databricks/appkit-ui/react';
import { StatusChip } from '../../components/StatusChip';
import { flatten, type LineageNode } from './scenariosModel';

interface Props {
  tree: LineageNode[];
  selected: string[];
  onToggle: (scenarioId: string) => void;
  maxSelected: number;
}

/** Scenario lineage (spec §6.4): indentation = parent → child; pick up to three to compare. */
export function LineageTree({ tree, selected, onToggle, maxSelected }: Props) {
  return (
    <ul className="space-y-1" aria-label="Scenario lineage">
      {flatten(tree).map(({ scenario: s, depth }) => {
        const checked = selected.includes(s.scenario_id);
        return (
          <li key={s.scenario_id} className="flex items-center gap-2 text-sm" style={{ paddingLeft: depth * 24 }}>
            <Checkbox aria-label={`Compare ${s.name}`} checked={checked}
              disabled={!checked && selected.length >= maxSelected} onCheckedChange={() => onToggle(s.scenario_id)} />
            {depth > 0 && <span className="text-muted-foreground">└</span>}
            <span className="font-medium">{s.name}</span>
            <span className="text-xs text-muted-foreground">{s.scenario_id}</span>
            {s.source && <Badge variant="outline">{s.source}</Badge>}
            {s.latest_status && <StatusChip status={s.latest_status} />}
            <span className="ml-auto flex gap-1">
              <Button asChild size="sm" variant="ghost"><Link to={`/results/${s.scenario_id}`}>Results</Link></Button>
              <Button asChild size="sm" variant="ghost"><Link to={`/inputs?source=${s.scenario_id}`}>Clone</Link></Button>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
