/**
 * Helpers shared by the chart workspace and the cockpit focus chart:
 * exchange time zones, timeframe presets, colour conversion, and the TTM
 * session window (which candles belong to the session the zones describe).
 */
import type { Candle, Freshness, SetupRow } from "@/lib/api";

/* -------------------------------------------------------------- timeframes */

export type Timeframe = "1m" | "5m" | "15m" | "1H" | "1D";

/**
 * UI timeframe -> backend params (terminal/app.py /api/chart accepts yfinance
 * intervals; warm-up frames exist for 1m, 5m, 15m, 1h, 1d). yfinance caps 1m at
 * 7 days and sub-hour bars at 60 days, so lookbacks stay inside those limits.
 */
export const TIMEFRAMES: Record<Timeframe, { interval: string; lookback: string; label: string; spoken: string }> = {
  "1m": { interval: "1m", lookback: "1d", label: "1M · 1 SESSION", spoken: "1 minute" },
  "5m": { interval: "5m", lookback: "5d", label: "5M · 5 DAYS", spoken: "5 minutes" },
  "15m": { interval: "15m", lookback: "5d", label: "15M · 5 DAYS", spoken: "15 minutes" },
  "1H": { interval: "1h", lookback: "1mo", label: "1H · 1 MONTH", spoken: "1 hour" },
  "1D": { interval: "1d", lookback: "1y", label: "1D · 1 YEAR", spoken: "1 day" },
};
export const TIMEFRAME_ORDER: Timeframe[] = ["1m", "5m", "15m", "1H", "1D"];

/* -------------------------------------------------------------- time zones */

/** Exchange time zone from the Yahoo ticker. Stockholm names end in .ST; ^OMX is Stockholm too. */
export function exchangeTz(yahoo: string): string {
  const s = yahoo.toUpperCase();
  if (s.endsWith(".ST") || s === "^OMX" || s === "^OMXS30") return "Europe/Stockholm";
  if (s.endsWith(".DE") || s === "^GDAXI") return "Europe/Berlin";
  if (s.endsWith(".L")) return "Europe/London";
  if (s.endsWith(".AS")) return "Europe/Amsterdam";
  return "America/New_York";
}

export function exchangeLabel(yahoo: string): string {
  const tz = exchangeTz(yahoo);
  if (tz === "Europe/Stockholm") return "Stockholm";
  if (tz === "America/New_York") return yahoo.startsWith("^") ? "US index" : "US";
  return tz.split("/")[1] ?? tz;
}

const dateFmtCache = new Map<string, Intl.DateTimeFormat>();
function dateFmt(tz: string) {
  let f = dateFmtCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" });
    dateFmtCache.set(tz, f);
  }
  return f;
}
/** "2026-09-23" for an epoch-seconds time in the given zone. */
export function isoDateInTz(epochSec: number, tz: string): string {
  return dateFmt(tz).format(new Date(epochSec * 1000));
}

export function timeInTz(epochSec: number, tz: string, withDate = false): string {
  return new Date(epochSec * 1000).toLocaleString("en-GB", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(withDate ? { day: "2-digit", month: "short" } : {}),
  });
}

/* ------------------------------------------------------------------ colour */

/** "#ef535055" -> "rgba(239,83,80,0.33)". Lightweight Charts does not read 8-digit hex reliably. */
export function cssColor(c: string | undefined, fallback = "#AEB6C0"): string {
  if (!c) return fallback;
  const m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(c.trim());
  if (!m) return c;
  const n = parseInt(m[1], 16);
  const a = m[2] ? parseInt(m[2], 16) / 255 : 1;
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(2)})`;
}

/* --------------------------------------------------------------- freshness */

/** The chart quote can say "realtime" (Avanza/yf live feed); the UI type calls that "live". */
export function normFreshness(f: string | null | undefined): Freshness {
  if (f === "realtime") return "live";
  if (f === "live" || f === "delayed" || f === "closed" || f === "stale") return f;
  return "unknown";
}

/* ------------------------------------------------------------- TTM window */

export interface ZoneWindow {
  /** Logical index range (inclusive) of the candles in the zones' session. */
  from: number;
  to: number;
  z1: number;
  z2: number;
  z3: number;
  z4: number;
  sessionDate: string;
}

/**
 * The zones in a setups row describe one session: `bar_date` (the daily bar
 * classified). Returns the candle index range for that session, or null when
 * none of the candles fall on it (e.g. the chart's lookback ends earlier).
 */
export function zoneWindow(candles: Candle[], row: SetupRow | null | undefined, tz: string): ZoneWindow | null {
  if (!row || candles.length === 0) return null;
  const session = row.bar_date ?? isoDateInTz(candles[candles.length - 1].time, tz);
  let from = -1;
  let to = -1;
  for (let i = 0; i < candles.length; i++) {
    // Intraday and daily bars are both stamped in exchange time, so compare dates there.
    if (isoDateInTz(candles[i].time, tz) === session) {
      if (from < 0) from = i;
      to = i;
    }
  }
  if (from < 0) return null;
  return { from, to, z1: row.zone1, z2: row.zone2, z3: row.zone3, z4: row.zone4, sessionDate: session };
}

/** Find a setups row for a route symbol: matches symbol or yahoo, ignoring case, spaces ~ dashes. */
export function findRow(rows: SetupRow[] | undefined, symbol: string): SetupRow | null {
  if (!rows) return null;
  const norm = (s: string) => s.trim().toUpperCase().replace(/\s+/g, "-");
  const s = norm(symbol);
  return rows.find((r) => norm(r.symbol) === s || norm(r.yahoo) === s) ?? null;
}

/** Absolute change implied by the last price and its percent change. */
export function absChange(price: number, changePct: number | null | undefined): number | null {
  if (changePct == null || !Number.isFinite(changePct)) return null;
  const prev = price / (1 + changePct / 100);
  return price - prev;
}
