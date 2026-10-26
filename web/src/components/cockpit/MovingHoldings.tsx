"use client";
import Link from "next/link";
import { Button } from "@/components/Button";
import { Num } from "@/components/Num";
import { Panel } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import type { BriefHolding, PortfolioBrief } from "@/lib/api";
import { routes } from "@/lib/commands";
import { fmtNumber } from "@/lib/format";
import { portfolioGate, usePortfolio } from "./usePortfolio";

const MAX_ROWS = 4;

/** Threshold encoded in the brief's flag key, e.g. "day_move_over_3pct" -> 3. */
function bigMoveThreshold(b: PortfolioBrief): { key: string; pct: number } | null {
  for (const key of Object.keys(b.flags)) {
    const m = /^day_move_over_([\d.]+)pct$/.exec(key);
    if (m) return { key, pct: Number(m[1]) };
  }
  return null;
}

function note(h: BriefHolding, big: { pct: number } | null): string {
  const parts: string[] = [];
  if (big && Math.abs(h.day_change_pct ?? 0) >= big.pct) parts.push(`Moved more than ${big.pct}% today`);
  if (h.weight_of_portfolio_pct != null) parts.push(`${fmtNumber(h.weight_of_portfolio_pct, 1)}% of portfolio`);
  if (h.pnl_pct != null) parts.push(`${h.pnl_pct >= 0 ? "+" : "−"}${fmtNumber(Math.abs(h.pnl_pct), 1)}% unrealized`);
  return parts.join(" · ");
}

export function MovingHoldings() {
  const { status, brief, authed } = usePortfolio();
  const gate = portfolioGate(status.data);

  let body;
  if (status.isLoading) body = <StateView kind="loading" compact title="Checking the Avanza session" className="px-0" />;
  else if (status.error && !status.data) body = <StateView kind="error" compact error={status.error} onRetry={() => status.mutate()} />;
  else if (gate)
    body = (
      <StateView
        kind="info"
        compact
        className="px-0"
        title="Needs the portfolio session"
        message={`Day moves come from your Avanza holdings. ${gate.message}`}
      />
    );
  else if (authed && brief.isLoading) body = <StateView kind="loading" compact title="Reading your holdings" />;
  else if (brief.error && !brief.data) body = <StateView kind="error" compact error={brief.error} onRetry={() => brief.mutate()} />;
  else if (brief.data) {
    const big = bigMoveThreshold(brief.data);
    const rows = brief.data.holdings
      .filter((h) => h.day_change_pct != null && h.day_change_pct !== 0)
      .sort((a, b) => Math.abs(b.day_change_pct ?? 0) - Math.abs(a.day_change_pct ?? 0))
      .slice(0, MAX_ROWS);
    body = rows.length ? (
      <ul className="m-0 list-none p-0">
        {rows.map((h) => (
          <li key={`${h.account}-${h.name}`} className="flex h-9 items-center gap-3.5 border-t border-raised text-[13px]">
            <span className="num w-[132px] truncate font-semibold text-text" title={h.name}>
              {h.ticker ? (
                <Link href={routes.chart(h.ticker)} className="hover:text-amber">
                  {h.name}
                </Link>
              ) : (
                h.name
              )}
            </span>
            <Num kind="pct" decimals={1} colored value={h.day_change_pct} className="w-16 text-right" />
            <span className="truncate text-soft">{note(h, big)}</span>
          </li>
        ))}
      </ul>
    ) : (
      <StateView kind="empty" compact title="Quiet day" message="None of your holdings has moved today." />
    );
  } else body = <StateView kind="empty" compact title="No holdings data" />;

  return (
    <Panel aria-labelledby="moving-h" className="shrink-0 px-5 py-3.5">
      <div className="mb-1.5 flex items-baseline gap-2.5">
        <h2 id="moving-h" className="m-0 text-sm font-semibold text-text">
          Moving in your holdings
        </h2>
        <Button variant="text" size="sm" href={routes.news()} className="ml-auto">
          All news →
        </Button>
      </div>
      {body}
    </Panel>
  );
}
