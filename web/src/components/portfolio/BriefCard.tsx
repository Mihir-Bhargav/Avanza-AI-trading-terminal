"use client";
/**
 * "Brief · by Kes": the deterministic portfolio brief (portfolio_mcp/brief.py),
 * fetched when the page opens and again only when asked. Every line is
 * computed from account data; no language model is involved.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import type { ApiError, BriefHolding, PortfolioBrief } from "@/lib/api";
import { routes } from "@/lib/commands";
import { cx } from "@/lib/cx";
import { fmtClock, fmtNumber, fmtPct, signOf } from "@/lib/format";
import { Button } from "../Button";
import { Kes } from "../Kes";
import { Eyebrow } from "../Panel";
import { StateView } from "../StateView";
import { fmtShortDate } from "./util";

type FlagLine = { key: string; value: ReactNode; tone: string; name: string; text: string; ticker: string | null };

const tone = (v: number | null | undefined) => {
  const s = signOf(v);
  return s > 0 ? "text-up" : s < 0 ? "text-down" : "text-muted";
};

const isHolding = (x: unknown): x is BriefHolding =>
  typeof x === "object" && x !== null && "name" in x && "value_sek" in x;

/** Turn the brief's flag lists into lines. Unknown flag keys are still shown, by name. */
function flagLines(flags: PortfolioBrief["flags"]): { lines: FlagLine[]; rules: string[] } {
  const lines: FlagLine[] = [];
  const rules: string[] = [];
  for (const [key, items] of Object.entries(flags)) {
    let m: RegExpMatchArray | null;
    if ((m = key.match(/^day_move_over_([\d.]+)pct$/))) {
      rules.push(`no holding moved ${m[1]}% or more today`);
      for (const h of items)
        if (isHolding(h))
          lines.push({
            key: `${key}-${h.name}`,
            value: fmtPct(h.day_change_pct, 1),
            tone: tone(h.day_change_pct),
            name: h.name,
            text: `moved ${m[1]}% or more today`,
            ticker: h.ticker,
          });
    } else if ((m = key.match(/^unrealized_loss_beyond_(-?[\d.]+)pct$/))) {
      const lim = fmtPct(Number(m[1]), 0);
      rules.push(`none is down more than ${lim.replace(/^[+−]/, "")}`);
      for (const h of items)
        if (isHolding(h))
          lines.push({
            key: `${key}-${h.name}`,
            value: fmtPct(h.pnl_pct, 1),
            tone: tone(h.pnl_pct),
            name: h.name,
            text: `unrealized loss beyond ${lim}`,
            ticker: h.ticker,
          });
    } else if ((m = key.match(/^stale_price_over_(\d+)d$/))) {
      rules.push(`no price is older than ${m[1]} days`);
      for (const s of items as { name?: string; age_days?: number | null }[])
        lines.push({
          key: `${key}-${s.name}`,
          value: s.age_days == null ? "AGE ?" : `${s.age_days}d`,
          tone: "text-down-soft",
          name: s.name ?? "Unknown",
          text: s.age_days == null ? "price date unreadable" : `price last updated ${s.age_days} days ago`,
          ticker: null,
        });
    } else {
      rules.push(`nothing flagged as ${key.replace(/_/g, " ")}`);
      for (const x of items)
        lines.push({
          key: `${key}-${JSON.stringify(x).slice(0, 40)}`,
          value: "FLAG",
          tone: "text-amber",
          name: isHolding(x) ? x.name : "Item",
          text: key.replace(/_/g, " "),
          ticker: isHolding(x) ? x.ticker : null,
        });
    }
  }
  return { lines, rules };
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Eyebrow className="mt-1.5">{title}</Eyebrow>
      {children}
    </div>
  );
}

function BriefBody({ brief }: { brief: PortfolioBrief }) {
  const { lines, rules } = flagLines(brief.flags);
  const nameOf = (ticker: string) => brief.holdings.find((h) => h.ticker === ticker)?.name ?? ticker;
  const e = brief.earnings;
  const c = brief.concentration;

  return (
    <>
      <Section title="MOVERS & FLAGS">
        {lines.length ? (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {lines.map((l) => (
              <li key={l.key} className="flex gap-2.5 text-[13px] leading-[1.4]">
                <span className={cx("num w-[58px] shrink-0", l.tone)}>{l.value}</span>
                <span className="min-w-0 text-soft">
                  <span className="font-medium text-text">{l.name}</span> · {l.text}
                  {l.ticker ? (
                    <>
                      {" · "}
                      <Link href={routes.news(l.ticker.split(".")[0])} className="text-amber hover:text-amber-hover">
                        news
                      </Link>
                    </>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-[13px] leading-[1.45] text-soft">
            Nothing flagged: {rules.length ? rules.join(", ") : "no flag rules were reported"}.
          </p>
        )}
      </Section>

      <Section title={`EARNINGS AHEAD · ${e.within_days}D`}>
        {e.upcoming.length ? (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px]">
            {e.upcoming.map((u) => (
              <li key={u.ticker} className="flex justify-between gap-3">
                <span className="truncate text-text-2">
                  {nameOf(u.ticker)} <span className="num text-[11px] text-faint">{u.ticker}</span>
                </span>
                <span className={cx("num shrink-0", u.days_until <= 7 ? "text-down-soft" : "text-muted")}>
                  {u.days_until === 0 ? "today" : `in ${u.days_until} day${u.days_until === 1 ? "" : "s"}`} · {fmtShortDate(u.date)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-[13px] text-soft">
            {e.checked.length
              ? `None of the ${e.checked.length} stock${e.checked.length === 1 ? "" : "s"} checked reports within ${e.within_days} days.`
              : "No stock holdings to check."}
          </p>
        )}
        {e.lookup_failed.length ? (
          <p className="m-0 text-xs leading-[1.45] text-warn-text">
            Earnings lookup failed for {e.lookup_failed.join(", ")}. Check those dates yourself before holding through a print.
          </p>
        ) : null}
        {e.unmapped_stocks.length ? (
          <p className="m-0 text-xs leading-[1.45] text-warn-text">
            No ticker mapped for {e.unmapped_stocks.join(", ")}, so earnings were not checked.
          </p>
        ) : null}
      </Section>

      <Section title="CONCENTRATION">
        <p className="m-0 text-[13px] leading-[1.45] text-soft">
          Top holding <span className="num text-text-2">{c.top1_pct_of_invested == null ? "—" : `${fmtNumber(c.top1_pct_of_invested, 1)}%`}</span> of
          invested · top three <span className="num text-text-2">{c.top3_pct_of_invested == null ? "—" : `${fmtNumber(c.top3_pct_of_invested, 1)}%`}</span>
          {brief.totals_sek.cash_pct != null ? (
            <>
              {" "}
              · cash <span className="num text-text-2">{fmtNumber(brief.totals_sek.cash_pct, 1)}%</span> of portfolio
            </>
          ) : null}
        </p>
      </Section>
    </>
  );
}

export function BriefCard({
  brief,
  error,
  validating,
  onRefresh,
}: {
  brief: PortfolioBrief | undefined;
  error: ApiError | undefined;
  validating: boolean;
  onRefresh: () => void;
}) {
  const asOf = brief?.as_of;
  return (
    <section aria-labelledby="brief-h" className="flex flex-col gap-2.5 rounded-[16px] border border-line bg-surface px-5 py-[18px]">
      <div className="flex items-center gap-2.5">
        <Kes mood={validating ? "thinking" : error && !brief ? "alert" : "watching"} size={30} perch="none" />
        <div className="flex min-w-0 flex-col">
          <h2 id="brief-h" className="m-0 whitespace-nowrap text-sm font-semibold text-text">
            Brief · by Kes
          </h2>
          <span className="num whitespace-nowrap text-[11px] text-muted" aria-live="polite">
            {validating ? "working…" : asOf ? `on request · ${fmtClock(asOf)}` : "on request"}
          </span>
        </div>
        <Button variant="outline" size="sm" className="ml-auto" onClick={onRefresh} disabled={validating}>
          Refresh brief
        </Button>
      </div>

      {brief ? (
        <>
          {error ? (
            <p role="alert" className="m-0 text-xs text-warn-text">
              Refresh failed ({error.message}). Showing the brief from {fmtClock(asOf)}.
            </p>
          ) : null}
          <BriefBody brief={brief} />
        </>
      ) : error ? (
        <StateView kind="error" error={error} onRetry={onRefresh} compact />
      ) : (
        <StateView kind="loading" title="Putting the brief together" message="Earnings dates are looked up per stock; this can take a few seconds." compact />
      )}

      <p className="m-0 mt-2 text-[11px] leading-[1.5] text-muted">
        Every figure is computed from your account data, not written by a model.
      </p>
    </section>
  );
}
