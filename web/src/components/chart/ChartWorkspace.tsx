"use client";
/**
 * Chart workspace (/terminal/chart/[symbol]): header with quote, timeframe /
 * layout / indicator controls, the main chart (or a 2/4 grid of the same
 * symbol at other timeframes), and on the right the TTM card and the levels
 * ladder.
 *
 * Symbol resolution: the route symbol may be a setups symbol ("ERIC-B"), a
 * Yahoo ticker ("ERIC-B.ST") or a command-bar form ("ERIC B"). The setups list
 * maps it to its Yahoo ticker; outside the universe the route symbol is used
 * as-is and the TTM row is computed ad hoc via /api/setups?symbol=.
 */
import { useMemo, useState } from "react";
import { FreshnessBadge } from "@/components/FreshnessBadge";
import { Num } from "@/components/Num";
import { Panel } from "@/components/Panel";
import { Segmented } from "@/components/Segmented";
import { StateView } from "@/components/StateView";
import type { Candle, ChartResponse, SetupsResponse } from "@/lib/api";
import { paths } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtPct, fmtSigned } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import {
  TIMEFRAMES,
  TIMEFRAME_ORDER,
  absChange,
  cssColor,
  exchangeLabel,
  exchangeTz,
  findRow,
  normFreshness,
  timeInTz,
  zoneWindow,
  type Timeframe,
} from "./chartUtils";
import { IndicatorsMenu } from "./IndicatorsMenu";
import { LevelsLadder } from "./LevelsLadder";
import { PriceChart } from "./PriceChart";
import { TtmCard } from "./TtmCard";
import { InstrumentCard } from "./InstrumentCard";
import { avanzaPaths, type InstrumentDetail } from "@/lib/avanza";
import type { SetupRow } from "@/lib/api";

type Layout = "1" | "2" | "4";
const DEFAULT_IND = ["vol", "ema", "vwap", "rsi"];

/** Timeframes for the extra cells in a 2/4 layout: the chosen one first, then the most useful others. */
function gridFrames(tf: Timeframe, layout: Layout): Timeframe[] {
  if (layout === "1") return [tf];
  const pref: Timeframe[] = ["1D", "1H", "5m", "15m", "1m"].filter((t) => t !== tf) as Timeframe[];
  return [tf, ...pref.slice(0, layout === "2" ? 1 : 3)];
}

/** Wilder ATR14 from daily candles (used only when the setups row has no atr14). */
function atr14(c: Candle[]): number | null {
  if (c.length < 15) return null;
  let atr: number | null = null;
  for (let i = 1; i < c.length; i++) {
    const tr = Math.max(c[i].high - c[i].low, Math.abs(c[i].high - c[i - 1].close), Math.abs(c[i].low - c[i - 1].close));
    atr = atr == null ? tr : atr + (tr - atr) / 14;
  }
  return atr;
}

function useChart(yahoo: string | null, tf: Timeframe, ind: string[]) {
  const t = TIMEFRAMES[tf];
  const path = yahoo ? paths.chart(yahoo, { interval: t.interval, lookback: t.lookback, ind }) : null;
  return useApi<ChartResponse>(path, { refreshInterval: tf === "1D" ? 300_000 : 60_000 });
}

const AV_RE = /^AV:(\d+)$/i;

/** Tickers chart directly. "AV:<orderbook id>" (an Avanza certificate/mini) charts its
 *  underlying with the instrument's barrier and financing added, or, when the underlying
 *  can't be identified, the instrument's own (sparse, daily) history. */
export function ChartWorkspace({ symbol }: { symbol: string }) {
  const m = AV_RE.exec(symbol);
  return m ? <InstrumentWorkspace oid={m[1]} /> : <Workspace symbol={symbol} />;
}

function InstrumentWorkspace({ oid }: { oid: string }) {
  const inst = useApi<InstrumentDetail>(avanzaPaths.instrument(oid), { refreshInterval: 30_000 });
  const d = inst.data;
  if (inst.error || d?.error || !d) {
    return (
      <div className="flex flex-1 px-6 py-[18px]">
        <Panel className="flex-1">
          {inst.error || d?.error ? (
            <StateView kind="error" error={inst.error} message={d?.error} onRetry={() => inst.mutate()} />
          ) : (
            <StateView kind="loading" mood="thinking" title="Loading instrument" />
          )}
        </Panel>
      </div>
    );
  }
  return d.underlying
    ? <Workspace key={d.underlying} symbol={d.underlying} instrument={d} />
    : <Workspace key={`AV:${oid}`} symbol={`AV:${oid}`} instrument={d} ownHistory />;
}

function Workspace({ symbol, instrument, ownHistory = false }: { symbol: string; instrument?: InstrumentDetail; ownHistory?: boolean }) {
  const [tf, setTf] = useState<Timeframe>(ownHistory ? "1D" : "15m");
  const [layout, setLayout] = useState<Layout>("1");
  const [ind, setInd] = useState<string[]>(DEFAULT_IND);

  // Resolve the symbol through the (cached) setups list; ad hoc row when outside the universe.
  // An instrument without an identified underlying has no setups row to look up.
  const all = useApi<SetupsResponse>(ownHistory ? null : paths.setups(), { refreshInterval: 300_000 });
  const listed = findRow(all.data?.rows, symbol);
  const settled = ownHistory || all.data !== undefined || all.error !== undefined;
  const needAdhoc = !ownHistory && settled && !listed;
  const adhoc = useApi<SetupsResponse>(needAdhoc ? paths.setups(symbol) : null);
  const row: SetupRow | null = listed ?? adhoc.data?.rows[0] ?? null;
  const yahoo = settled ? (listed?.yahoo ?? symbol) : null;
  const tz = exchangeTz(yahoo ?? symbol);

  const main = useChart(yahoo, tf, ind);
  const q = main.data?.quote ?? null;
  const last = q?.price ?? main.data?.candles.at(-1)?.close ?? null;
  const chg = q ? absChange(q.price, q.change_pct) : null;

  // ATR for the ladder: setups atr14 (daily) when known, else computed from daily bars here.
  const daily = useApi<ChartResponse>(yahoo && settled && !row && !adhoc.isLoading ? paths.chart(yahoo, { interval: "1d", lookback: "3mo" }) : null);
  const localAtr = useMemo(() => (daily.data ? atr14(daily.data.candles) : null), [daily.data]);
  const atr = row?.atr14 ?? localAtr;
  const atrSource = row?.atr14 ? "daily ATR14 from the setups panel" : localAtr ? "daily ATR14 computed here from 3 months of daily bars" : "ATR (unavailable)";

  // Barrier and financing are quoted in the underlying's price, so they belong in its ladder.
  const extraLevels: { label: string; price: number; color: string }[] = [];
  if (instrument && !ownHistory) {
    if (instrument.barrier != null) extraLevels.push({ label: "KO barrier", price: instrument.barrier, color: "#FF6A5E" });
    if (instrument.financing != null) extraLevels.push({ label: "Financing", price: instrument.financing, color: "#F5A623" });
  }
  const ladderChart = main.data && extraLevels.length ? { ...main.data, levels: [...main.data.levels, ...extraLevels] } : main.data;

  const frames = gridFrames(tf, layout);
  const fresh = q ? normFreshness(q.freshness) : null;
  const closedAt = q && fresh === "closed" ? timeInTz(Date.parse(q.ts) / 1000, tz) : undefined;

  return (
    <div className="flex min-h-[720px] flex-1 gap-4 px-6 py-[18px]">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex min-h-9 flex-wrap items-center gap-x-3.5 gap-y-1">
          <h1 className="num m-0 text-2xl font-semibold text-text">{instrument ? instrument.name : (row?.symbol ?? symbol)}</h1>
          <span className="text-sm text-muted">
            {instrument
              ? ownHistory
                ? "Avanza instrument · own trade history"
                : `Underlying ${row?.symbol ?? symbol}${row?.name && row.name.toUpperCase() !== row.symbol.toUpperCase() ? ` (${row.name})` : ""} · ${exchangeLabel(yahoo ?? symbol)}`
              : <>
                  {row?.name && row.name.toUpperCase() !== row.symbol.toUpperCase() ? `${row.name} · ` : ""}
                  {exchangeLabel(yahoo ?? symbol)}
                </>}
          </span>
          {q ? (
            <>
              <Num value={q.price} kind="price" className="text-[22px] text-text" />
              <Num colored value={q.change_pct} className="text-sm">
                {chg != null ? `${fmtSigned(chg, 2)} (${fmtPct(q.change_pct)})` : fmtPct(q.change_pct)}
              </Num>
              <FreshnessBadge
                freshness={fresh!}
                ageMin={fresh === "closed" ? null : q.age_min}
                closedAt={closedAt}
                suffix={fresh !== "closed" && q.age_min >= 1 ? "OLD" : undefined}
              />
            </>
          ) : main.data ? (
            <span className="text-xs text-faint">No quote from the feed</span>
          ) : null}
        </div>

        <div className="flex items-center gap-3">
          <Segmented<Timeframe>
            ariaLabel="Timeframe"
            mono
            size="sm"
            surface="surface"
            value={tf}
            onChange={setTf}
            options={(ownHistory ? (["1D"] as Timeframe[]) : TIMEFRAME_ORDER).map((t) => ({ value: t, label: t, ariaLabel: TIMEFRAMES[t].spoken }))}
          />
          <Segmented<Layout>
            ariaLabel="Layout"
            mono
            size="sm"
            surface="surface"
            value={layout}
            onChange={setLayout}
            options={[
              { value: "1", label: "1", ariaLabel: "One chart" },
              { value: "2", label: "2", ariaLabel: "Two charts" },
              { value: "4", label: "4", ariaLabel: "Four charts" },
            ]}
            className="[&_button]:min-w-9"
          />
          <IndicatorsMenu value={ind} onChange={setInd} />
          <span className="ml-auto text-xs text-faint">Read-only chart · no order entry</span>
        </div>

        {layout === "1" ? (
          <ChartPanel yahoo={yahoo} tf={tf} ind={ind} res={main} row={row} tz={tz} main />
        ) : (
          <div className={cx("grid min-h-0 flex-1 gap-3", layout === "2" ? "grid-cols-2" : "grid-cols-2 grid-rows-2")}>
            {frames.map((f, i) =>
              i === 0 ? (
                <ChartPanel key={f} yahoo={yahoo} tf={f} ind={ind} res={main} row={row} tz={tz} main={false} dense={layout === "4"} />
              ) : (
                <GridCell key={f} yahoo={yahoo} tf={f} ind={ind} row={row} tz={tz} dense={layout === "4"} onPick={() => { setTf(f); setLayout("1"); }} />
              ),
            )}
          </div>
        )}
      </div>

      <aside aria-label="Setup and levels" className="flex w-[312px] shrink-0 flex-col gap-3.5 min-h-0">
        {instrument ? <InstrumentCard d={instrument} ownHistory={ownHistory} /> : null}
        {ownHistory ? null : <TtmCard
          row={row}
          inUniverse={!!listed}
          loading={!settled || adhoc.isLoading}
          error={needAdhoc ? adhoc.error : undefined}
          onRetry={() => adhoc.mutate()}
          symbol={symbol}
        />}
        <LevelsLadder
          chart={ladderChart}
          row={row}
          last={last}
          atr={atr}
          atrSource={atrSource}
          loading={main.isLoading || !settled}
          error={main.error}
          onRetry={() => main.mutate()}
        />
      </aside>
    </div>
  );
}

function GridCell(props: { yahoo: string | null; tf: Timeframe; ind: string[]; row: SetupRow | null; tz: string; dense: boolean; onPick: () => void }) {
  const res = useChart(props.yahoo, props.tf, props.ind);
  return <ChartPanel {...props} res={res} main={false} />;
}

function ChartPanel({
  yahoo,
  tf,
  res,
  row,
  tz,
  main,
  dense = false,
  onPick,
}: {
  yahoo: string | null;
  tf: Timeframe;
  ind: string[];
  res: ReturnType<typeof useChart>;
  row: SetupRow | null;
  tz: string;
  main: boolean;
  dense?: boolean;
  onPick?: () => void;
}) {
  const t = TIMEFRAMES[tf];
  const d = res.data;
  const candles = d?.candles;
  const zones = useMemo(() => (candles ? zoneWindow(candles, row, tz) : null), [candles, row, tz]);
  // In the 4-up grid, only price-pane series (overlays + volume) fit.
  const series = useMemo(
    () => (d ? (dense ? d.series.filter((s) => s.pane === "overlay" || s.pane === "vol") : d.series) : undefined),
    [d, dense],
  );
  const overlays = useMemo(() => {
    const seen = new Set<string>();
    return (d?.series ?? []).filter((s) => s.pane === "overlay" && !seen.has(s.title) && seen.add(s.title));
  }, [d]);

  let content;
  if (!yahoo || res.isLoading) content = <StateView kind="loading" title={`Loading ${t.spoken} bars`} className="flex-1" />;
  else if (res.error && !d) content = <StateView kind="error" error={res.error} onRetry={() => res.mutate()} className="flex-1" />;
  else if (!candles?.length) content = <StateView kind="empty" title="No bars" message={`The feed returned no ${t.spoken} candles for ${yahoo}.`} className="flex-1" />;
  else
    content = (
      <PriceChart
        candles={candles}
        series={series}
        zones={zones}
        tz={tz}
        intraday={tf !== "1D"}
        lastPrice={d?.quote?.price ?? null}
        viewKey={`${yahoo}-${tf}`}
        initialBars={tf === "1D" ? 130 : tf === "1m" ? 240 : tf === "5m" ? 160 : undefined}
        ariaLabel={`${yahoo} ${t.spoken} candles${zones ? ` with the TTM zones for ${zones.sessionDate}` : ""}`}
        className="min-h-0 flex-1"
      />
    );

  return (
    <Panel variant="chart" aria-label={`${yahoo ?? ""} ${t.spoken} chart`} className="min-h-0 flex-1">
      <div className="num flex min-h-[30px] flex-wrap items-center gap-x-[18px] gap-y-1 px-4 pb-1 pt-2.5 text-[11px]">
        {onPick ? (
          <button type="button" onClick={onPick} className="cursor-pointer text-muted hover:text-amber" title="Open this timeframe as the main chart">
            {t.label}
          </button>
        ) : (
          <span className="text-muted">{t.label}</span>
        )}
        {!dense &&
          overlays.map((s) => (
            <span key={s.title} style={{ color: cssColor(s.color) }}>
              — {s.title}
            </span>
          ))}
        {row ? (
          zones ? (
            <>
              <span className="text-amber">▮ Z1–Z2</span>
              <span className="text-zone">▮ Z3–Z4</span>
              {!dense ? <span className="text-faint">zones for {zones.sessionDate}</span> : null}
            </>
          ) : candles?.length ? (
            <span className="text-faint">TTM zones: {row.bar_date ?? "session"} not in this view</span>
          ) : null
        ) : null}
        {res.error && d ? <span className="text-warn-text">refresh failed</span> : null}
        {main ? <span className="ml-auto text-faint">Levels listed on the right →</span> : null}
      </div>
      {content}
    </Panel>
  );
}
