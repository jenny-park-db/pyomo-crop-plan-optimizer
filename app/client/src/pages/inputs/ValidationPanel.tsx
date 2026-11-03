import { Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@databricks/appkit-ui/react';
import type { Issue } from '../../../../shared/studio/types';

/** Pre-solve checks (spec §6.1): errors block Run, warnings don't. The job repeats them before solving. */
export function ValidationPanel({ issues, parseError }: { issues: Issue[] | null; parseError: string | null }) {
  const errors = (issues ?? []).filter((i) => i.severity === 'error');
  const warnings = (issues ?? []).filter((i) => i.severity === 'warning');
  return (
    <Card>
      <CardHeader>
        <CardTitle>Validation</CardTitle>
        <CardDescription>
          {parseError ? 'Settings are not valid yet.'
            : issues === null ? 'Loading the scenario inputs…'
              : errors.length ? `${errors.length} error${errors.length > 1 ? 's' : ''} block the run.`
                : warnings.length ? `Passes, with ${warnings.length} warning${warnings.length > 1 ? 's' : ''}.` : 'Passes all pre-solve checks.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {parseError && (
          <Alert variant="destructive">
            <AlertTitle>Settings</AlertTitle>
            <AlertDescription>{parseError}</AlertDescription>
          </Alert>
        )}
        {[...errors, ...warnings].map((i) => (
          <div key={`${i.severity}|${i.rule}|${i.entity}`} className="flex items-start gap-2 text-sm">
            <Badge variant={i.severity === 'error' ? 'destructive' : 'outline'}
              style={i.severity === 'warning' ? { backgroundColor: 'var(--warning)', color: 'var(--warning-foreground)' } : undefined}>
              {i.severity}
            </Badge>
            <span><span className="font-medium">{i.entity}</span> — {i.detail}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
