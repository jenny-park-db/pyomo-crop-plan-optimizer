import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import {
  Alert, AlertDescription, Badge, Button, Card, CardContent, Collapsible, CollapsibleContent,
  CollapsibleTrigger, Empty, EmptyDescription, EmptyHeader, EmptyTitle, Input, ScrollArea, Spinner,
} from '@databricks/appkit-ui/react';
import type { TurnState } from '../../../server/studio/agentProxy';
import { ApiError, studioApi } from '../studio/api';
import { useStudio } from '../studio/StudioContext';
import { AGENT_SAMPLES, elapsedSeconds, knownScenarios, linkScenarios, nextPollStep, toolCards, turnReply, type CardState, type ToolCard } from './agentModel';

const POLL_MS = 2000;
const nowMs = () => Date.now();

interface Turn {
  question: string;
  state: TurnState | null;
  error: string | null;
  startedAt: number;
}

const STATE_BADGE: Record<CardState, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  done: 'secondary', running: 'outline', pending: 'outline', rejected: 'destructive', error: 'destructive',
};

function ToolCardView({ card }: { card: ToolCard }) {
  return (
    <Collapsible className="rounded-md border p-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-medium">{card.label}</span>
        <Badge variant={STATE_BADGE[card.state]}>{card.state}</Badge>
        {card.scenarioId && <Link className="underline" to={`/results/${card.scenarioId}`}>Results for {card.scenarioId}</Link>}
        <CollapsibleTrigger asChild><Button size="sm" variant="ghost" className="ml-auto h-6">Details</Button></CollapsibleTrigger>
      </div>
      {card.detail && <p className="mt-1 text-muted-foreground">{card.detail}</p>}
      {card.assumptions && <p className="mt-1">Assumption: {card.assumptions}</p>}
      {card.sql && (
        <div className="mt-2">
          <p className="text-muted-foreground">{card.sqlTitle ?? 'Generated SQL'}{card.link && <> · <a className="underline" href={card.link} target="_blank" rel="noreferrer">open in Genie</a></>}</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{card.sql}</pre>
        </div>
      )}
      <CollapsibleContent>
        <p className="mt-2 text-muted-foreground">Arguments</p>
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{JSON.stringify(card.args, null, 2)}</pre>
        <p className="mt-2 text-muted-foreground">Result</p>
        <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{JSON.stringify(card.result, null, 2)}</pre>
      </CollapsibleContent>
    </Collapsible>
  );
}

function TurnView({ turn, now }: { turn: Turn; now: number }) {
  const messages = turn.state?.messages ?? [];
  const cards = toolCards(messages);
  const reply = turnReply(messages);
  const busy = !turn.error && (!turn.state || turn.state.status === 'queued' || turn.state.status === 'active');
  return (
    <div className="space-y-2">
      <p className="ml-8 rounded-md bg-muted p-2 text-sm">{turn.question}</p>
      {busy && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          <Spinner className="size-4" /> Working… {elapsedSeconds(now, turn.startedAt)} s (a what-if waits for the solver, up to 4 minutes)
        </p>
      )}
      {cards.map((c) => <ToolCardView key={c.id} card={c} />)}
      {reply && (
        <Card>
          <CardContent className="whitespace-pre-wrap pt-4 text-sm">
            {linkScenarios(reply, knownScenarios(cards)).map((part, i) => part.scenarioId
              ? <Link key={i} className="underline" to={`/results/${part.scenarioId}`}>{part.text}</Link>
              : <span key={i}>{part.text}</span>)}
          </CardContent>
        </Card>
      )}
      {reply && <p className="text-xs text-muted-foreground">AI-generated. Numbers come from the solver and Genie results shown above — check them before relying on them.</p>}
      {(turn.error || turn.state?.status === 'failed') && (
        <Alert variant="destructive"><AlertDescription>{turn.error ?? turn.state?.error ?? 'The agent failed on this turn.'}</AlertDescription></Alert>
      )}
    </div>
  );
}

/** The Agent tab (spec §6.5): chat with the planning agent through the app's proxy, as the signed-in user. */
export function AgentPanel() {
  const { config, me, bump } = useStudio();
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState('');
  const [now, setNow] = useState(nowMs);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const busy = turns.some((t) => !t.error && (!t.state || t.state.status === 'queued' || t.state.status === 'active'));

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (!busy) return;
    const tick = setInterval(() => setNow(nowMs()), 1000);
    return () => clearInterval(tick);
  }, [busy]);

  const update = (index: number, patch: Partial<Turn>) =>
    setTurns((all) => all.map((t, i) => (i === index ? { ...t, ...patch } : t)));

  const poll = (index: number, id: string, startedAt: number, failures = 0) => {
    timer.current = setTimeout(() => void (async () => {
      let outcome: Parameters<typeof nextPollStep>[0];
      try {
        const state = await studioApi.agentPoll(id);
        update(index, { state });
        outcome = { state };
      } catch (error) {
        outcome = { error };
      }
      const step = nextPollStep(outcome, failures, startedAt, nowMs());
      if (step.kind === 'again') poll(index, id, startedAt, step.failures);
      else if (step.kind === 'done' && step.bump) bump(); // Runs/Scenarios show the new scenario
      else if (step.kind === 'error') update(index, { error: step.message });
    })(), POLL_MS * (failures + 1));
  };

  const ask = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    const index = turns.length;
    const startedAt = nowMs();
    setTurns((all) => [...all, { question, state: null, error: null, startedAt }]);
    setText('');
    try {
      const started = await studioApi.agentStart(sessionId, question);
      poll(index, started.id, startedAt);
    } catch (e) {
      update(index, { error: e instanceof ApiError || e instanceof Error ? e.message : String(e) });
    }
  };

  const reset = () => {
    if (timer.current) clearTimeout(timer.current);
    setTurns([]);
    setSessionId(crypto.randomUUID());
  };

  if (!config.agentUrl) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>The planning agent is not deployed yet</EmptyTitle>
          <EmptyDescription>Run scripts/deploy_agent.py to deploy it; meanwhile use Ask data for questions about stored results.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="secondary">{me.email}</Badge>
        <span className="text-muted-foreground">The agent acts as you: scenarios and stress tests it starts are recorded under your email.</span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={reset} disabled={busy}>New conversation</Button>
      </div>
      <ScrollArea className="flex-1 min-h-0 pr-2">
        {turns.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>Ask for a what-if, a data question, or a robustness check</EmptyTitle>
              <EmptyDescription>What-ifs run the solver as a new scenario; data questions go to Genie and show its SQL.</EmptyDescription>
            </EmptyHeader>
            <div className="flex flex-col gap-2">
              {AGENT_SAMPLES.map((q) => <Button key={q} variant="outline" size="sm" className="h-auto whitespace-normal text-left" onClick={() => void ask(q)}>{q}</Button>)}
            </div>
          </Empty>
        ) : (
          <div className="space-y-4">{turns.map((t) => <TurnView key={t.startedAt} turn={t} now={now} />)}</div>
        )}
      </ScrollArea>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(text); }}>
        <Input aria-label="Ask the planning agent" placeholder="What if…" value={text} onChange={(e) => setText(e.target.value)} disabled={busy} />
        <Button type="submit" disabled={busy || !text.trim()}>Send</Button>
      </form>
    </div>
  );
}
