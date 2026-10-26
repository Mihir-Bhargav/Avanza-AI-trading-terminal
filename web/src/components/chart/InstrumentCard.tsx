/**
 * Right-panel card when the chart was opened for an Avanza certificate/mini:
 * what the instrument itself is (leverage, spread, barrier risk), while the
 * chart beside it shows the underlying it is priced from.
 */
import Link from "next/link";
import { FreshnessBadge } from "@/components/FreshnessBadge";
import { Panel } from "@/components/Panel";
import type { InstrumentDetail } from "@/lib/avanza";
import { routes } from "@/lib/commands";
import { DASH, fmtNumber, fmtPct, fmtPrice } from "@/lib/format";

/** The house survivability rule: a barrier inside 3.5 ATR can be hit by ordinary noise. */
const SAFE_ATRS = 3.5;

export function InstrumentCard({ d, ownHistory }: { d: InstrumentDetail; ownHistory: boolean }) {
  const near = d.atrs_to_barrier != null && d.atrs_to_barrier < SAFE_ATRS;
  const spread = d.spread_pct == null ? "market closed" : `${d.spread_pct.toFixed(3)}%`;
  const rows: [string, string][] = [
    ["Leverage", d.leverage != null ? `${fmtNumber(d.leverage, 2)}x` : DASH],
    ["Spread", spread],
    ["Bid / ask", d.bid != null && d.ask != null ? `${fmtPrice(d.bid)} / ${fmtPrice(d.ask)}` : DASH],
    ["Financing", d.financing != null ? fmtPrice(d.financing) : DASH],
  ];

  return (
    <Panel padded className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] tracking-[0.1em] text-amber">AVANZA INSTRUMENT</span>
        {/* No quotes means the market maker is off: the last price is a closing print, not live. */}
        <FreshnessBadge freshness={d.bid == null || d.ask == null ? "closed" : d.is_realtime ? "live" : "delayed"} />
      </div>
      <span className="text-base font-semibold text-text">{d.name}</span>
      <div className="flex items-baseline gap-2.5">
        <span className="font-mono text-xl tabular-nums text-text">{fmtPrice(d.last)}</span>
        <span className={`font-mono text-sm tabular-nums ${(d.change_pct ?? 0) >= 0 ? "text-up" : "text-down"}`}>{fmtPct(d.change_pct)}</span>
        <span className="text-xs text-faint">{d.currency}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <dt className="font-mono text-[10px] tracking-[0.08em] text-faint">{k.toUpperCase()}</dt>
            <dd className="font-mono tabular-nums text-text-2">{v}</dd>
          </div>
        ))}
      </dl>
      <div className={`rounded-card border p-2.5 text-sm ${near ? "border-down/50 bg-down-soft" : "border-line"}`}>
        <span className="font-mono text-[10px] tracking-[0.08em] text-faint">KNOCK-OUT BARRIER</span>
        {d.barrier == null ? (
          <p className="text-text-2">None reported.</p>
        ) : (
          <p className="text-text-2">
            <span className="font-mono tabular-nums">{fmtPrice(d.barrier)}</span>
            {d.barrier_distance_pct != null ? ` · ${fmtNumber(d.barrier_distance_pct, 1)}% away` : ""}
            {d.atrs_to_barrier != null ? ` · ${fmtNumber(d.atrs_to_barrier, 1)} ATR` : ""}
          </p>
        )}
        {near ? <p className="mt-1 text-xs text-down">Inside {SAFE_ATRS} ATR: an ordinary day&apos;s move can knock this out.</p> : null}
      </div>
      <p className="text-xs leading-relaxed text-muted">
        {ownHistory
          ? "Underlying not identified, so this is the instrument's own history: daily, and only on days a trade printed."
          : "The chart shows the underlying, since Avanza only records this instrument's price when a trade prints. Barrier and financing are in the levels ladder."}
      </p>
      <Link href={routes.avanza()} className="text-xs text-amber hover:text-amber-hover">Back to Avanza finder →</Link>
    </Panel>
  );
}
