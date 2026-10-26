"use client";
/**
 * Portfolio page body. Read-only: Range cannot place trades, and nothing here
 * links to an order screen.
 *
 * Login safety: /api/portfolio/status never logs in, every other portfolio
 * endpoint logs in lazily. So nothing but status is requested until Avanza is
 * configured, not in a login cool-down, and either already signed in or the
 * user has explicitly asked to sign in. Polling is 60 s at most (the backend
 * caches Avanza for 60 s anyway); the brief is fetched on open and on request.
 */
import { useState, type ReactNode } from "react";
import type {
  PerformancePeriod,
  PerformanceResponse,
  PortfolioBrief,
  PortfolioStatus,
  PortfolioSummary,
  PositionsResponse,
  TransactionsResponse,
} from "@/lib/api";
import { paths } from "@/lib/api";
import { fmtClock } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useNow } from "@/lib/useNow";
import { Button } from "../Button";
import { StateView } from "../StateView";
import { AllocationPanel } from "./AllocationPanel";
import { BriefCard } from "./BriefCard";
import { HoldingsTable } from "./HoldingsTable";
import { RecentActivity } from "./RecentActivity";
import { ValueHero } from "./ValueHero";

const POLL = 60_000;
/** Never auto-retry a failed portfolio call: each retry can be another Avanza login attempt. */
const NO_RETRY = { shouldRetryOnError: false } as const;

function FullPage({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col gap-4 px-6 py-5">
      <div className="flex flex-1 items-center justify-center rounded-[16px] border border-line bg-surface">{children}</div>
      <Footer />
    </div>
  );
}

function Footer() {
  return <p className="m-0 text-center text-[11px] text-faint">View only — Range cannot place trades.</p>;
}

function Body({ onStatusChanged }: { onStatusChanged: () => void }) {
  const [period, setPeriod] = useState<PerformancePeriod>("1w");
  const summary = useApi<PortfolioSummary>(paths.portfolioSummary(), {
    refreshInterval: POLL,
    swr: { ...NO_RETRY, onError: onStatusChanged },
  });
  const ready = !!summary.data;
  // Everything else waits for the first successful summary: one login at most, then shared session.
  const positions = useApi<PositionsResponse>(ready ? paths.positions() : null, { refreshInterval: POLL, swr: NO_RETRY });
  const perf = useApi<PerformanceResponse>(ready ? paths.performance(period) : null, { refreshInterval: POLL, swr: NO_RETRY });
  const brief = useApi<PortfolioBrief>(ready ? paths.brief(30) : null, {
    swr: { ...NO_RETRY, revalidateIfStale: false, revalidateOnReconnect: false },
  });
  const tx = useApi<TransactionsResponse>(ready ? paths.transactions() : null, { swr: { ...NO_RETRY, revalidateIfStale: false } });

  if (!summary.data) {
    if (summary.error)
      return (
        <FullPage>
          <StateView
            kind="error"
            error={summary.error}
            title={summary.error.status === 503 ? "Avanza unavailable" : undefined}
            onRetry={() => {
              onStatusChanged();
              void summary.mutate();
            }}
          />
        </FullPage>
      );
    return (
      <FullPage>
        <StateView kind="loading" title="Reading your accounts" message="Read-only, via Avanza." />
      </FullPage>
    );
  }

  return (
    <div className="flex flex-col gap-4 px-6 py-5">
      <div className="flex gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <ValueHero
            summary={summary.data}
            perf={perf.data}
            perfError={perf.error}
            period={period}
            onPeriod={setPeriod}
            onRetryPerf={() => void perf.mutate()}
          />
          <HoldingsTable
            data={positions.data}
            error={positions.error}
            totalValue={summary.data.totals_sek.total_value}
            onRetry={() => void positions.mutate()}
          />
        </div>
        <aside aria-label="Allocation, brief and recent activity" className="flex w-[380px] shrink-0 flex-col gap-4">
          <AllocationPanel brief={brief.data} error={brief.error} onRetry={() => void brief.mutate()} />
          <BriefCard brief={brief.data} error={brief.error} validating={brief.isValidating} onRefresh={() => void brief.mutate()} />
          <RecentActivity data={tx.data} error={tx.error} onRetry={() => void tx.mutate()} />
        </aside>
      </div>
      <Footer />
    </div>
  );
}

export function PortfolioView() {
  const status = useApi<PortfolioStatus>(paths.portfolioStatus(), { refreshInterval: POLL });
  const [connect, setConnect] = useState(false);
  const now = useNow(15_000);

  if (!status.data) {
    return (
      <FullPage>
        {status.error ? (
          <StateView kind="error" error={status.error} onRetry={() => void status.mutate()} />
        ) : (
          <StateView kind="loading" title="Checking the Avanza connection" />
        )}
      </FullPage>
    );
  }

  const s = status.data;
  if (!s.configured)
    return (
      <FullPage>
        <StateView
          kind="info"
          mood="watching"
          title="Avanza isn't connected"
          message="Set AVANZA_USERNAME, AVANZA_PASSWORD and AVANZA_TOTP_SECRET in .env and restart the backend. The portfolio is read-only: Range can show holdings but never place trades."
        />
      </FullPage>
    );

  const blockedUntil = s.login_blocked_until ? Date.parse(s.login_blocked_until) : NaN;
  const blocked = !Number.isNaN(blockedUntil) && (now === null || blockedUntil > now);
  if (blocked && !s.authenticated)
    return (
      <FullPage>
        <StateView
          kind="error"
          mood="cautious"
          title={`Avanza paused after a failed login — next attempt at ${fmtClock(s.login_blocked_until)}`}
          message={
            <>
              {s.last_login_failure ? <>Last failure: {s.last_login_failure}. </> : null}
              Range waits out Avanza&apos;s cool-down instead of retrying, because repeated logins get the account throttled for the day.
            </>
          }
          action={
            <Button variant="outline" size="sm" className="mt-1" onClick={() => void status.mutate()}>
              Check status again
            </Button>
          }
        />
      </FullPage>
    );

  if (!s.authenticated && !connect)
    return (
      <FullPage>
        <StateView
          kind="info"
          mood="watching"
          title="Not signed in to Avanza"
          message={
            <>
              Loading the portfolio signs in once with your saved credentials. Avanza throttles logins (about 15 a day), so
              this only happens when you ask.
              {s.last_login_failure ? <> Last failure: {s.last_login_failure}.</> : null}
            </>
          }
          action={
            <Button variant="amber" size="md" className="mt-1" onClick={() => setConnect(true)}>
              Sign in and load portfolio
            </Button>
          }
        />
      </FullPage>
    );

  // A failed load drops back to the explicit "Sign in" step: without this, the
  // 60 s summary poll re-attempts a login every time a short cool-down (60 s
  // after a TOTP failure) expires, for as long as the page stays open.
  return (
    <Body
      onStatusChanged={() => {
        setConnect(false);
        void status.mutate();
      }}
    />
  );
}
