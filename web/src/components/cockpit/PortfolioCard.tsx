"use client";
import { Button } from "@/components/Button";
import { Num } from "@/components/Num";
import { Panel } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import type { PortfolioBrief } from "@/lib/api";
import { fmtNumber, fmtPct, fmtSigned } from "@/lib/format";
import { portfolioGate, usePortfolio } from "./usePortfolio";

/** Week result: Avanza's own insights total when present, else the sum of per-account changes. */
function weekChange(b: PortfolioBrief): { sek: number; pct: number | null } | null {
  const w = b.performance["1w"];
  if (!w) return null;
  const sek =
    w.insights_total_sek ??
    (w.per_account.length ? w.per_account.reduce((acc, a) => acc + (a.change ?? 0), 0) : null);
  if (sek == null) return null;
  const total = b.totals_sek.portfolio;
  const start = total != null ? total - sek : null;
  return { sek, pct: start ? (sek / start) * 100 : null };
}

export function PortfolioCard() {
  const { status, brief, authed } = usePortfolio();
  const gate = portfolioGate(status.data);

  let body;
  if (status.isLoading) body = <StateView kind="loading" compact title="Checking the Avanza session" />;
  else if (status.error && !status.data)
    body = <StateView kind="error" compact error={status.error} onRetry={() => status.mutate()} />;
  else if (gate)
    body = (
      <StateView
        kind="info"
        compact
        mood="watching"
        className="w-full px-0"
        title={gate.title}
        message={gate.message}
        action={
          <Button variant="text" size="md" href="/terminal/portfolio" className="ml-auto shrink-0">
            Portfolio →
          </Button>
        }
      />
    );
  else if (authed && brief.isLoading) body = <StateView kind="loading" compact title="Reading your portfolio" />;
  else if (brief.error && !brief.data)
    body = <StateView kind="error" compact error={brief.error} onRetry={() => brief.mutate()} />;
  else if (brief.data) {
    const b = brief.data;
    const wk = weekChange(b);
    body = (
      <div className="flex w-full items-center gap-7">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-xs text-muted">Portfolio</span>
          <span className="whitespace-nowrap font-serif text-[46px] leading-none text-text">
            {fmtNumber(b.totals_sek.portfolio, 0)} <span className="text-[22px] text-muted">SEK</span>
          </span>
          {wk ? (
            <Num colored value={wk.sek} className="text-[13px]">
              {`${fmtSigned(wk.sek, 0)}${wk.pct != null ? ` (${fmtPct(wk.pct, 2)})` : ""} this week`}
            </Num>
          ) : (
            <span className="text-[13px] text-faint">Week change unavailable</span>
          )}
        </div>
        <div className="ml-auto flex flex-col gap-2 text-xs">
        <dl className="m-0 flex flex-col gap-2">
          <div className="flex justify-between gap-[18px]">
            <dt className="text-muted">Cash</dt>
            <dd className="num m-0">{b.totals_sek.cash_pct == null ? "—" : `${fmtNumber(b.totals_sek.cash_pct, 1)}%`}</dd>
          </div>
          <div className="flex justify-between gap-[18px]">
            <dt className="text-muted">Unrealized</dt>
            <dd className="m-0">
              <Num kind="pct" decimals={1} colored value={b.totals_sek.unrealized_pnl_pct} />
            </dd>
          </div>
          <div className="flex justify-between gap-[18px]">
            <dt className="text-muted">Earnings ≤{b.earnings.within_days}d</dt>
            <dd className="num m-0">{b.earnings.upcoming.length}</dd>
          </div>
        </dl>
          <Button variant="text" size="sm" href="/terminal/portfolio" className="justify-start text-xs">
            Open portfolio →
          </Button>
        </div>
      </div>
    );
  } else body = <StateView kind="empty" compact title="No portfolio data" />;

  return (
    <Panel aria-label="Portfolio summary" className="w-[520px] shrink-0 flex-row items-center px-[22px] py-[18px]">
      {body}
    </Panel>
  );
}
