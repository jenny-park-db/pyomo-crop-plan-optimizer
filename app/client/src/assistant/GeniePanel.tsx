import { useState } from 'react';
import {
  Alert, AlertDescription, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Empty, EmptyDescription,
  EmptyHeader, EmptyTitle, GenieChatMessage, Input, ScrollArea, useGenieChat,
} from '@databricks/appkit-ui/react';
import { useStudio } from '../studio/StudioContext';
import { isEmptyAnswer, lastSql, SAMPLE_QUESTIONS, statusLabel } from './genieModel';

/**
 * Embedded Genie Q&A over the "Crop Plan Results" space. Ships the five trust items: who is asking,
 * the generated SQL, live status, an AI-generated note on every answer, and a truthful OBO disclosure
 * (bundle/resources/app.yml sets user_api_scopes [sql, dashboards.genie]).
 */
export function GeniePanel() {
  const { me } = useStudio();
  const { messages, status, error, sendMessage, reset } = useGenieChat({ alias: 'default' });
  const [text, setText] = useState('');
  const sqlCard = lastSql(messages);
  const progress = statusLabel(status, messages);
  const busy = status === 'streaming';
  const ask = (q: string) => {
    if (!q.trim() || busy) return;
    sendMessage(q.trim());
    setText('');
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="secondary">{me.email}</Badge>
        <span className="text-muted-foreground">
          {me.obo_scopes.includes('dashboards.genie')
            ? 'Genie runs as you: answers only use data your Unity Catalog permissions allow.'
            : "Genie runs as the app's service principal."}
        </span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={reset} disabled={busy}>New conversation</Button>
      </div>
      <ScrollArea className="flex-1 min-h-0 pr-2">
        {messages.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>Ask about scenarios, runs, and margins</EmptyTitle>
              <EmptyDescription>Genie writes SQL over the Crop Plan Results tables and shows it with every answer.</EmptyDescription>
            </EmptyHeader>
            <div className="flex flex-col gap-2">
              {SAMPLE_QUESTIONS.map((q) => <Button key={q} variant="outline" size="sm" className="whitespace-normal h-auto text-left" onClick={() => ask(q)}>{q}</Button>)}
            </div>
          </Empty>
        ) : (
          <div className="space-y-3">
            {messages.map((m) => (
              <div key={m.id} className="space-y-1">
                <GenieChatMessage message={m} />
                {m.role === 'assistant' && m.status === 'COMPLETED' && (
                  <p className="text-xs text-muted-foreground">
                    {isEmptyAnswer(m) ? 'Genie returned no answer for this question — try rephrasing it. ' : ''}
                    AI-generated from your data via Genie — check the generated SQL before relying on the numbers.
                  </p>
                )}
                {m.error && <p className="text-xs text-destructive">{m.error}</p>}
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
      {progress && <p className="text-sm text-muted-foreground" aria-live="polite">{progress}</p>}
      {status === 'error' && (
        <Alert variant="destructive"><AlertDescription>{error ?? 'Genie failed. Rephrase the question or try again.'}</AlertDescription></Alert>
      )}
      {sqlCard && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Generated SQL</CardTitle>
            <CardDescription className="text-xs">{sqlCard.description ?? sqlCard.title}</CardDescription>
          </CardHeader>
          <CardContent><pre className="max-h-48 overflow-auto text-xs whitespace-pre-wrap">{sqlCard.query}</pre></CardContent>
        </Card>
      )}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <Input aria-label="Ask Genie" placeholder="Ask a question about the results…" value={text} onChange={(e) => setText(e.target.value)} disabled={busy} />
        <Button type="submit" disabled={busy || !text.trim()}>Ask</Button>
      </form>
    </div>
  );
}
