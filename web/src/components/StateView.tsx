/**
 * The one way every page shows loading, empty and failure states, voiced by Kes.
 *
 *   <StateView kind="loading" title="Reading today's setups" />
 *   <StateView kind="empty" title="No setups near a zone" message="..." />
 *   <StateView kind="error" error={error} onRetry={() => mutate()} />
 *
 * kind "error" accepts an ApiError (or any Error) and turns it into a clear
 * message: unreachable backend vs. the backend's own error text. Default moods:
 * loading → thinking, empty → watching, error → alert. `compact` lays out in a
 * single row for use inside small panels. `action` replaces the retry button.
 */
import type { ReactNode } from "react";
import { ApiError, BACKEND_LABEL, type KesMood } from "@/lib/api";
import { cx } from "@/lib/cx";
import { Button } from "./Button";
import { Kes } from "./Kes";

export type StateKind = "loading" | "empty" | "error" | "info";

const defaultMood: Record<StateKind, KesMood> = {
  loading: "thinking",
  empty: "watching",
  error: "alert",
  info: "watching",
};

export function describeError(error: unknown): { title: string; message: string } {
  if (error instanceof ApiError) {
    if (error.unreachable)
      return {
        title: "Backend not reachable",
        message: `No answer from the Range backend at ${BACKEND_LABEL}. Either it is down (start it with python3.13 -m terminal.app) or the request timed out. I won't show numbers I can't check.`,
      };
    if (error.status === 503) return { title: "Source unavailable", message: error.message };
    if (error.status === 404) return { title: "Not found", message: error.message };
    return { title: `Request failed (${error.status})`, message: error.message };
  }
  if (error instanceof Error) return { title: "Something went wrong", message: error.message };
  return { title: "Something went wrong", message: String(error) };
}

export function StateView({
  kind,
  title,
  message,
  error,
  mood,
  onRetry,
  action,
  compact = false,
  className,
}: {
  kind: StateKind;
  title?: ReactNode;
  message?: ReactNode;
  error?: unknown;
  mood?: KesMood;
  onRetry?: () => void;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  const described = kind === "error" && error !== undefined ? describeError(error) : null;
  const heading = title ?? described?.title ?? (kind === "loading" ? "Loading" : kind === "empty" ? "Nothing here yet" : kind === "error" ? "Something went wrong" : "");
  const body = message ?? described?.message;
  const m = mood ?? defaultMood[kind];

  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      aria-busy={kind === "loading" || undefined}
      className={cx(
        "flex",
        compact ? "items-center gap-3 px-4 py-3 text-left" : "flex-col items-center justify-center gap-3 px-6 py-10 text-center",
        className,
      )}
    >
      <Kes mood={m} size={compact ? 36 : 72} perch={compact ? "none" : "bar"} />
      <div className={cx("flex flex-col gap-1", compact ? "min-w-0" : "max-w-[440px] items-center")}>
        <span className={cx("font-semibold", compact ? "text-[13px]" : "text-[15px]", kind === "error" ? "text-warn-text" : "text-text")}>
          {heading}
        </span>
        {body ? <span className={cx("leading-[1.5] text-muted", compact ? "text-xs" : "text-[13px]")}>{body}</span> : null}
      </div>
      {action ??
        (onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry} className={compact ? "ml-auto" : "mt-1"}>
            Try again
          </Button>
        ) : null)}
    </div>
  );
}
