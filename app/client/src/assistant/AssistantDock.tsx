import { Tabs, TabsContent, TabsList, TabsTrigger } from '@databricks/appkit-ui/react';
import { AgentPanel } from './AgentPanel';
import { GeniePanel } from './GeniePanel';

/** Right-docked Assistant (spec §6): Ask data (Genie) and the planning agent. */
export function AssistantDock() {
  return (
    <Tabs defaultValue="genie" className="flex h-full flex-col">
      <TabsList>
        <TabsTrigger value="genie">Ask data (Genie)</TabsTrigger>
        <TabsTrigger value="agent">Agent</TabsTrigger>
      </TabsList>
      {/* forceMount: switching tabs must not drop a conversation that is still waiting on Genie or a solve. */}
      <TabsContent value="genie" forceMount className="flex-1 min-h-0 data-[state=inactive]:hidden"><GeniePanel /></TabsContent>
      <TabsContent value="agent" forceMount className="flex-1 min-h-0 data-[state=inactive]:hidden"><AgentPanel /></TabsContent>
    </Tabs>
  );
}
