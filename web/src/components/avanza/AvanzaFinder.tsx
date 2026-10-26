"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { FreshnessBadge } from "@/components/FreshnessBadge";
import { Panel, PanelHeader } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import { Sparkline } from "@/components/markets/Sparkline";
import { avanzaPaths, type FinderResponse, type FinderRow, type InstrumentChart, type InstrumentDetail } from "@/lib/avanza";
import { routes } from "@/lib/commands";
import { DASH, fmtNumber, fmtPct, fmtPrice } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const SUGGESTIONS = ["bull x2 amd", "mini l omx", "bull guld x5", "bear nvda", "mini s sp500"];
/** The house survivability rule: a knock-out barrier inside 3.5 ATR can be hit by ordinary noise. */
const SAFE_ATRS = 3.5;

function spreadText(r: { spread_known?: boolean; spread_pct: number | null }): string {
  if (r.spread_known === false || r.spread_pct == null) return DASH;
  return r.spread_pct > 1000 ? `${r.spread_pct.toExponential(1)}%` : `${r.spread_pct.toFixed(3)}%`;
}

function spreadTone(r: FinderRow): string {
  if (!r.spread_known || r.spread_pct == null) return "text-faint";
  if (r.spread_pct < 0.5) return "text-up";
  if (r.spread_pct < 1.5) return "text-text-2";
  return "text-down";
}

export function AvanzaFinder({ initialQuery }: { initialQuery: string }) {
  const router = useRouter();
  const [draft, setDraft] = useState(initialQuery);
  const [picked, setPicked] = useState<string | null>(null);

  const find = useApi<FinderResponse>(initialQuery ? avanzaPaths.find(initialQuery) : null);
  const rows = find.data?.rows ?? [];
  // The cheapest line is the one you would actually trade, so it opens by default.
  const oid = picked ?? rows[0]?.orderbook_id ?? null;

  function submit(e?: FormEvent, q: string = draft) {
    e?.preventDefault();
    const clean = q.trim().replace(/\s+/g, " ");
    if (clean) router.replace(routes.avanza(clean));
  }

  const dead = rows.filter((r) => r.spread_known && (r.spread_pct ?? 0) > 5).length;
  const unpriced = rows.filter((r) => !r.spread_known).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-lg font-semibold text-text">Avanza finder</h1>
        <span className="font-mono text-[11px] tracking-[0.1em] text-amber">CERTIFICATES · MINIS · CHEAPEST SPREAD FIRST</span>
      </div>

      <form onSubmit={submit} className="flex items-center gap-3" role="search">
        <label className="flex h-11 w-[520px] items-center gap-3 rounded-control border border-line-2 bg-surface px-4">
          <span className="sr-only">Search Avanza instruments</span>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Underlying and product, e.g. bull x2 amd, mini l omx"
            className="flex-1 bg-transparent text-sm text-text outline-none placeholder:text-placeholder"
            autoFocus={!initialQuery}
          />
        </label>
        <button
          type="submit"
          className="h-11 rounded-control bg-amber px-5 text-sm font-semibold text-on-amber hover:bg-amber-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber"
        >
          Search
        </button>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => { setDraft(s); submit(undefined, s); }}
              className="rounded-chip border border-line-2 px-2.5 py-1 font-mono text-xs text-muted hover:text-text"
            >
              {s}
            </button>
          ))}
        </div>
      </form>

      {!initialQuery ? (
        <Panel className="flex-1">
          <StateView
            kind="empty"
            mood="watching"
            title="Search an underlying"
            message="Every certificate and mini on it, ranked by spread. On Avanza Markets the spread is the whole cost above 1,000 SEK, and it ranges from a fraction of a percent to thousands of percent on the same underlying."
          />
        </Panel>
      ) : (
        <div className="flex min-h-0 flex-1 gap-4">
          <Panel className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <PanelHeader
              title="Results"
              tag={initialQuery.toUpperCase()}
              right={
                find.data ? (
                  <span className="text-xs text-muted">
                    {find.data.count} found · cheapest first
                    {dead ? <span className="text-down"> · {dead} untradeably wide</span> : null}
                    {unpriced ? <span className="text-faint"> · {unpriced} unpriced (market closed)</span> : null}
                  </span>
                ) : null
              }
            />
            {find.error ? (
              <StateView kind="error" error={find.error} onRetry={() => find.mutate()} />
            ) : find.isLoading ? (
              <StateView kind="loading" mood="thinking" title="Searching Avanza" />
            ) : rows.length === 0 ? (
              <StateView kind="empty" title="Nothing found" message={`No certificates or minis matched "${initialQuery}". Try the underlying's name, e.g. "bull amd" or "mini l omx".`} />
            ) : (
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-raised">
                    <tr className="font-mono text-[10px] tracking-[0.08em] text-faint">
                      <th className="px-5 py-2 text-left font-normal">INSTRUMENT</th>
                      <th className="px-3 py-2 text-left font-normal">TYPE</th>
                      <th className="px-3 py-2 text-right font-normal">LAST</th>
                      <th className="px-3 py-2 text-right font-normal">TODAY</th>
                      <th className="px-5 py-2 text-right font-normal">SPREAD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const on = r.orderbook_id === oid;
                      return (
                        <tr
                          key={r.orderbook_id}
                          onClick={() => setPicked(r.orderbook_id)}
                          className={`cursor-pointer border-t border-line ${on ? "bg-raised" : "hover:bg-raised/60"}`}
                        >
                          <td className="px-5 py-2.5">
                            <button type="button" onClick={() => setPicked(r.orderbook_id)} className="text-left text-text focus-visible:outline-2 focus-visible:outline-amber">
                              {r.name}
                            </button>
                            <span className="ml-2 font-mono text-[10px] text-faint">{r.orderbook_id}</span>
                          </td>
                          <td className="px-3 py-2.5 font-mono text-xs text-muted">{r.type.toLowerCase()}</td>
                          <td className="px-3 py-2.5 text-right font-mono tabular-nums text-text-2">{fmtPrice(r.last)}</td>
                          <td className={`px-3 py-2.5 text-right font-mono tabular-nums ${(r.change_pct ?? 0) >= 0 ? "text-up" : "text-down"}`}>
                            {fmtPct(r.change_pct)}
                          </td>
                          <td className={`px-5 py-2.5 text-right font-mono tabular-nums ${spreadTone(r)}`}>{spreadText(r)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          <aside className="w-[420px] shrink-0">
            {oid ? <InstrumentPanel oid={oid} /> : null}
          </aside>
        </div>
      )}
      <p className="text-xs text-faint">
        Spread is the whole trading cost on Avanza Markets above 1,000 SEK, so the cheapest line on an underlying is usually the one to use. Read-only: Range never places orders.
      </p>
    </div>
  );
}

function InstrumentPanel({ oid }: { oid: string }) {
  const detail = useApi<InstrumentDetail>(avanzaPaths.instrument(oid), { refreshInterval: 30_000 });
  const chart = useApi<InstrumentChart>(avanzaPaths.chart(oid));
  const d = detail.data;

  if (detail.error || d?.error) {
    return (
      <Panel className="h-full">
        <StateView kind="error" error={detail.error} message={d?.error} onRetry={() => detail.mutate()} />
      </Panel>
    );
  }
  if (!d) {
    return (
      <Panel className="h-full">
        <StateView kind="loading" mood="thinking" title="Loading instrument" />
      </Panel>
    );
  }

  const near = d.atrs_to_barrier != null && d.atrs_to_barrier < SAFE_ATRS;
  const points = chart.data
    ? (chart.data.line.length ? chart.data.line.map((p) => p.value) : chart.data.candles.map((c) => c.close))
    : [];
  const stats: [string, string][] = [
    ["Type", [d.type, d.sub_type].filter(Boolean).join(" · ").replace(/_/g, " ").toLowerCase() || DASH],
    ["Direction", d.direction || DASH],
    ["Leverage", d.leverage != null ? `${fmtNumber(d.leverage, 2)}x` : DASH],
    ["Spread", spreadText(d)],
    ["Bid / ask", d.bid != null && d.ask != null ? `${fmtPrice(d.bid)} / ${fmtPrice(d.ask)}` : DASH],
    ["Financing", d.financing != null ? fmtPrice(d.financing) : DASH],
    ["Parity", d.parity != null ? fmtNumber(d.parity, 0) : DASH],
    ["Currency", d.currency || DASH],
  ];

  return (
    <Panel className="flex h-full flex-col gap-4 overflow-auto" padded>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-text">{d.name}</h2>
          <p className="text-xs text-muted">{d.sub_category || d.category || DASH}</p>
        </div>
        <FreshnessBadge freshness={d.bid == null || d.ask == null ? "closed" : d.is_realtime ? "live" : "delayed"} />
      </div>

      <Link
        href={routes.chart(`AV:${d.orderbook_id}`)}
        className="flex h-10 shrink-0 items-center justify-center rounded-control bg-amber text-sm font-semibold text-on-amber hover:bg-amber-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber"
      >
        Open in chart{d.underlying ? ` · ${d.underlying}` : ""}
      </Link>

      <div className="flex items-baseline gap-3">
        <span className="font-mono text-2xl tabular-nums text-text">{fmtPrice(d.last)}</span>
        <span className={`font-mono text-sm tabular-nums ${(d.change_pct ?? 0) >= 0 ? "text-up" : "text-down"}`}>{fmtPct(d.change_pct)}</span>
      </div>

      <div className="rounded-card bg-rail p-3">
        {chart.error ? (
          <span className="text-xs text-down">Price history unavailable.</span>
        ) : (
          <Sparkline points={points} changePct={d.change_pct} width={372} height={110} />
        )}
        <span className="mt-1 block font-mono text-[10px] text-faint">PRICE HISTORY · AVANZA</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {stats.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <dt className="font-mono text-[10px] tracking-[0.08em] text-faint">{k.toUpperCase()}</dt>
            <dd className="font-mono tabular-nums text-text-2">{v}</dd>
          </div>
        ))}
      </dl>

      <div className={`rounded-card border p-3 text-sm ${d.barrier == null ? "border-line" : near ? "border-down/50 bg-down-soft" : "border-line"}`}>
        <span className="font-mono text-[10px] tracking-[0.08em] text-faint">KNOCK-OUT BARRIER</span>
        {d.barrier == null ? (
          <p className="text-text-2">None reported for this instrument.</p>
        ) : (
          <p className="text-text-2">
            <span className="font-mono tabular-nums">{fmtPrice(d.barrier)}</span>
            {d.barrier_distance_pct != null ? <span> · {fmtNumber(d.barrier_distance_pct, 1)}% away</span> : null}
            {d.atrs_to_barrier != null ? <span> · {fmtNumber(d.atrs_to_barrier, 1)} ATR</span> : null}
          </p>
        )}
        {near ? (
          <p className="mt-1 text-xs text-down">Inside {SAFE_ATRS} ATR: an ordinary day&apos;s move can knock this out before a thesis plays out.</p>
        ) : null}
      </div>

      <div className="text-sm">
        <span className="font-mono text-[10px] tracking-[0.08em] text-faint">UNDERLYING</span>
        {d.underlying ? (
          <p className="text-text-2">
            <span className="font-mono">{d.underlying}</span>
            {d.underlying_price != null ? <span className="font-mono tabular-nums"> · {fmtPrice(d.underlying_price)}</span> : null}
            {" · "}
            <Link href={routes.chart(d.underlying)} className="text-amber hover:text-amber-hover">Open chart →</Link>
          </p>
        ) : (
          <p className="text-muted">Not resolved to a ticker{d.sub_category ? ` (${d.sub_category})` : ""}, so no ATR or barrier distance.</p>
        )}
      </div>
    </Panel>
  );
}
