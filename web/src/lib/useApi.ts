"use client";

import useSWR, { type SWRConfiguration } from "swr";
import { apiGet, type ApiError } from "./api";

export interface UseApiOptions {
  /** Poll interval in ms (0 = no polling). */
  refreshInterval?: number;
  /** Extra SWR options if needed. */
  swr?: SWRConfiguration;
}

/**
 * SWR-backed GET. Pass `null` as path to skip fetching.
 * `error` stays set alongside stale `data` when a refresh fails — show both
 * (the old data plus an "update failed" marker), never just the old data.
 */
export function useApi<T>(path: string | null, opts: UseApiOptions = {}) {
  const { data, error, isLoading, isValidating, mutate } = useSWR<T, ApiError>(path, apiGet<T>, {
    refreshInterval: opts.refreshInterval ?? 0,
    revalidateOnFocus: false,
    shouldRetryOnError: true,
    errorRetryInterval: 10_000,
    ...opts.swr,
  });
  return { data, error, isLoading, isValidating, mutate };
}
