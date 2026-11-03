import type { ReactNode } from 'react';
import {
  Alert, AlertDescription, AlertTitle, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Skeleton,
} from '@databricks/appkit-ui/react';

interface Props {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  emptyAction?: ReactNode;
  /** Shown while the SQL warehouse starts (AppKit streams its state before running the query). */
  warehouseState?: string | null;
  skeletonClassName?: string;
  children: ReactNode;
}

/** The loading / empty / error states every data view must have (spec §6). */
export function QueryState({
  loading, error, empty, emptyTitle = 'Nothing here yet', emptyDescription, emptyAction, warehouseState,
  skeletonClassName = 'h-32 w-full', children,
}: Props) {
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn’t load this data</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (loading) {
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className={skeletonClassName} />
        {warehouseState && warehouseState !== 'RUNNING' && (
          <p className="text-xs text-muted-foreground">SQL warehouse is {warehouseState.toLowerCase()}…</p>
        )}
      </div>
    );
  }
  if (empty) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>{emptyTitle}</EmptyTitle>
          {emptyDescription && <EmptyDescription>{emptyDescription}</EmptyDescription>}
        </EmptyHeader>
        {emptyAction && <EmptyContent>{emptyAction}</EmptyContent>}
      </Empty>
    );
  }
  return <>{children}</>;
}
