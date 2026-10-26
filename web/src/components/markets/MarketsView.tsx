"use client";
/**
 * Markets page (MAP): TradingView's heatmap for the chosen index, and under it
 * our own sector overview (/api/markets/sectors, polled every 60 s).
 *
 * The two halves come from different sources and are labelled as such: the
 * heatmap is TradingView's data and timing; the cards carry their own
 * freshness from our yfinance batch.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Freshness } from "@/lib/api";
import { fmtClock } from "@/lib/format";
import { MARKET_INDEXES, marketsPaths, type SectorsResponse } from "@/lib/markets";
import { useApi } from "@/lib/useApi";
import { FreshnessBadge } from "../FreshnessBadge";
import { Panel, PanelHeader } from "../Panel";
import { Segmented } from "../Segmented";
import { StateView } from "../StateView";
import { MarketHeatmap } from "./MarketHeatmap";
import { SectorCard } from "./SectorCard";

const POLL = 60_000;

/** The typical (median-age) freshness across priced members, for the section badge. */
function summarise(data: SectorsResponse): { freshness: Freshness; age: number | null } {
  const ms = data.sectors.flatMap((s) => s.members).filter((m) => m.last != null && m.age_min != null);
  if (!ms.length) return { freshness: "unknown", age: null };
  const sorted = [...ms].sort((a, b) => (a.age_min ?? 0) - (b.age_min ?? 0));
  const mid = sorted[Math.floor(sorted.length / 2)];
  return { freshness: mid.freshness, age: mid.age_min };
}

function Sectors({ index, label }: { index: NonNullable<(typeof MARKET_INDEXES)[number]["sectors"]>; label: string }) {
  const { data, error, isLoading, mutate } = useApi<SectorsResponse>(marketsPaths.sectors(index), { refreshInterval: POLL });
  const current = data && data.index === index ? data : undefined;

  let body;
  if (!current) {
    body =
      error && !isLoading ? (
        <Panel>
          <StateView kind="error" error={error} onRetry={() => mutate()} />
        </Panel>
      ) : (
        <Panel>
          <StateView kind="loading" title={`Pricing the ${label} sector leaders`} message="One batched request for every leader's 5-minute bars, then a headline per sector." />
        </Panel>
      );
  } else {
    const { freshness, age } = summarise(current);
    const basis =
      current.sectors[0]?.change_basis === "members_avg"
        ? "Sector move = equal-weighted average of the listed leaders (no sector ETFs)."
        : "Sector move = its SPDR sector ETF (XLK, XLF, …).";
    body = (
      <>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted">
          <FreshnessBadge freshness={freshness} ageMin={age} />
          <span>
            Updated <span className="num text-soft">{fmtClock(current.as_of)}</span>
          </span>
          <span aria-hidden="true" className="text-faint">
            ·
          </span>
          <span>{basis}</span>
          <span aria-hidden="true" className="text-faint">
            ·
          </span>
          <span title="Curated snapshot in watchlists/sector_leaders.json; not a live membership feed">
            Leaders snapshot <span className="num text-soft">{current.membership_as_of ?? "undated"}</span>
          </span>
          {error ? (
            <span role="status" className="rounded-chip bg-down/12 px-2 py-0.5 text-down-soft">
              Refresh failed · showing data from {fmtClock(current.as_of)}
            </span>
          ) : null}
        </div>
        {current.errors.length ? (
          <details className="rounded-lg border border-line bg-amber/[0.05] px-3 py-2 text-xs text-soft">
            <summary className="cursor-pointer text-amber">
              {current.errors.length} {current.errors.length === 1 ? "symbol or source" : "symbols or sources"} came back incomplete
            </summary>
            <ul className="num m-0 mt-1.5 list-none p-0 text-[11px] leading-[1.6] text-muted">
              {current.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </details>
        ) : null}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(360px,1fr))] gap-4">
          {current.sectors.map((s) => (
            <SectorCard key={s.sector} s={s} expected={freshness} />
          ))}
        </div>
      </>
    );
  }

  return (
    <section aria-labelledby="sectors-h" className="flex flex-col gap-3">
      <div className="flex items-baseline gap-3">
        <h2 id="sectors-h" className="m-0 text-base font-semibold text-text">
          Sectors
        </h2>
        <span className="num text-[11px] tracking-[0.8px] text-amber">{label.toUpperCase()} LEADERS</span>
        {current ? (
          <span className="ml-auto text-xs text-faint">
            Best to worst · headline is for each sector&apos;s biggest mover · click a row for its chart
          </span>
        ) : null}
      </div>
      {body}
    </section>
  );
}

export function MarketsView({ initialIndex }: { initialIndex?: string }) {
  const router = useRouter();
  const [value, setValue] = useState(
    MARKET_INDEXES.some((o) => o.value === initialIndex) ? (initialIndex as string) : MARKET_INDEXES[0].value,
  );
  const opt = MARKET_INDEXES.find((o) => o.value === value) ?? MARKET_INDEXES[0];

  const choose = (v: string) => {
    setValue(v);
    router.replace(v === MARKET_INDEXES[0].value ? "/terminal/markets" : `/terminal/markets?index=${v}`, { scroll: false });
  };

  return (
    <div className="flex flex-col gap-5 px-6 py-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="m-0 text-lg font-semibold text-text">Markets</h1>
        <Segmented
          ariaLabel="Index"
          value={value}
          onChange={choose}
          surface="surface"
          controls="markets-heatmap"
          options={MARKET_INDEXES.map((o) => ({ value: o.value, label: o.label, ariaLabel: o.ariaLabel }))}
        />
      </div>

      <Panel id="markets-heatmap" role="tabpanel" aria-labelledby="heatmap-h">
        <PanelHeader
          id="heatmap-h"
          title={`${opt.label} heatmap`}
          tag="SIZE MKT CAP · COLOUR 1D %"
          right={
            <>
              <span className="text-faint" title="On 2026-09-24 during US hours the widget still showed the previous session's 1D change. The sector cards below carry their own timestamps.">TradingView&apos;s data · can lag a session</span>
              <a
                href="https://www.tradingview.com/"
                target="_blank"
                rel="noopener nofollow"
                className="text-soft underline decoration-line-3 underline-offset-2 hover:text-amber-hover"
              >
                Heatmap by TradingView
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </>
          }
        />
        <div className="h-[560px] border-t border-line">
          <MarketHeatmap dataSource={opt.tvDataSource} label={opt.label} />
        </div>
      </Panel>

      {opt.sectors ? (
        <Sectors key={opt.sectors} index={opt.sectors} label={opt.label} />
      ) : (
        <section aria-label="Sectors" className="flex flex-col gap-3">
          <h2 className="m-0 text-base font-semibold text-text">Sectors</h2>
          <Panel>
            <StateView
              kind="info"
              title={`No sector overview for the ${opt.label}`}
              message={`The cards below the map come from a curated list of each sector's largest members, which exists for the S&P 500, Nasdaq 100, Dow 30 and OMXS30. Two thousand small caps don't reduce to a leaders list, so for the ${opt.label} only TradingView's map is shown.`}
            />
          </Panel>
        </section>
      )}
    </div>
  );
}
