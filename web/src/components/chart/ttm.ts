/**
 * Plain-language readings of a TTM Power Range setups row. Every sentence is
 * built from the row's own numbers (no LLM, nothing invented), and a missing
 * number reads as "—" rather than a guess.
 */
import type { ChipTone } from "@/components/Chip";
import type { HistBlock, SetupRow, SetupState } from "@/lib/api";
import { fmtFracPct, fmtNumber, fmtPct } from "@/lib/format";
import { exchangeTz, isoDateInTz } from "./chartUtils";

export const STATE_LABEL: Record<SetupState, string> = {
  crossed_z1_up: "Crossed Z1 ↑",
  crossed_z3_down: "Crossed Z3 ↓",
  at_z1: "At Z1",
  at_z3: "At Z3",
  near_z1: "Near Z1",
  near_z3: "Near Z3",
  inside: "Inside range",
};

export function stateTone(s: SetupState): ChipTone {
  return s.startsWith("crossed") ? "amber" : "neutral";
}

/** Which zone the row is about. Inside the range: whichever edge is closer. */
export function zoneSide(r: SetupRow): "z1" | "z3" {
  if (r.state.endsWith("z1") || r.state === "crossed_z1_up") return "z1";
  if (r.state.endsWith("z3") || r.state === "crossed_z3_down") return "z3";
  const d1 = r.dist_z1_atr ?? -Infinity;
  const d3 = r.dist_z3_atr ?? -Infinity;
  return d1 >= d3 ? "z1" : "z3";
}

/** Signed distance for the relevant zone: positive = through it, negative = still inside by that many ATR. */
export function relevantDist(r: SetupRow): number | null {
  return zoneSide(r) === "z1" ? r.dist_z1_atr : r.dist_z3_atr;
}

export function relevantHist(r: SetupRow): HistBlock {
  return zoneSide(r) === "z1" ? r.hist.z1_up : r.hist.z3_dn;
}

/** What a "win" means for this side: z1 = closed higher 3 days later, z3 = closed lower. */
export function winWord(r: SetupRow) {
  return zoneSide(r) === "z1" ? "closed higher" : "closed lower";
}

export function stateSentence(r: SetupRow): string {
  const d = relevantDist(r);
  const abs = d == null ? "—" : fmtNumber(Math.abs(d), 2);
  const zone = zoneSide(r) === "z1" ? "Z1" : "Z3";
  const trend = r.with_trend ? "with trend" : `against the ${r.trend === "up" ? "up" : "down"}trend`;
  switch (r.state) {
    case "crossed_z1_up":
    case "crossed_z3_down":
      return `Crossed ${zone} ${trend} · ${abs} ATR through`;
    case "at_z1":
    case "at_z3":
      return `At ${zone} ${trend} · ${abs} ATR from the edge`;
    case "near_z1":
    case "near_z3":
      return `Near ${zone} · ${abs} ATR short of the zone`;
    default:
      return `Inside the range · ${abs} ATR from ${zone}`;
  }
}

export function historyLine(r: SetupRow): string {
  const h = relevantHist(r);
  if (!h.n) return `History: no ${zoneSide(r) === "z1" ? "Z1" : "Z3"} crosses in two years`;
  return `History: n=${h.n} · ${fmtFracPct(h.win_rate)} ${winWord(r)} · ${fmtFracPct(h.avg_fwd_ret, 1, true)} avg 3d`;
}

/** Longer explanation for the chart card. */
export function stateDetail(r: SetupRow): string {
  const d = relevantDist(r);
  const abs = d == null ? "—" : fmtNumber(Math.abs(d), 2);
  const zoneName = zoneSide(r) === "z1" ? "the upper zone" : "the lower zone";
  const trend = `Trend ${r.trend}: close ${r.trend === "up" ? "above" : "below"} EMA 21 (daily).`;
  if (r.state.startsWith("crossed")) return `${abs} ATR through ${zoneName}. ${trend}`;
  if (r.state.startsWith("at")) return `Within ${abs} ATR of ${zoneName}. ${trend}`;
  if (r.state.startsWith("near")) return `${abs} ATR short of ${zoneName}. ${trend}`;
  return `${abs} ATR from ${zoneName}, the closer edge. ${trend}`;
}

export function stateHeadline(r: SetupRow): string {
  const zone = zoneSide(r) === "z1" ? "Z1" : "Z3";
  if (r.state.startsWith("crossed")) return `Crossed ${zone} ${r.with_trend ? "with trend" : "against trend"}`;
  if (r.state.startsWith("at")) return `At ${zone} ${r.with_trend ? "with trend" : "against trend"}`;
  if (r.state.startsWith("near")) return `Near ${zone}, not crossed`;
  return "Inside the range";
}

/**
 * Kes's note under the TTM card: a rule-based reading of the base rate,
 * earnings and trend alignment. Descriptive only, never an instruction.
 */
export function kesNote(r: SetupRow): string {
  const h = relevantHist(r);
  const parts: string[] = [];
  if (r.earnings_days != null && r.earnings_days <= 7) {
    parts.push(
      `Earnings in ${r.earnings_days} day${r.earnings_days === 1 ? "" : "s"}. ATR is backward-looking and understates a binary print.`,
    );
  }
  if (r.state === "inside") {
    parts.push("Nothing has crossed. The zones are levels to watch, not a setup yet.");
  } else if (!h.n || h.win_rate == null) {
    parts.push("No past crosses of this zone in two years, so there is no base rate to lean on.");
  } else {
    const win = h.win_rate;
    const avg = h.avg_fwd_ret == null ? "—" : fmtPct(h.avg_fwd_ret * 100, 1);
    if (h.n < 25) parts.push(`Small sample (n=${h.n}). Treat the ${fmtFracPct(win)} as a rumour, not evidence.`);
    else if (win >= 0.6) parts.push(`${fmtFracPct(win)} ${winWord(r)} over n=${h.n}. A real lean, still not a promise; average ${avg}.`);
    else if (win >= 0.5)
      parts.push(`Look, don't leap. ${fmtFracPct(win)} is a coin with a slight lean; the average move was ${avg}.`);
    else parts.push(`History leans the other way: only ${fmtFracPct(win)} ${winWord(r)} (n=${h.n}), average ${avg}.`);
    if (!r.with_trend && (r.state.startsWith("crossed") || r.state.startsWith("at")))
      parts.push("This one is against the daily trend.");
  }
  return parts.join(" ");
}

/** The daily bar is from an earlier session than today's in the exchange's zone. */
export function barIsPrevSession(r: SetupRow, nowMs: number | null): boolean {
  if (!r.bar_date || nowMs == null) return false;
  return r.bar_date < isoDateInTz(Math.floor(nowMs / 1000), exchangeTz(r.yahoo));
}

export function shortDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
