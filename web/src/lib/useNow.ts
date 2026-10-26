"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Current time in ms, ticking every `intervalMs`. Returns null during SSR and
 * the hydration pass, so time-dependent text never causes a hydration mismatch.
 */
export function useNow(intervalMs = 1000): number | null {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const id = setInterval(onChange, Math.min(intervalMs, 1000));
      return () => clearInterval(id);
    },
    [intervalMs],
  );
  return useSyncExternalStore(
    subscribe,
    () => Math.floor(Date.now() / intervalMs) * intervalMs,
    () => null,
  );
}
