"use client";
/** Holdings across all accounts, largest first. Weight is of total portfolio value (SEK). */
import type { ApiError, Position, PositionsResponse } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtClock, fmtNumber, fmtPct, fmtSEK, signOf } from "@/lib/format";
import { DataCell, DataHeader, DataRow, DataTable } from "../DataTable";
import { StateView } from "../StateView";
import { humanType } from "./util";

const COLS = "2.3fr 0.55fr 1.5fr 1fr 1.05fr 0.75fr";

const tone = (v: number | null | undefined) => {
  const s = signOf(v);
  return s > 0 ? "text-up" : s < 0 ? "text-down" : "text-muted";
};

function latestPriceTime(rows: Position[]): string | null {
  let best: number | null = null;
  for (const p of rows) {
    const t = p.last_price_updated ? Date.parse(p.last_price_updated) : NaN;
    if (!Number.isNaN(t) && (best === null || t > best)) best = t;
  }
  return best === null ? null : new Date(best).toISOString();
}

export function HoldingsTable({
  data,
  error,
  totalValue,
  onRetry,
}: {
  data: PositionsResponse | undefined;
  error: ApiError | undefined;
  totalValue: number | null | undefined;
  onRetry: () => void;
}) {
  const rows = data ? [...data.positions].sort((a, b) => (b.market_value_sek ?? -1) - (a.market_value_sek ?? -1)) : [];
  const accounts = [...new Set(rows.map((p) => p.account))];
  const maxW = Math.max(
    25,
    ...rows.map((p) => (totalValue && p.market_value_sek != null ? (p.market_value_sek / totalValue) * 100 : 0)),
  );
  const priced = latestPriceTime(rows);

  return (
    <section aria-labelledby="hold-h" className="flex min-h-0 flex-col overflow-hidden rounded-[16px] border border-line bg-surface">
      <div className="flex items-baseline gap-2.5 px-5 pb-2.5 pt-4">
        <h2 id="hold-h" className="m-0 text-base font-semibold text-text">
          Holdings
        </h2>
        {data ? (
          <span className="num text-xs text-muted">
            {rows.length} position{rows.length === 1 ? "" : "s"}
            {accounts.length ? ` · ${accounts.join(" · ")}` : ""}
          </span>
        ) : null}
        <span className="num ml-auto text-[11px] text-faint">
          {error && data ? (
            <span className="text-down-soft">UPDATE FAILED · SHOWING EARLIER DATA</span>
          ) : priced ? (
            `LATEST PRICE ${fmtClock(priced)} · REFRESH 60S`
          ) : null}
        </span>
      </div>

      {!data ? (
        error ? (
          <StateView kind="error" error={error} onRetry={onRetry} />
        ) : (
          <StateView kind="loading" title="Reading your holdings" />
        )
      ) : rows.length === 0 ? (
        <StateView kind="empty" title="No holdings" message="Avanza reports no positions in these accounts. Cash is shown in the total above." />
      ) : (
        <DataTable label="Holdings">
          <DataHeader
            cols={COLS}
            columns={[
              { label: "NAME" },
              { label: "CCY" },
              { label: "WEIGHT" },
              { label: "VALUE SEK", align: "right" },
              { label: "P&L", align: "right" },
              { label: "TODAY", align: "right" },
            ]}
          />
          {rows.map((p, i) => {
            const w = totalValue && p.market_value_sek != null ? (p.market_value_sek / totalValue) * 100 : null;
            return (
              <DataRow key={`${p.account}-${p.isin ?? p.name}-${i}`} cols={COLS} height={46}>
                <DataCell className="flex flex-col">
                  <span className="truncate text-text" title={p.name}>
                    {p.name}
                  </span>
                  <span className="num text-[10px] tracking-[0.6px] text-faint">
                    {humanType(p.instrument_type).toUpperCase()} · {p.account}
                    {p.yahoo_ticker ? ` · ${p.yahoo_ticker}` : ""}
                  </span>
                </DataCell>
                <DataCell mono className="text-muted">
                  {p.currency ?? "—"}
                </DataCell>
                <DataCell className="flex items-center gap-2.5">
                  <span aria-hidden="true" className="h-1.5 w-[110px] shrink-0 overflow-hidden rounded-[3px] bg-raised">
                    <span className="block h-1.5 bg-amber" style={{ width: `${w == null ? 0 : Math.min(100, (w / maxW) * 100)}%` }} />
                  </span>
                  <span className="num text-xs text-soft">{w == null ? "—" : `${fmtNumber(w, 1)}%`}</span>
                </DataCell>
                <DataCell align="right" mono>
                  {fmtSEK(p.market_value_sek, { unit: false })}
                </DataCell>
                <DataCell align="right" className="flex flex-col items-end">
                  <span className={cx("num", tone(p.pnl_pct))}>{fmtPct(p.pnl_pct, 1)}</span>
                  <span className={cx("num text-[11px] opacity-80", tone(p.pnl_sek))}>
                    {fmtSEK(p.pnl_sek, { signed: true, unit: false })}
                  </span>
                </DataCell>
                <DataCell align="right" mono className={tone(p.day_change_pct)}>
                  {fmtPct(p.day_change_pct, 1)}
                </DataCell>
              </DataRow>
            );
          })}
          {data.non_sek_positions_not_in_totals.length ? (
            <p className="m-0 border-t border-raised px-5 py-2.5 text-[11px] text-faint">
              Not valued in SEK, so no weight: {data.non_sek_positions_not_in_totals.join(", ")}.
            </p>
          ) : null}
        </DataTable>
      )}
    </section>
  );
}
