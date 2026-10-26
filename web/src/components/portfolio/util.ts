/** Small, pure helpers shared by the portfolio panels. */
import type { PerformancePeriod, PerformanceResponse, PortfolioSummary } from "@/lib/api";

/** `phrase` labels a figure ("+612 SEK · past week"); `span` reads in a sentence ("nothing reported over the past week"). */
export const PERIOD_TABS: { value: PerformancePeriod; label: string; ariaLabel: string; phrase: string; span: string }[] = [
  { value: "1d", label: "1D", ariaLabel: "1 day", phrase: "today", span: "today" },
  { value: "1w", label: "1W", ariaLabel: "1 week", phrase: "past week", span: "over the past week" },
  { value: "1m", label: "1M", ariaLabel: "1 month", phrase: "past month", span: "over the past month" },
  { value: "3m", label: "3M", ariaLabel: "3 months", phrase: "past 3 months", span: "over the past 3 months" },
  { value: "ytd", label: "YTD", ariaLabel: "Year to date", phrase: "this year", span: "this year" },
  { value: "1y", label: "1Y", ariaLabel: "1 year", phrase: "past year", span: "over the past year" },
  { value: "all", label: "ALL", ariaLabel: "Since start", phrase: "since start", span: "since the start" },
];

export const periodPhrase = (p: PerformancePeriod) => PERIOD_TABS.find((t) => t.value === p)?.phrase ?? p;
export const periodSpan = (p: PerformancePeriod) => PERIOD_TABS.find((t) => t.value === p)?.span ?? p;

export interface PeriodChange {
  change: number | null;
  pct: number | null;
  /** Where the figure came from, so the UI can say so. */
  basis: "accounts" | "insights" | null;
  /** Accounts whose change is not in SEK and so is not in the sum. */
  excluded: { account: string; change: number; unit: string | null }[];
}

/**
 * Sum per-account changes, SEK only. The percentage is weighted by each
 * account's implied starting value (change / change_pct), which is the same
 * basis Avanza used for the per-account figure; falls back to
 * current value − change when an account's percentage is missing or zero.
 * 1D has no per-account figure, so the insights total is used instead.
 */
export function periodChange(perf: PerformanceResponse | undefined, summary: PortfolioSummary | undefined): PeriodChange {
  const none: PeriodChange = { change: null, pct: null, basis: null, excluded: [] };
  if (!perf) return none;
  const withChange = perf.per_account.filter((a) => a.change != null);
  const sek = withChange.filter((a) => a.change_unit === "SEK");
  const excluded = withChange
    .filter((a) => a.change_unit !== "SEK")
    .map((a) => ({ account: a.account, change: a.change as number, unit: a.change_unit }));
  if (sek.length) {
    const change = sek.reduce((s, a) => s + (a.change as number), 0);
    let start = 0;
    let ok = true;
    for (const a of sek) {
      const c = a.change as number;
      if (a.change_pct != null && a.change_pct !== 0) start += c / (a.change_pct / 100);
      else {
        const tv = summary?.accounts.find((x) => x.account === a.account)?.total_value;
        if (tv == null) ok = false;
        else start += tv - c;
      }
    }
    return { change, pct: ok && start > 0 ? (change / start) * 100 : null, basis: "accounts", excluded };
  }
  const ins = perf.insights?.total_outcome_sek;
  if (ins != null) return { change: ins, pct: null, basis: "insights", excluded };
  return { ...none, excluded };
}

/** "EXCHANGE_TRADED_FUND" -> "Exchange traded fund". */
export function humanType(t: string | null | undefined): string {
  if (!t) return "Other";
  const s = t.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "2026-09-23" -> "Sep 23" (local). */
export function fmtShortDate(d: string | null | undefined): string {
  if (!d) return "—";
  const t = new Date(d.length === 10 ? `${d}T12:00:00` : d);
  if (Number.isNaN(t.getTime())) return d;
  return t.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

/** Stable colour per instrument type for the allocation bar. */
const TYPE_COLORS: Record<string, string> = {
  FUND: "#5AA9FF",
  STOCK: "#F5A623",
  EXCHANGE_TRADED_FUND: "#8CC4FF",
  CERTIFICATE: "#C38BFF",
  BOND: "#3DD68C",
};
const FALLBACK = ["#8CC4FF", "#C9D1DA", "#B8662F", "#6FCF97"];
export function typeColor(t: string, i: number): string {
  return TYPE_COLORS[t] ?? FALLBACK[i % FALLBACK.length];
}
export const CASH_COLOR = "#5C6773";
