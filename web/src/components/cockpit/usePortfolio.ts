"use client";
/**
 * Portfolio data for the cockpit, gated on the session status so the cockpit
 * never starts an Avanza login: the brief is only requested once
 * /api/portfolio/status says a session is already authenticated (every other
 * portfolio endpoint logs in lazily, and logins are throttled).
 */
import type { PortfolioBrief, PortfolioStatus } from "@/lib/api";
import { paths } from "@/lib/api";
import { fmtClock } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export function usePortfolio() {
  const status = useApi<PortfolioStatus>(paths.portfolioStatus(), { refreshInterval: 60_000 });
  const authed = status.data?.authenticated === true;
  const brief = useApi<PortfolioBrief>(authed ? paths.brief() : null, {
    refreshInterval: 120_000,
    // No auto-retry: a failed portfolio call may mean the session dropped, and a
    // retry is then a login attempt. The 60 s status poll decides when to resume.
    swr: { shouldRetryOnError: false },
  });
  return { status, brief, authed };
}

/** Why there is no portfolio data, in one sentence, or null when there should be. */
export function portfolioGate(s: PortfolioStatus | undefined): { title: string; message: string } | null {
  if (!s || s.authenticated) return null;
  if (!s.configured)
    return {
      title: "Portfolio not connected",
      message: "Avanza isn't configured on this backend, so there are no holdings to show.",
    };
  if (s.login_blocked_until)
    return {
      title: "Avanza paused",
      message: `Paused after a failed login, next attempt ${fmtClock(s.login_blocked_until)}.${
        s.last_login_failure ? ` Reason: ${s.last_login_failure}` : ""
      }`,
    };
  return {
    title: "No Avanza session",
    message: "Open Portfolio to sign in. The cockpit never starts a login on its own.",
  };
}
