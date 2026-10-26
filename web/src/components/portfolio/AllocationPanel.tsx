"use client";
/**
 * Allocation from the brief: instrument types (rescaled from % of invested to
 * % of the whole portfolio so cash fits on the same bar) and currency exposure
 * (% of invested, by the currency each holding is priced in).
 */
import type { ApiError, PortfolioBrief } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { StateView } from "../StateView";
import { CASH_COLOR, humanType, typeColor } from "./util";

export function AllocationPanel({
  brief,
  error,
  onRetry,
}: {
  brief: PortfolioBrief | undefined;
  error: ApiError | undefined;
  onRetry: () => void;
}) {
  let body;
  if (!brief) {
    body = error ? (
      <StateView kind="error" error={error} onRetry={onRetry} compact />
    ) : (
      <StateView kind="loading" title="Working out your allocation" compact />
    );
  } else {
    const { invested, portfolio, cash } = brief.totals_sek;
    const scale = invested != null && portfolio ? invested / portfolio : null;
    const types = Object.entries(brief.concentration.by_instrument_type_pct)
      .filter(([, v]) => v != null)
      .map(([k, v], i) => ({ key: k, label: humanType(k), pct: scale == null ? null : (v as number) * scale, color: typeColor(k, i) }));
    const cashPct = brief.totals_sek.cash_pct ?? (cash != null && portfolio ? (cash / portfolio) * 100 : null);
    const segs = [...types, ...(cashPct != null ? [{ key: "CASH", label: "Cash", pct: cashPct, color: CASH_COLOR }] : [])].filter(
      (s) => s.pct != null && s.pct > 0,
    );
    const ccy = Object.entries(brief.concentration.by_currency_pct).filter(([, v]) => v != null) as [string, number][];

    body = (
      <>
        <span className="text-xs text-muted">By type · % of portfolio</span>
        {segs.length ? (
          <>
            <div
              role="img"
              aria-label={segs.map((s) => `${s.label} ${fmtNumber(s.pct, 0)}%`).join(", ")}
              className="flex h-2.5 gap-0.5 overflow-hidden rounded-[5px]"
            >
              {segs.map((s) => (
                <span key={s.key} className="block h-2.5" style={{ width: `${s.pct}%`, background: s.color }} />
              ))}
            </div>
            <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs">
              {segs.map((s) => (
                <li key={s.key} className="flex items-center gap-1.5">
                  <span aria-hidden="true" className="h-2 w-2 rounded-[2px]" style={{ background: s.color }} />
                  <span className="text-soft">{s.label}</span>
                  <span className="num text-text-2">{fmtNumber(s.pct, 0)}%</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <span className="text-xs text-faint">No invested positions to break down.</span>
        )}

        <span className="mt-1 text-xs text-muted">By currency · FX exposure · % of invested</span>
        {ccy.length ? (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {ccy.map(([k, v]) => (
              <li key={k} className="flex items-center gap-2.5 text-xs">
                <span className="num w-[34px] text-soft">{k}</span>
                <span aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-[3px] bg-raised">
                  <span className="block h-1.5 bg-zone" style={{ width: `${Math.min(100, v)}%` }} />
                </span>
                <span className="num w-11 text-right text-text-2">{fmtNumber(v, 1)}%</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-xs text-faint">No currency exposure reported.</span>
        )}
      </>
    );
  }

  return (
    <section aria-labelledby="alloc-h" className="flex flex-col gap-3 rounded-[16px] border border-line bg-surface px-5 py-[18px]">
      <h2 id="alloc-h" className="m-0 text-sm font-semibold text-text">
        Allocation
      </h2>
      {body}
    </section>
  );
}
