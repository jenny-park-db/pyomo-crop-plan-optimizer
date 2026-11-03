import { Badge, Spinner } from '@databricks/appkit-ui/react';
import { statusTone } from '../pages/runs/runsModel';

const TONE_STYLE: Record<string, React.CSSProperties> = {
  good: { color: 'var(--success)', borderColor: 'var(--success)' },
  warn: { color: 'var(--warning-foreground)', backgroundColor: 'var(--warning)' },
};

export function StatusChip({ status }: { status: string }) {
  const tone = statusTone(status);
  if (tone === 'active') {
    return (
      <Badge variant="outline" className="gap-1">
        <Spinner className="size-3" />
        {status}
      </Badge>
    );
  }
  if (tone === 'bad') return <Badge variant="destructive">{status}</Badge>;
  return <Badge variant="outline" style={TONE_STYLE[tone]}>{status}</Badge>;
}
