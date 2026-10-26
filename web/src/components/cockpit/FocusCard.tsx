"use client";
import { useMemo } from "react";
import { Button } from "@/components/Button";
import { FreshnessBadge } from "@/components/FreshnessBadge";
import { Num } from "@/components/Num";
import { Panel } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import { PriceChart } from "@/components/chart/PriceChart";
import { absChange, exchangeTz, normFreshness, zoneWindow } from "@/components/chart/chartUtils";
import { historyLine, stateSentence } from "@/components/chart/ttm";
import type { ChartResponse, SetupRow } from "@/lib/api";
import { paths } from "@/lib/api";
import { routes } from "@/lib/commands";
import { fmtPct, fmtPrice, fmtSigned } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { PlanForm } from "./PlanForm";

export function FocusCard({ row }: { row: SetupRow }) {
  const chartPath = paths.chart(row.yahoo, { interval: "15m", lookback: "5d" });
  const chart = useApi<ChartResponse>(chartPath, { refreshInterval: 60_000 });
  const tz = exchangeTz(row.yahoo);
  const candles = chart.data?.candles;
  const zones = useMemo(() => (candles ? zoneWindow(candles, row, tz) : null), [candles, row, tz]);

  const q = chart.data?.quote ?? null;
  const price = q?.price ?? null;
  const chg = price != null ? absChange(price, q?.change_pct) : null;

  return (
    <Panel as="aside" aria-labelledby="focus-h" className="w-[392px] shrink-0 gap-3 overflow-y-auto px-5 py-4">
      <div className="flex items-center gap-2.5">
        <h2 id="focus-h" className="num m-0 text-lg font-semibold text-text">
          {row.symbol}
        </h2>
        <span className="truncate text-[13px] text-muted">{row.name}</span>
        {q ? <FreshnessBadge freshness={normFreshness(q.freshness)} ageMin={q.age_min} className="ml-auto" /> : null}
      </div>

      <div className="flex items-baseline gap-3">
        {price != null ? (
          <>
            <Num value={price} kind="price" className="text-[30px] leading-none text-text" />
            <Num colored value={q?.change_pct} className="text-sm">
              {chg != null ? `${fmtSigned(chg, 2)} (${fmtPct(q?.change_pct)})` : fmtPct(q?.change_pct)}
            </Num>
          </>
        ) : chart.isLoading ? (
          <span className="text-[13px] text-faint">Loading quote…</span>
        ) : (
          <>
            <Num value={row.close} kind="price" className="text-[30px] leading-none text-text" />
            <span className="text-xs text-faint">close {row.bar_date ?? ""} · no live quote</span>
          </>
        )}
      </div>

      <div className="h-[132px] shrink-0 overflow-hidden rounded-control bg-rail">
        {chart.isLoading ? (
          <StateView kind="loading" compact title="Loading 15-minute bars" className="h-full" />
        ) : chart.error && !chart.data ? (
          <StateView kind="error" compact error={chart.error} onRetry={() => chart.mutate()} className="h-full" />
        ) : candles && candles.length ? (
          <PriceChart
            candles={candles}
            zones={zones}
            tz={tz}
            intraday
            lastPrice={price}
            compact
            viewKey={`focus-${row.yahoo}`}
            initialBars={56}
            ariaLabel={`${row.name} 15-minute candles with the TTM zones for ${zones?.sessionDate ?? "the latest session"}`}
            className="h-full"
          />
        ) : (
          <StateView kind="empty" compact title="No intraday bars" message="The feed returned no 15-minute candles." className="h-full" />
        )}
      </div>
      <div className="num -mt-1 flex gap-4 text-[10px] tracking-[0.6px]">
        <span className="text-amber">▮ Z1–Z2 {fmtPrice(Math.max(row.zone1, row.zone2))}–{fmtPrice(Math.min(row.zone1, row.zone2))}</span>
        <span className="text-zone">▮ Z3–Z4 {fmtPrice(Math.max(row.zone3, row.zone4))}–{fmtPrice(Math.min(row.zone3, row.zone4))}</span>
        {!zones && candles?.length ? <span className="text-faint">zone session not in view</span> : null}
      </div>

      <div className="flex flex-col gap-1 text-[13px]">
        <span className={row.state.startsWith("crossed") ? "font-medium text-amber" : "font-medium text-soft"}>{stateSentence(row)}</span>
        <span className="num text-xs text-muted">{historyLine(row)}</span>
      </div>

      <PlanForm key={row.symbol} row={row} price={price} />

      <div className="sticky -bottom-4 mt-auto -mb-4 flex shrink-0 gap-2.5 bg-surface pb-4 pt-2">
        <Button variant="amber" size="md" href={routes.chart(row.symbol)} className="flex-1">
          Open chart
        </Button>
        <Button variant="outline" size="md" href={`/terminal/news?ask=${encodeURIComponent(row.symbol)}`} className="flex-1">
          Ask Kes
        </Button>
      </div>
    </Panel>
  );
}
