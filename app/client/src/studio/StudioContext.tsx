import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { Alert, AlertDescription, AlertTitle, Skeleton } from '@databricks/appkit-ui/react';
import type { ClientConfig } from '../../../server/studio/config';
import { studioApi, type Me } from './api';

interface Studio {
  config: ClientConfig;
  me: Me;
  /** Every query takes this as a parameter; bump() re-runs all mounted queries after a write. */
  refresh: number;
  bump: () => void;
}

const StudioCtx = createContext<Studio | null>(null);

export function useStudio(): Studio {
  const ctx = useContext(StudioCtx);
  if (!ctx) throw new Error('useStudio must be used inside <StudioProvider>');
  return ctx;
}

export function StudioProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ config: ClientConfig; me: Me } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const bump = useCallback(() => setRefresh((n) => n + 1), []);

  useEffect(() => {
    Promise.all([studioApi.config(), studioApi.whoami()])
      .then(([config, me]) => setState({ config, me }))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <Alert variant="destructive" className="m-6">
        <AlertTitle>Crop Plan Studio could not start</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!state) return <Skeleton className="m-6 h-40" />;
  return <StudioCtx.Provider value={{ ...state, refresh, bump }}>{children}</StudioCtx.Provider>;
}
