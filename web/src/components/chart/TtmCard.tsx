"use client";
import { Kes } from "@/components/Kes";
import { Panel, StatTile } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import type { SetupRow } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtFracPct, fmtLev, fmtNumber, fmtPrice } from "@/lib/format";
import { historyLine, kesNote, relevantHist, shortDate, stateDetail, stateHeadline, winWord } from "./ttm";

export function TtmCard({
  row,
  inUniverse,
  loading,
  error,
  onRetry,
  symbol,
}: {
  row: SetupRow | null;
  inUniverse: boolean;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  symbol: string;
}) {
  const title = (
    <h2 id="ttm-h" className="num m-0 text-[11px] tracking-[1px] text-amber">
      TTM POWER RANGE · {row?.bar_date ? shortDate(row.bar_date).toUpperCase() : "TODAY"}
    </h2>
  );

  if (!row) {
    return (
      <Panel aria-labelledby="ttm-h" className="gap-2 px-[18px] py-4">
        {title}
        {loading ? (
          <StateView kind="loading" compact title="Classifying against today's zones" className="px-0" />
        ) : error ? (
          <StateView kind="error" compact error={error} onRetry={onRetry} className="px-0" />
        ) : (
          <StateView kind="empty" compact title="No zone data" message={`${symbol} is not in the setups universe and no zones could be computed for it.`} className="px-0" />
        )}
      </Panel>
    );
  }

  const h = relevantHist(row);
  const avg = h.avg_fwd_ret;
  return (
    <Panel aria-labelledby="ttm-h" className="gap-2 px-[18px] py-4">
      {title}
      {!inUniverse ? (
        <p className="m-0 rounded-lg bg-raised px-2.5 py-1.5 text-[11px] leading-snug text-soft">
          {row.symbol} is not in the 16-name setups universe. Computed ad hoc for this chart; it never appears on the cockpit.
        </p>
      ) : null}
      <span className="text-base font-semibold text-text">{stateHeadline(row)}</span>
      <span className="text-[13px] leading-snug text-soft">{stateDetail(row)}</span>
      <div className="mt-1 grid grid-cols-3 gap-2">
        <StatTile label="WIN 3D">
          <span title={`Share of past crosses that ${winWord(row)} three days later`}>{fmtFracPct(h.win_rate)}</span>
        </StatTile>
        <StatTile label="AVG 3D">
          <span className={cx(avg != null && avg > 0 && "text-up", avg != null && avg < 0 && "text-down")}>{fmtFracPct(avg, 1, true)}</span>
        </StatTile>
        <StatTile label="SAMPLE">n={h.n}</StatTile>
      </div>
      <span className="num text-xs text-muted">
        ATR14 {fmtPrice(row.atr14)} ({fmtNumber(row.atr_pct, 2)}%) · lev cap {fmtLev(row.lev_cap)}
      </span>
      <span className="sr-only">{historyLine(row)}</span>
      <div className="mt-1 flex gap-2.5 rounded-control bg-bubble px-3 py-2.5">
        <Kes mood={row.earnings_days != null && row.earnings_days <= 7 ? "cautious" : "watching"} size={30} perch="none" className="shrink-0" />
        <span className="text-xs leading-[1.45] text-[#D5DBE2]">{kesNote(row)}</span>
      </div>
    </Panel>
  );
}
