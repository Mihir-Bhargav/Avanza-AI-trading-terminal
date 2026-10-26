"use client";
/**
 * Total value + change for the selected period. Avanza gives period changes,
 * not a value history, so instead of a line this shows what the period is made
 * of: the change per account, and Avanza's best/worst contributors when its
 * insights report covers the period.
 */
import type { ReactNode } from "react";
import type { ApiError, InsightInstrument, PerformancePeriod, PerformanceResponse, PortfolioSummary } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtNumber, fmtPct, fmtSEK, signOf } from "@/lib/format";
import { Eyebrow } from "../Panel";
import { Segmented } from "../Segmented";
import { StateView } from "../StateView";
import { PERIOD_TABS, periodChange, periodPhrase, periodSpan } from "./util";

function toneOf(v: number | null | undefined) {
  const s = signOf(v);
  return s > 0 ? "text-up" : s < 0 ? "text-down" : "text-muted";
}

/** Horizontal bar growing left (negative) or right (positive) from a centre line. */
function DivergingBar({ value, max }: { value: number | null; max: number }) {
  const w = value == null || max <= 0 ? 0 : Math.min(50, (Math.abs(value) / max) * 50);
  return (
    <span aria-hidden="true" className="relative block h-2 flex-1 rounded-[3px] bg-raised">
      <span className="absolute left-1/2 top-[-3px] h-[14px] w-px bg-line-3" />
      {value != null && value !== 0 ? (
        <span
          className={cx("absolute top-0 h-2", value > 0 ? "rounded-r-[3px] bg-up/80" : "rounded-l-[3px] bg-down/80")}
          style={value > 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
        />
      ) : null}
    </span>
  );
}

function AccountBreakdown({ perf }: { perf: PerformanceResponse }) {
  const rows = perf.per_account.filter((a) => a.change != null);
  if (!rows.length)
    return (
      <p className="m-0 text-[13px] leading-[1.5] text-muted">
        {perf.period === "1d"
          ? "Avanza's overview has no per-account figure for today; the total above comes from its insights report."
          : "Avanza reports no per-account change for this period."}
      </p>
    );
  const max = Math.max(...rows.map((a) => Math.abs(a.change as number)));
  return (
    <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
      {rows.map((a) => (
        <li key={a.account} className="flex items-center gap-3 text-[12px]">
          <span className="num w-[76px] shrink-0 text-soft">{a.account}</span>
          <DivergingBar value={a.change} max={max} />
          <span className={cx("num w-[92px] shrink-0 text-right", toneOf(a.change))}>
            {a.change_unit === "SEK" || a.change_unit == null
              ? fmtSEK(a.change, { signed: true, unit: false })
              : `${fmtNumber(a.change, 0)} ${a.change_unit}`}
          </span>
          <span className={cx("num w-[60px] shrink-0 text-right", toneOf(a.change_pct))}>{fmtPct(a.change_pct)}</span>
        </li>
      ))}
    </ul>
  );
}

function ContributorRow({ c, max }: { c: InsightInstrument; max: number }) {
  return (
    <li className="flex items-center gap-3 text-[12px]">
      <span className="min-w-0 flex-1 truncate text-soft" title={c.name}>
        {c.name}
      </span>
      <span aria-hidden="true" className="block h-1.5 w-[70px] shrink-0 overflow-hidden rounded-[3px] bg-raised">
        <span
          className={cx("block h-1.5", (c.outcome_sek ?? 0) >= 0 ? "bg-up/80" : "bg-down/80")}
          style={{ width: `${max > 0 ? Math.min(100, (Math.abs(c.outcome_sek ?? 0) / max) * 100) : 0}%` }}
        />
      </span>
      <span className={cx("num w-[70px] shrink-0 text-right", toneOf(c.outcome_sek))}>
        {fmtSEK(c.outcome_sek, { signed: true, unit: false })}
      </span>
      <span className={cx("num w-[54px] shrink-0 text-right", toneOf(c.outcome_pct))}>{fmtPct(c.outcome_pct, 1)}</span>
    </li>
  );
}

function Contributors({ perf }: { perf: PerformanceResponse }) {
  if (!perf.insights)
    return (
      <p className="m-0 text-[13px] leading-[1.5] text-muted">
        {perf.insights_note ?? "No per-position breakdown for this period."}
      </p>
    );
  const best = (perf.insights.best ?? []).slice(0, 3);
  const worst = (perf.insights.worst ?? []).slice(0, 3);
  if (!best.length && !worst.length)
    return <p className="m-0 text-[13px] text-muted">Avanza&apos;s insights report lists no contributors for this period.</p>;
  const max = Math.max(1, ...[...best, ...worst].map((c) => Math.abs(c.outcome_sek ?? 0)));
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {best.map((c, i) => (
        <ContributorRow key={`b${i}`} c={c} max={max} />
      ))}
      {best.length && worst.length ? <li aria-hidden="true" className="h-px bg-raised" /> : null}
      {worst.map((c, i) => (
        <ContributorRow key={`w${i}`} c={c} max={max} />
      ))}
    </ul>
  );
}

export function ValueHero({
  summary,
  perf,
  perfError,
  period,
  onPeriod,
  onRetryPerf,
}: {
  summary: PortfolioSummary;
  perf: PerformanceResponse | undefined;
  perfError: ApiError | undefined;
  period: PerformancePeriod;
  onPeriod: (p: PerformancePeriod) => void;
  onRetryPerf: () => void;
}) {
  const total = summary.totals_sek.total_value;
  const ch = periodChange(perf, summary);
  const phrase = periodPhrase(period);
  const span = periodSpan(period);
  const nonSek = summary.non_sek_amounts_not_in_totals;

  let changeLine: ReactNode;
  if (perfError && !perf) changeLine = <span className="text-down-soft">Change {span} unavailable</span>;
  else if (!perf) changeLine = <span className="text-faint">Loading change {span}…</span>;
  else if (ch.change == null) changeLine = <span className="text-muted">No change reported {span}</span>;
  else
    changeLine = (
      <span className={toneOf(ch.change)}>
        {fmtSEK(ch.change, { signed: true })}
        {ch.pct != null ? ` (${fmtPct(ch.pct)})` : ""} · {phrase}
        {ch.basis === "insights" ? <span className="text-faint"> · from Avanza insights</span> : null}
      </span>
    );

  return (
    <section
      aria-labelledby="pv-h"
      className="flex flex-col gap-4 rounded-[16px] border border-line bg-surface px-6 pb-5 pt-[22px]"
    >
      <div className="flex items-end gap-6">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 id="pv-h" className="m-0 text-[13px] font-medium text-muted">
            Total value · all accounts
          </h1>
          <span className="font-serif text-[60px] leading-none text-text">
            {total == null ? "—" : fmtNumber(total, 0)} <span className="text-[26px] text-muted">SEK</span>
          </span>
          <span className="num text-sm" aria-live="polite">
            {changeLine}
          </span>
        </div>
        <Segmented
          ariaLabel="Period"
          value={period}
          onChange={onPeriod}
          options={PERIOD_TABS.map(({ value, label, ariaLabel }) => ({ value, label, ariaLabel }))}
          mono
          controls="pv-breakdown"
          className="ml-auto shrink-0"
        />
      </div>

      <div id="pv-breakdown" role="tabpanel" aria-label={`Breakdown, ${phrase}`} className="min-h-[132px] border-t border-raised pt-4">
        {perfError && !perf ? (
          <StateView kind="error" error={perfError} onRetry={onRetryPerf} compact />
        ) : !perf ? (
          <StateView kind="loading" title={`Loading performance ${span}`} compact />
        ) : (
          <div className="grid grid-cols-2 gap-8">
            <div className="flex min-w-0 flex-col gap-3">
              <Eyebrow tone="faint">CHANGE BY ACCOUNT · {phrase.toUpperCase()}</Eyebrow>
              <AccountBreakdown perf={perf} />
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <Eyebrow tone="faint">BIGGEST CONTRIBUTORS · AVANZA INSIGHTS</Eyebrow>
              <Contributors perf={perf} />
            </div>
          </div>
        )}
      </div>

      <p className="m-0 text-[11px] leading-[1.5] text-faint">
        Avanza reports changes per period, not a value history, so no value line is drawn.
        {ch.excluded.length
          ? ` Not in the total: ${ch.excluded.map((e) => `${e.account} ${fmtNumber(e.change, 0)} ${e.unit ?? ""}`.trim()).join(", ")} (not SEK).`
          : ""}
        {nonSek.length ? ` Total value excludes ${nonSek.length} non-SEK amount${nonSek.length > 1 ? "s" : ""}.` : ""}
        {perfError && perf ? " Last refresh failed; showing the previous figures." : ""}
      </p>
    </section>
  );
}
