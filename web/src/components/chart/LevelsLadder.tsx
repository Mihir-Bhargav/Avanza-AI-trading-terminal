"use client";
/**
 * Every level beside the chart, sorted by price (high to low), with the last
 * price inserted in place and each level's distance from last in ATR. This is
 * where levels are labelled; the chart itself draws none.
 */
import { useEffect, useRef } from "react";
import { Panel } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import type { ChartResponse, SetupRow } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtAtr, fmtPrice } from "@/lib/format";

interface Level {
  name: string;
  price: number;
  swatch: string;
  kind: "ttm" | "pivot" | "last";
}

const PIVOT_NAMES: Record<string, string> = { PDH: "Prev high", PDL: "Prev low", TC: "CPR top", BC: "CPR bottom" };

export function LevelsLadder({
  chart,
  row,
  last,
  atr,
  atrSource,
  loading,
  error,
  onRetry,
}: {
  chart: ChartResponse | undefined;
  row: SetupRow | null;
  last: number | null;
  atr: number | null;
  atrSource: string;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const list = useRef<HTMLOListElement>(null);
  // Keep the "Last" row in view: centre it in the list whenever the price or levels change.
  useEffect(() => {
    const ol = list.current;
    const li = ol?.querySelector<HTMLElement>("[aria-current]");
    if (ol && li) ol.scrollTop = li.offsetTop - ol.clientHeight / 2 + li.clientHeight / 2;
  }, [last, chart, row]);
  let body;
  if (loading && !chart) body = <StateView kind="loading" compact title="Loading levels" />;
  else if (error && !chart) body = <StateView kind="error" compact error={error} onRetry={onRetry} />;
  else {
    const levels: Level[] = [];
    for (const l of chart?.levels ?? []) levels.push({ name: l.label, price: l.price, swatch: "#5C6773", kind: "pivot" });
    if (row) {
      levels.push({ name: "TTM Z1", price: row.zone1, swatch: "var(--amber)", kind: "ttm" });
      levels.push({ name: "TTM Z2", price: row.zone2, swatch: "var(--amber)", kind: "ttm" });
      levels.push({ name: "TTM Z3", price: row.zone3, swatch: "var(--zone)", kind: "ttm" });
      levels.push({ name: "TTM Z4", price: row.zone4, swatch: "var(--zone)", kind: "ttm" });
    }
    if (last != null) levels.push({ name: "Last", price: last, swatch: "var(--amber)", kind: "last" });
    levels.sort((a, b) => b.price - a.price || (a.kind === "last" ? -1 : 1));

    body = levels.length ? (
      <ol ref={list} className="relative m-0 min-h-0 flex-1 list-none overflow-y-auto p-0" aria-label="Levels by price, highest first">
        {levels.map((l) => {
          const isLast = l.kind === "last";
          const dist = !isLast && last != null && atr ? (l.price - last) / atr : null;
          return (
            <li
              key={l.name + l.price}
              className={cx("flex h-7 items-center gap-2.5 px-[18px] text-xs", isLast && "bg-amber/10")}
              aria-current={isLast || undefined}
            >
              <span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: l.swatch }} aria-hidden="true" />
              <span className={cx("w-[74px] truncate", isLast ? "font-semibold text-amber" : "text-text-2")} title={PIVOT_NAMES[l.name]}>
                {l.name}
              </span>
              <span className={cx("num", isLast ? "font-semibold text-amber" : "text-text-2")}>{fmtPrice(l.price)}</span>
              <span className="num ml-auto text-muted">{isLast ? "now" : fmtAtr(dist)}</span>
            </li>
          );
        })}
      </ol>
    ) : (
      <StateView kind="empty" compact title="No levels" message="The chart response had no pivot levels and there are no zones for this symbol." />
    );
  }

  return (
    <Panel aria-labelledby="lv-h" className="min-h-0 flex-1">
      <div className="flex items-baseline px-[18px] pb-2 pt-3.5">
        <h2 id="lv-h" className="m-0 text-sm font-semibold text-text">
          Levels
        </h2>
        <span className="num ml-auto text-[10px] tracking-[0.8px] text-faint">PRICE · FROM LAST</span>
      </div>
      {body}
      <div className="num flex shrink-0 flex-col gap-0.5 border-t border-raised px-[18px] py-2.5 text-[10px] leading-snug text-faint">
        <span>Distance in {atrSource}.</span>
        {chart?.levels_from ? (
          <span className={chart.levels_stale ? "text-warn-text" : undefined}>
            Pivots from the {chart.levels_from} session{chart.levels_stale ? " · STALE" : ""}
          </span>
        ) : null}
        {chart?.cpr_verdict ? <span>CPR: {chart.cpr_verdict}</span> : null}
      </div>
    </Panel>
  );
}
