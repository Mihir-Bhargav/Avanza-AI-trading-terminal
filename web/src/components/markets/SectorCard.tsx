/**
 * One sector, Finviz-hover-card style: name + day move, the headline for its
 * biggest mover, then each leader with sparkline, last and % change. Rows link
 * to the chart page.
 */
import Link from "next/link";
import type { Freshness } from "@/lib/api";
import { routes } from "@/lib/commands";
import { cx } from "@/lib/cx";
import { fmtAge, fmtPct, fmtPrice } from "@/lib/format";
import type { SectorMember, SectorOverview } from "@/lib/markets";
import { Num } from "../Num";
import { Sparkline } from "./Sparkline";

const safeUrl = (u: string | null) => (u && /^https?:\/\//i.test(u) ? u : null);
const label = (sym: string) => sym.replace(/\.ST$/i, "");

const FLAG: Partial<Record<Freshness, { text: string; cls: string }>> = {
  stale: { text: "STALE", cls: "bg-down/12 text-down-soft" },
  unknown: { text: "NO DATA", cls: "bg-raised text-muted" },
};

function MemberRow({ m, expected }: { m: SectorMember; expected: Freshness }) {
  const flag = m.freshness !== expected ? FLAG[m.freshness] : undefined;
  const aria = `${m.name} (${label(m.symbol)}): ${m.last != null ? fmtPrice(m.last) : "no price"}, ${
    m.change_pct != null ? fmtPct(m.change_pct) : "change unknown"
  } today. Open chart.`;
  return (
    <li>
      <Link
        href={routes.chart(m.symbol)}
        aria-label={aria}
        title={m.error ? `${m.name}: ${m.error}` : `${m.name}${m.age_min != null ? ` · last bar ${fmtAge(m.age_min)} old` : ""}`}
        className="grid h-9 grid-cols-[56px_minmax(0,1fr)_60px_66px_58px] items-center gap-2.5 rounded-lg px-2 transition-colors hover:bg-raised focus-visible:bg-raised"
      >
        <span className="num truncate text-[12px] font-medium text-text">{label(m.symbol)}</span>
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[12px] text-faint">{m.name}</span>
          {flag ? <span className={cx("num shrink-0 rounded-[4px] px-1 py-px text-[9px] tracking-[0.6px]", flag.cls)}>{flag.text}</span> : null}
        </span>
        <Sparkline points={m.spark} changePct={m.change_pct} width={60} />
        <Num value={m.last} kind="price" className="text-right text-[12px] text-text-2" />
        <Num value={m.change_pct} kind="pct" colored className="text-right text-[12px]" />
      </Link>
    </li>
  );
}

export function SectorCard({ s, expected }: { s: SectorOverview; expected: Freshness }) {
  const id = `sector-${s.sector.replace(/\W+/g, "-").toLowerCase()}`;
  const href = safeUrl(s.headline?.url ?? null);
  const basis =
    s.change_basis === "etf"
      ? `${s.etf} sector ETF${s.etf_quote?.last != null ? ` at ${fmtPrice(s.etf_quote.last)}` : ""}`
      : `Equal-weighted average of the ${s.members.length} listed members`;
  const tint = s.change_pct == null || s.change_pct === 0 ? "bg-line-3" : s.change_pct > 0 ? "bg-up" : "bg-down";

  return (
    <article aria-labelledby={id} className="relative flex flex-col overflow-hidden rounded-panel border border-line bg-surface">
      <span aria-hidden="true" className={cx("absolute inset-y-0 left-0 w-[3px] opacity-80", tint)} />
      <header className="flex items-baseline gap-2.5 px-4 pb-2 pt-3.5">
        <h3 id={id} className="m-0 truncate text-[15px] font-semibold text-text">
          {s.sector}
        </h3>
        <span className="num shrink-0 text-[10px] tracking-[0.8px] text-faint" title={basis}>
          {s.change_basis === "etf" ? s.etf : "AVG"}
        </span>
        <span className="ml-auto" title={basis}>
          <Num value={s.change_pct} kind="pct" colored className="text-[17px] font-medium" />
        </span>
      </header>

      <div className="mx-4 mb-2 min-h-[40px] border-b border-raised pb-2.5">
        {s.headline ? (
          <>
            <p className="m-0 truncate text-[13px] leading-[1.35] text-text-2" title={s.headline.title}>
              {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer" className="text-text-2 hover:text-amber-hover hover:underline">
                  {s.headline.title}
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              ) : (
                s.headline.title
              )}
            </p>
            <p className="num m-0 mt-1 truncate text-[10.5px] tracking-[0.3px] text-faint">
              <span className="text-amber">{label(s.headline.symbol)}</span>
              {" · "}
              {s.headline.source || "unknown source"}
              {" · "}
              {s.headline.age_min != null ? `${fmtAge(s.headline.age_min)} ago` : "age unknown"}
            </p>
          </>
        ) : s.headline_error ? (
          <p className="m-0 text-[12px] leading-[1.4] text-warn-text" role="status">
            Headline lookup for {s.top_mover ? label(s.top_mover) : "the top mover"} failed: {s.headline_error}
          </p>
        ) : (
          <p className="m-0 text-[12px] leading-[1.4] text-faint">
            {s.top_mover
              ? `No headline naming ${label(s.top_mover)}, the sector's biggest mover, in the last 48 h.`
              : "No mover to look up: no member has a price change yet."}
          </p>
        )}
      </div>

      <ul className="m-0 flex list-none flex-col px-2 pb-2.5 pt-0">
        {s.members.map((m) => (
          <MemberRow key={m.symbol} m={m} expected={expected} />
        ))}
      </ul>
    </article>
  );
}
