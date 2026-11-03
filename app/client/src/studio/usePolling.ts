import { useEffect, useRef } from 'react';

/** Call `tick` every `ms` while `active` is true (and once right away when it turns true). */
export function usePolling(active: boolean, tick: () => Promise<void> | void, ms = 5000): void {
  const fn = useRef(tick);
  useEffect(() => {
    fn.current = tick;
  }, [tick]);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    const run = async () => {
      if (stopped) return;
      try {
        await fn.current();
      } finally {
        if (!stopped) timer = setTimeout(() => void run(), ms);
      }
    };
    let timer = setTimeout(() => void run(), 0);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [active, ms]);
}
