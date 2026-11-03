import { useState } from 'react';
import { createBrowserRouter, Navigate, NavLink, Outlet, RouterProvider } from 'react-router';
import { Badge, Button } from '@databricks/appkit-ui/react';
import { PanelRightClose, PanelRightOpen } from 'lucide-react';
import { AssistantDock } from './assistant/AssistantDock';
import { InputsPage } from './pages/inputs/InputsPage';
import { ResultsPage } from './pages/results/ResultsPage';
import { RunsPage } from './pages/runs/RunsPage';
import { ScenariosPage } from './pages/scenarios/ScenariosPage';
import { StudioProvider, useStudio } from './studio/StudioContext';

const NAV = [
  { to: '/inputs', label: 'Inputs' },
  { to: '/runs', label: 'Runs' },
  { to: '/results', label: 'Results' },
  { to: '/scenarios', label: 'Scenarios' },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-2 text-sm font-medium ${isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`;

function Shell() {
  const { me } = useStudio();
  const [dockOpen, setDockOpen] = useState(true);
  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="flex items-center gap-3 border-b px-4 py-2">
        <h1 className="text-lg font-semibold text-foreground">Crop Plan Studio</h1>
        <span className="text-xs text-muted-foreground">2027 hybrid-to-field planning · synthetic data</span>
        <Badge variant="secondary" className="ml-auto">{me.email}</Badge>
        <Button variant="ghost" size="icon" aria-label={dockOpen ? 'Hide assistant' : 'Show assistant'} onClick={() => setDockOpen(!dockOpen)}>
          {dockOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
        </Button>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav className="w-44 shrink-0 space-y-1 border-r p-3" aria-label="Screens">
          {NAV.map((n) => <NavLink key={n.to} to={n.to} className={linkClass}>{n.label}</NavLink>)}
        </nav>
        <main className="min-w-0 flex-1 overflow-auto p-4"><Outlet /></main>
        {dockOpen && <aside className="w-[420px] shrink-0 border-l p-3" aria-label="Assistant"><AssistantDock /></aside>}
      </div>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <StudioProvider><Shell /></StudioProvider>,
    children: [
      { path: '/', element: <Navigate to="/inputs" replace /> },
      { path: '/inputs', element: <InputsPage /> },
      { path: '/runs', element: <RunsPage /> },
      { path: '/results', element: <ResultsPage /> },
      { path: '/results/:scenarioId', element: <ResultsPage /> },
      { path: '/scenarios', element: <ScenariosPage /> },
      { path: '*', element: <Navigate to="/inputs" replace /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
