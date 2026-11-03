import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test, vi } from 'vitest';

// The appkit-ui barrel pulls in chart code that doesn't load under Node; the real Tabs come from its tabs module.
vi.mock('@databricks/appkit-ui/react', () => import('../../../node_modules/@databricks/appkit-ui/dist/react/ui/tabs.js'));
vi.mock('./AgentPanel', () => ({ AgentPanel: () => <p>agent-panel-mounted</p> }));
vi.mock('./GeniePanel', () => ({ GeniePanel: () => <p>genie-panel-mounted</p> }));

const { AssistantDock } = await import('./AssistantDock');

test('both assistant tabs stay mounted, so switching tabs keeps a running conversation', () => {
  const html = renderToStaticMarkup(<AssistantDock />);
  expect(html).toContain('genie-panel-mounted');
  expect(html).toContain('agent-panel-mounted');
});
