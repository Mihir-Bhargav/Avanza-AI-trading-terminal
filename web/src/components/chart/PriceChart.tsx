"use client";
/**
 * Candlestick chart on Lightweight Charts v5 with the TTM zones shaded over
 * one session (ZoneBands primitive), overlays on the price pane, volume at
 * the bottom of the price pane, and every other indicator pane ("rsi",
 * "macd", "atr", ...) as its own synced pane below. The chart draws no
 * text labels for levels: the ladder beside it lists them.
 *
 * `compact` is the cockpit's small focus chart (no sub-panes, no crosshair labels).
 */
import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  TickMarkType,
  createChart,
  type IChartApi,
  type LogicalRange,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, ChartSeries } from "@/lib/api";
import { cssColor, timeInTz, type ZoneWindow } from "./chartUtils";
import { ZoneBands } from "./ZoneBands";

const PANE_LABEL: Record<string, string> = {
  rsi: "RSI 14",
  macd: "MACD 12 26 9",
  atr: "ATR %",
  compass: "TREND COMPASS",
};

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function withAlpha(hex: string, alpha: number) {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

const NO_SERIES: ChartSeries[] = [];

export interface PriceChartProps {
  candles: Candle[];
  series?: ChartSeries[];
  zones?: ZoneWindow | null;
  tz: string;
  intraday: boolean;
  /** Last price for the amber tag (quote price, falls back to the last close). */
  lastPrice?: number | null;
  compact?: boolean;
  /** Identity of what is shown; the visible range is kept across refreshes of the same view. */
  viewKey: string;
  /** Initial number of bars in view (default: all). */
  initialBars?: number;
  ariaLabel: string;
  className?: string;
}

export function PriceChart({
  candles,
  series = NO_SERIES,
  zones = null,
  tz,
  intraday,
  lastPrice,
  compact = false,
  viewKey,
  initialBars,
  ariaLabel,
  className,
}: PriceChartProps) {
  const host = useRef<HTMLDivElement>(null);
  const kept = useRef<{ key: string; range: LogicalRange | null } | null>(null);
  const [paneLabels, setPaneLabels] = useState<{ label: string; top: number }[]>([]);

  useEffect(() => {
    const el = host.current;
    if (!el || candles.length === 0) return;

    const up = cssVar("--up", "#3dd68c");
    const down = cssVar("--down", "#ff6a5e");
    const mono = getComputedStyle(document.body).getPropertyValue("--font-geist-mono").trim() || "ui-monospace, monospace";

    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0E1115" },
        textColor: "#7D8793",
        fontFamily: mono,
        fontSize: compact ? 10 : 11,
        attributionLogo: false,
        panes: { separatorColor: "#1F242C", separatorHoverColor: "#2B323C", enableResize: !compact },
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "#1A1F26" },
      },
      rightPriceScale: { borderColor: "#1F242C", scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: "#1F242C",
        timeVisible: intraday,
        secondsVisible: false,
        rightOffset: compact ? 2 : 4,
        visible: true,
        tickMarkFormatter: (time: Time, type: TickMarkType) => {
          const t = time as number;
          if (type === TickMarkType.Time || type === TickMarkType.TimeWithSeconds) return timeInTz(t, tz);
          return new Date(t * 1000).toLocaleDateString("en-GB", {
            timeZone: tz,
            day: type === TickMarkType.Year || type === TickMarkType.Month ? undefined : "numeric",
            month: "short",
            year: type === TickMarkType.Year ? "numeric" : undefined,
          });
        },
      },
      localization: {
        timeFormatter: (time: Time) => {
          const t = time as number;
          return intraday
            ? timeInTz(t, tz, true)
            : new Date(t * 1000).toLocaleDateString("en-GB", { timeZone: tz, day: "2-digit", month: "short", year: "numeric" });
        },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#2B323C", labelBackgroundColor: "#232A33", labelVisible: !compact },
        horzLine: { color: "#2B323C", labelBackgroundColor: "#232A33", labelVisible: !compact },
      },
      handleScroll: !compact,
      handleScale: !compact,
    });

    const price = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      wickUpColor: up,
      wickDownColor: down,
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    price.setData(candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));

    const last = lastPrice ?? candles[candles.length - 1].close;
    price.createPriceLine({
      price: last,
      color: "rgba(245,166,35,0.6)",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      axisLabelColor: "#F5A623",
      axisLabelTextColor: "#1A1204",
      title: "",
    });

    const bands = new ZoneBands(zones);
    price.attachPrimitive(bands);

    // Indicator series. Overlays and volume share pane 0; the rest get a pane each.
    const paneIndex = new Map<string, number>();
    const paneOrder: string[] = [];
    for (const s of series) {
      const pane = String(s.pane);
      if (pane === "overlay") {
        chart
          .addSeries(LineSeries, {
            color: cssColor(s.color),
            lineWidth: (s.lineWidth ?? 1) as 1 | 2 | 3 | 4,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          })
          .setData(s.data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
        continue;
      }
      if (pane === "vol") {
        const vol = chart.addSeries(HistogramSeries, {
          priceScaleId: "vol",
          priceFormat: { type: "volume" },
          priceLineVisible: false,
          lastValueVisible: false,
        });
        vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        vol.setData(
          s.data.map((p) => ({
            time: p.time as UTCTimestamp,
            value: p.value,
            color: (p.color ?? "").toLowerCase().startsWith("#26a69a") ? withAlpha(up, 0.28) : withAlpha(down, 0.28),
          })),
        );
        continue;
      }
      if (compact) continue;
      if (!paneIndex.has(pane)) {
        paneIndex.set(pane, paneOrder.length + 1);
        paneOrder.push(pane);
      }
      const idx = paneIndex.get(pane)!;
      if (s.kind === "histogram") {
        chart
          .addSeries(
            HistogramSeries,
            { priceLineVisible: false, lastValueVisible: false },
            idx,
          )
          .setData(
            s.data.map((p) => ({
              time: p.time as UTCTimestamp,
              value: p.value,
              color: p.value >= 0 ? withAlpha(up, 0.45) : withAlpha(down, 0.45),
            })),
          );
      } else {
        const reference = /^-?\d+(\.\d+)?$/.test(s.title); // "70", "30", "0" guide lines
        chart
          .addSeries(
            LineSeries,
            {
              color: reference ? "#2B323C" : cssColor(s.color),
              lineWidth: reference ? 1 : ((s.lineWidth ?? 1) as 1 | 2 | 3 | 4),
              lineStyle: reference ? LineStyle.Dashed : LineStyle.Solid,
              priceLineVisible: false,
              lastValueVisible: !reference,
              crosshairMarkerVisible: false,
            },
            idx,
          )
          .setData(s.data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      }
    }

    const panes = chart.panes();
    panes[0]?.setStretchFactor(1);
    for (let i = 1; i < panes.length; i++) panes[i].setStretchFactor(0.26);

    // Keep the user's zoom across data refreshes of the same view.
    const ts = chart.timeScale();
    if (kept.current?.key === viewKey && kept.current.range) {
      ts.setVisibleLogicalRange(kept.current.range);
    } else if (initialBars && candles.length > initialBars) {
      ts.setVisibleLogicalRange({ from: candles.length - initialBars, to: candles.length + 2 });
    } else {
      ts.fitContent();
    }
    const onRange = (r: LogicalRange | null) => {
      kept.current = { key: viewKey, range: r };
    };
    ts.subscribeVisibleLogicalRangeChange(onRange);

    // Pane captions (HTML, top-left of each sub-pane).
    const placeLabels = () => {
      const ps = chart.panes();
      let top = 0;
      const out: { label: string; top: number }[] = [];
      ps.forEach((p, i) => {
        if (i > 0) out.push({ label: PANE_LABEL[paneOrder[i - 1]] ?? paneOrder[i - 1].toUpperCase(), top: top + 6 });
        top += p.getHeight() + 1;
      });
      setPaneLabels(out);
    };
    const raf = requestAnimationFrame(placeLabels);
    const ro = new ResizeObserver(() => requestAnimationFrame(placeLabels));
    ro.observe(el);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      ts.unsubscribeVisibleLogicalRangeChange(onRange);
      chart.remove();
    };
  }, [candles, series, zones, tz, intraday, lastPrice, compact, viewKey, initialBars]);

  return (
    <div className={className} style={{ position: "relative" }}>
      <div ref={host} role="img" aria-label={ariaLabel} className="absolute inset-0" />
      {paneLabels.map((p) => (
        <span
          key={p.label + p.top}
          className="num pointer-events-none absolute left-3 z-10 text-[10px] tracking-[0.8px] text-muted"
          style={{ top: p.top }}
        >
          {p.label}
        </span>
      ))}
    </div>
  );
}
