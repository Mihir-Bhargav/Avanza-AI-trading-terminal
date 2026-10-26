/**
 * Number and time formatting for the terminal. Every function returns "—" for
 * null/undefined/NaN, so a missing value is visible rather than shown as 0.
 *
 * Conventions (System.dc.html): real minus sign (U+2212), explicit "+" on
 * signed values, thin no-break space (U+202F) as the thousands separator.
 */

export const MINUS = "−";
export const THIN = " ";
export const DASH = "—";

type Maybe = number | null | undefined;

const isNum = (v: Maybe): v is number => typeof v === "number" && Number.isFinite(v);

/** Group an unsigned decimal string: 1234567.8 -> "1 234 567.8" (thin spaces). */
function group(abs: number, decimals: number): string {
  const [int, frac] = abs.toFixed(decimals).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
  return frac ? `${grouped}.${frac}` : grouped;
}

/** Plain number with thousands grouping. Negative values get a real minus. */
export function fmtNumber(v: Maybe, decimals = 2): string {
  if (!isNum(v)) return DASH;
  const rounded = Number(v.toFixed(decimals));
  const sign = rounded < 0 ? MINUS : "";
  return sign + group(Math.abs(v), decimals);
}

/** Always-signed number: "+27.00", "−3.40", "0.00". */
export function fmtSigned(v: Maybe, decimals = 2): string {
  if (!isNum(v)) return DASH;
  const rounded = Number(v.toFixed(decimals));
  const sign = rounded > 0 ? "+" : rounded < 0 ? MINUS : "";
  return sign + group(Math.abs(v), decimals);
}

/** Percent where the input is already in percent units (0.79 -> "+0.79%"). */
export function fmtPct(v: Maybe, decimals = 2, signed = true): string {
  if (!isNum(v)) return DASH;
  return (signed ? fmtSigned(v, decimals) : fmtNumber(v, decimals)) + "%";
}

/** Percent where the input is a fraction (0.55 -> "55%", 0.016 -> "+1.6%"). */
export function fmtFracPct(v: Maybe, decimals = 0, signed = false): string {
  if (!isNum(v)) return DASH;
  return fmtPct(v * 100, decimals, signed);
}

/**
 * Price with decimals chosen by magnitude unless given:
 * >= 10 000 -> 0, >= 1 -> 2, below 1 -> 4.  e.g. 29 356 · 3 291.07 · 9.91
 */
export function priceDecimals(v: number): number {
  const a = Math.abs(v);
  if (a >= 10_000) return 0;
  if (a >= 1) return 2;
  return 4;
}

export function fmtPrice(v: Maybe, decimals?: number): string {
  if (!isNum(v)) return DASH;
  return fmtNumber(v, decimals ?? priceDecimals(v));
}

/** SEK amount: "48 210 SEK". Pass signed for P&L ("+612 SEK"). */
export function fmtSEK(v: Maybe, opts: { decimals?: number; signed?: boolean; unit?: boolean } = {}): string {
  const { decimals = 0, signed = false, unit = true } = opts;
  if (!isNum(v)) return DASH;
  const s = signed ? fmtSigned(v, decimals) : fmtNumber(v, decimals);
  return unit ? `${s} SEK` : s;
}

/** Distance measured in ATR: "−0.28 ATR". */
export function fmtAtr(v: Maybe, decimals = 2): string {
  if (!isNum(v)) return DASH;
  return `${fmtSigned(v, decimals)} ATR`;
}

/** Leverage multiple: "5.6x". */
export function fmtLev(v: Maybe, decimals = 1): string {
  if (!isNum(v)) return DASH;
  return `${fmtNumber(v, decimals)}x`;
}

/** Relative age from minutes: "now", "1m", "15m", "2h", "3d". */
export function fmtAge(minutes: Maybe): string {
  if (!isNum(minutes)) return DASH;
  if (minutes < 1) return "now";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / (60 * 24))}d`;
}

/** Minutes elapsed since an ISO timestamp (null if unparseable). */
export function minutesSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, (now - t) / 60_000);
}

/** Local wall-clock time "16:02" (or "16:02:17" with seconds) from ISO. */
export function fmtClock(iso: string | null | undefined, seconds = false): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: false,
  });
}

/** Sign of a value for colouring: 1, -1 or 0 (0 also for missing). */
export function signOf(v: Maybe): -1 | 0 | 1 {
  if (!isNum(v) || v === 0) return 0;
  return v > 0 ? 1 : -1;
}
