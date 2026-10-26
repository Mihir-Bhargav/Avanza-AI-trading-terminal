"use client";
/**
 * High-profile trades. Tabs:
 *   Insiders · live  SEC Form 4, market-wide, polled from EDGAR (InsidersView)
 *   Congress         STOCK Act reports via Alpha Vantage, per tracked symbol
 *   Funds 13F        well-known funds' quarter-over-quarter 13F changes, SEC EDGAR (FundsView)
 * History and context only: every row is public only after the trade, which
 * the Lag column and Kes's note say out loud.
 */
import { useMemo, useState, type ReactNode } from "react";
import { ApiError, paths, type DisclosureRow, type DisclosureType, type DisclosuresResponse } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtClock } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { Button } from "../Button";
import { FundsView } from "./FundsView";
import { InsidersView } from "./InsidersView";
import { Kes } from "../Kes";
import { Segmented } from "../Segmented";
import { StateView } from "../StateView";

type PageTab = "insiders" | "congress" | "funds";
const TABS: { value: PageTab; label: string }[] = [
  { value: "insiders", label: "Insiders · live" },
  { value: "congress", label: "Congress" },
  { value: "funds", label: "Funds 13F" },
];
const WHO_LABEL: Record<DisclosureType, string> = { congress: "MEMBER", insiders: "INSIDER", funds: "FUND" };
const COLS = "0.8fr 0.8fr 0.55fr 1.9fr 0.75fr 0.55fr 1.15fr 0.6fr";
const LAG_WARN_DAYS = 30;

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const t = new Date(d.length === 10 ? `${d}T12:00:00` : d);
  if (Number.isNaN(t.getTime())) return d;
  return t.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

const OWNER: Record<string, string> = { self: "self", spouse: "spouse", joint: "joint", dependent_child: "child", other: "other" };

function metaLine(r: DisclosureRow, type: DisclosureType): string {
  if (type === "congress") return [r.chamber, r.party, r.owner ? OWNER[r.owner] ?? r.owner : null].filter(Boolean).join(" · ");
  if (type === "insiders") return [r.role, r.security].filter(Boolean).join(" · ");
  return r.role ?? "";
}

function sideClass(side: string | null) {
  return side === "buy" ? "text-up" : side === "sell" ? "text-down" : "text-muted";
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function FilerCard({ who, rows, type }: { who: string | null; rows: DisclosureRow[]; type: DisclosureType }) {
  if (!who)
    return (
      <section aria-label="Selected filer" className="rounded-[14px] border border-line bg-surface px-[18px] py-4 text-[13px] text-muted">
        Select a row to see that filer&apos;s history in the loaded filings.
      </section>
    );
  const mine = rows.filter((r) => r.who === who);
  const first = mine[0];
  const lags = mine.map((r) => r.lag_days).filter((x): x is number => x != null);
  const med = median(lags);
  const counts = new Map<string, number>();
  for (const r of mine) if (r.symbol) counts.set(r.symbol, (counts.get(r.symbol) ?? 0) + 1);
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([s]) => s);
  const buys = mine.filter((r) => r.side === "buy").length;
  const third =
    type === "congress"
      ? { label: "SPOUSE", value: `${mine.filter((r) => r.owner === "spouse").length} / ${mine.length}` }
      : { label: "BUYS", value: `${buys} / ${mine.length}` };
  return (
    <section aria-labelledby="filer-h" className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-[18px] py-4">
      <div className="flex flex-col gap-0.5">
        <h2 id="filer-h" className="m-0 truncate text-[15px] font-semibold text-text">
          {who}
        </h2>
        <span className="text-xs text-muted">
          {[first ? (type === "congress" ? [first.chamber, first.party].filter(Boolean).join(" · ") : first.role) : null, "selected filer"]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <div className="num grid grid-cols-3 gap-2">
        <div className="flex flex-col gap-0.5 rounded-lg bg-rail p-2">
          <span className="text-[10px] text-faint">FILINGS LOADED</span>
          <span className="text-[15px] text-text-2">{mine.length}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-lg bg-rail p-2">
          <span className="text-[10px] text-faint">MEDIAN LAG</span>
          <span className={cx("text-[15px]", med == null ? "text-muted" : med > LAG_WARN_DAYS ? "text-amber" : "text-text-2")}>
            {med == null ? "—" : `${Math.round(med)}d`}
          </span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-lg bg-rail p-2">
          <span className="text-[10px] text-faint">{third.label}</span>
          <span className="text-[15px] text-text-2">{third.value}</span>
        </div>
      </div>
      <span className="text-xs text-muted">
        Most traded: <span className="num text-text-2">{top.length ? top.join(" · ") : "—"}</span>
      </span>
      <span className="text-[11px] leading-[1.45] text-faint">
        Counted from the filings loaded here (tracked symbols only), not the filer&apos;s full record.
        {med == null && type !== "congress" ? " No lag: the source gives no filing date." : ""}
      </span>
    </section>
  );
}

function MostBought({ data }: { data: DisclosuresResponse }) {
  const items = data.most_bought.slice(0, 8);
  const max = Math.max(1, ...items.map((m) => m.count));
  return (
    <section aria-labelledby="most-h" className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-[18px] py-4">
      <div className="flex items-baseline">
        <h2 id="most-h" className="m-0 text-sm font-semibold text-text">
          Most bought
        </h2>
        <span className="num ml-auto text-[10px] tracking-[0.8px] text-faint">
          {data.type.toUpperCase()} · 30 DAYS · BUY FILINGS
        </span>
      </div>
      {items.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items.map((m) => (
            <li key={m.symbol} className="flex items-center gap-2.5 text-xs">
              <span className="num w-12 font-semibold text-text">{m.symbol}</span>
              <span aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-[3px] bg-raised">
                <span className="block h-1.5 bg-zone" style={{ width: `${(m.count / max) * 100}%` }} />
              </span>
              <span className="num w-[22px] text-right text-text-2">{m.count}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[13px] text-muted">No buys filed in the last 30 days for the tracked symbols.</p>
      )}
    </section>
  );
}

/** Skipped symbols grouped by reason, so one budget message isn't repeated per symbol. */
function groupSkipped(data: DisclosuresResponse): [string, string[]][] {
  const by = new Map<string, string[]>();
  for (const s of data.skipped) {
    const why = data.skipped_reasons?.[s] ?? "not loaded";
    by.set(why, [...(by.get(why) ?? []), s]);
  }
  return [...by.entries()];
}

function kesNote(data: DisclosuresResponse): string {
  const lead =
    data.type === "congress"
      ? "These trades happened up to 45 days before anyone could see them."
      : data.type === "insiders"
        ? "Form 4s are due within two business days, but this source gives no filing date, so the delay can't be shown."
        : "13F holdings are quarter-end snapshots, filed up to 45 days later.";
  const held = data.holdings_note
    ? " HELD isn't marked right now, so check overlaps with what you own yourself."
    : " Rows that overlap what you hold are marked HELD.";
  return `${lead} Read them as history and context, not timing.${held}`;
}

export function DisclosuresView({ symbol }: { symbol?: string }) {
  const [tab, setTab] = useState<PageTab>("insiders");
  const header = (
    <>
      <h1 id="disc-h" className="m-0 text-lg font-semibold text-text">
        High-profile trades
      </h1>
      <Segmented ariaLabel="Source" value={tab} onChange={setTab} options={TABS} size="sm" />
    </>
  );
  if (tab === "insiders") return <InsidersView header={header} symbol={symbol} />;
  if (tab === "funds") return <FundsView header={header} symbol={symbol} />;
  return <FilingsView key={tab} type={tab} header={header} symbol={symbol} />;
}

/** Congress (Alpha Vantage). Insiders and Funds have their own SEC views. */
function FilingsView({ type, header, symbol }: { type: Exclude<PageTab, "insiders" | "funds">; header: ReactNode; symbol?: string }) {
  const [onlyMine, setOnlyMine] = useState(false);
  const [filter, setFilter] = useState<string | undefined>(symbol?.toUpperCase());
  const [selected, setSelected] = useState<string | null>(null);
  const { data, error, isLoading, isValidating, mutate } = useApi<DisclosuresResponse>(paths.disclosures(type), {
    swr: { revalidateIfStale: false, shouldRetryOnError: false },
  });

  const rows = useMemo(() => {
    let r = data?.rows ?? [];
    if (onlyMine) r = r.filter((x) => x.yours === "HELD" || x.yours === "WATCH");
    if (filter) r = r.filter((x) => (x.symbol ?? "").toUpperCase() === filter);
    return r;
  }, [data, onlyMine, filter]);

  const notConfigured =
    error instanceof ApiError && error.status === 503 && (error.body as { configured?: boolean } | undefined)?.configured === false;

  if (notConfigured)
    return (
      <div className="flex flex-1 flex-col px-6 py-5">
        <div className="flex flex-1 flex-col rounded-[14px] border border-line bg-surface">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 pb-3.5 pt-4">{header}</div>
          <StateView
            className="flex-1"
            kind="info"
            mood="watching"
            title="Congress filings aren't enabled"
            message={
              <>
                Add ALPHAVANTAGE_API_KEY to .env to enable disclosures (free key at{" "}
                <a href="https://www.alphavantage.co/support/#api-key" target="_blank" rel="noopener noreferrer" className="text-amber">
                  alphavantage.co
                </a>
                ), then restart the backend. Congress filings are public records; the free tier allows 25 requests a day,
                cached per symbol and day. Insiders · live and Funds 13F read the SEC directly and need no key.
              </>
            }
          />
        </div>
      </div>
    );

  const whoSelected = selected && rows.some((r) => r.who === selected) ? selected : (rows[0]?.who ?? null);
  const lagMissing = type !== "congress";

  return (
    <div className="flex min-h-0 flex-1 gap-4 px-6 py-5">
      <section aria-labelledby="disc-h" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[14px] border border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 pb-3.5 pt-4">
          {header}
          <label className="flex cursor-pointer items-center gap-2 text-[13px] text-soft">
            <input
              type="checkbox"
              checked={onlyMine}
              onChange={(e) => setOnlyMine(e.target.checked)}
              className="h-[15px] w-[15px] accent-amber"
            />
            <span>Only my holdings and watchlist</span>
          </label>
          {filter ? (
            <button
              type="button"
              onClick={() => setFilter(undefined)}
              className="num flex h-7 items-center gap-1.5 rounded-chip bg-raised px-2.5 text-xs text-text-2 hover:bg-seg-on"
              aria-label={`Remove the ${filter} filter`}
            >
              {filter} <span aria-hidden="true" className="text-muted">×</span>
            </button>
          ) : null}
          {data ? (
            <span className="num w-full text-[11px] tracking-[0.6px] text-muted">
              <span className="text-faint">RULE · </span>
              {data.rule.toUpperCase()}
            </span>
          ) : null}
        </div>

        {data && (data.partial || data.holdings_note) ? (
          <div className="flex flex-col gap-1 border-t border-line bg-amber/[0.05] px-5 py-2 text-xs leading-[1.45] text-soft" role="status">
            {data.partial ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">PARTIAL</span>
                {data.skipped.length} symbol{data.skipped.length === 1 ? "" : "s"} not loaded.{" "}
                {groupSkipped(data)
                  .map(([why, syms]) => `${syms.join(", ")}: ${why}`)
                  .join(". ")}
                .
              </span>
            ) : null}
            {data.holdings_note ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">HOLDINGS</span>
                {data.holdings_note}.
              </span>
            ) : null}
          </div>
        ) : null}

        <div id="disc-table" role="tabpanel" aria-label={`${TABS.find((t) => t.value === type)?.label} filings`} className="flex min-h-0 flex-1 flex-col">
          {!data ? (
            error ? (
              <StateView kind="error" error={error} onRetry={() => void mutate()} />
            ) : (
              <StateView
                kind="loading"
                title="Fetching filings"
                message="Symbols cached today load instantly; up to ten more are fetched live, within the 25-a-day Alpha Vantage limit."
              />
            )
          ) : (
            <div role="table" aria-label="Filings" className="flex min-h-0 flex-1 flex-col">
              <div
                role="row"
                className="num grid gap-x-3 border-y border-line bg-[#0F1216] px-5 py-2 text-[10px] tracking-[0.9px] text-faint"
                style={{ gridTemplateColumns: COLS }}
              >
                <span role="columnheader">FILED</span>
                <span role="columnheader">TRADED</span>
                <span role="columnheader" className="text-right">
                  LAG
                </span>
                <span role="columnheader">{WHO_LABEL[type]}</span>
                <span role="columnheader">TICKER</span>
                <span role="columnheader">SIDE</span>
                <span role="columnheader" className="text-right">
                  AMOUNT
                </span>
                <span role="columnheader" className="text-right">
                  YOURS
                </span>
              </div>
              <div className={cx("min-h-0 flex-1 overflow-y-auto", isValidating && !isLoading && "opacity-70")}>
                {rows.length === 0 ? (
                  <StateView
                    kind="empty"
                    title={data.rows.length ? "No filings match the filter" : "No filings in the window"}
                    message={
                      data.rows.length
                        ? "Clear the filter to see every loaded filing."
                        : `Nothing filed in the last ${data.window_days ?? 180} days for the ${data.symbols?.length ?? 0} tracked symbols${data.partial ? " that loaded" : ""}.`
                    }
                  />
                ) : (
                  rows.map((r, i) => {
                    const on = r.who != null && r.who === whoSelected;
                    return (
                      <div
                        key={`${r.who}-${r.symbol}-${r.traded}-${i}`}
                        role="row"
                        tabIndex={0}
                        aria-selected={on}
                        onClick={() => setSelected(r.who)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelected(r.who);
                          }
                        }}
                        className={cx(
                          "grid h-11 cursor-pointer items-center gap-x-3 border-b border-raised px-5 text-[13px] transition-colors hover:bg-[#161B22]",
                          on ? "bg-[#171C23]" : r.yours === "HELD" ? "bg-amber/[0.04]" : "",
                        )}
                        style={{ gridTemplateColumns: COLS }}
                      >
                        <span role="cell" className="num text-text-2">
                          {fmtDate(r.filed)}
                        </span>
                        <span role="cell" className="num text-muted">
                          {fmtDate(r.traded)}
                        </span>
                        <span
                          role="cell"
                          className={cx("num text-right", r.lag_days != null && r.lag_days > LAG_WARN_DAYS ? "text-amber" : "text-soft")}
                        >
                          {r.lag_days == null ? "—" : `${r.lag_days}d`}
                        </span>
                        <span role="cell" className="flex min-w-0 flex-col">
                          <span className="truncate text-text">{r.who ?? "—"}</span>
                          <span className="truncate text-[11px] text-faint">{metaLine(r, type)}</span>
                        </span>
                        <span role="cell" className="num font-semibold text-text">
                          {r.symbol ?? "—"}
                        </span>
                        <span role="cell" className={cx("num text-xs", sideClass(r.side))}>
                          {(r.side ?? "—").toUpperCase()}
                        </span>
                        <span role="cell" className="num truncate text-right text-text-2">
                          {r.amount_label ?? "—"}
                        </span>
                        <span
                          role="cell"
                          className={cx(
                            "num text-right text-[11px]",
                            r.yours === "HELD" ? "text-amber" : r.yours === "WATCH" ? "text-zone-text" : "text-[#5C6773]",
                          )}
                        >
                          {r.yours ?? "—"}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-line px-5 py-2.5 text-[11px] leading-[1.5] text-faint">
          Lag is the gap between the trade and the public filing. Amounts are the ranges filers report, not exact sizes.
          {lagMissing ? " Filed and Lag show — when the source publishes no filing date." : ""}{" "}
          Names are as filed in public records.
        </div>
      </section>

      <aside aria-label="Filing context" className="flex w-[360px] shrink-0 flex-col gap-3.5 overflow-y-auto">
        {data ? (
          <>
            <MostBought data={data} />
            <FilerCard who={whoSelected} rows={data.rows} type={type} />
          </>
        ) : null}
        <section aria-label="Kes on disclosures" className="flex gap-3 rounded-[14px] border border-kes-line bg-kes-surface px-4 py-3.5">
          <Kes mood="cautious" size={40} perch="none" className="shrink-0" />
          <div className="flex flex-col gap-1.5">
            <span className="text-[13px] font-semibold text-text">Kes</span>
            <span className="text-[13px] leading-[1.5] text-[#D5DBE2]">
              {data ? kesNote(data) : "Filings are history and context, not timing. They are weeks old by the time they are public."}
            </span>
          </div>
        </section>
        <div className="num mt-auto flex flex-col gap-1.5 text-[11px] leading-[1.5] text-faint">
          <span>Source: STOCK Act periodic transaction reports, via Alpha Vantage (tracked symbols only)</span>
          {data ? (
            <span>
              {data.source} · built {fmtClock(data.as_of)}
              {data.live_fetches != null ? ` · ${data.live_fetches} live fetch${data.live_fetches === 1 ? "" : "es"}` : ""}
              {data.symbols ? ` · ${data.symbols.length} symbols` : ""}
            </span>
          ) : null}
          {data?.budget ? (
            <span className={cx(data.budget.used >= data.budget.limit || data.budget.exhausted ? "text-amber" : "")}>
              Alpha Vantage today: {data.budget.used} of {data.budget.limit} requests used
              {data.budget.exhausted ? " · rate-limited until tomorrow" : ""}
            </span>
          ) : null}
          {data ? (
            <Button variant="text" size="sm" className="self-start" onClick={() => void mutate()} disabled={isValidating}>
              {isValidating ? "Reloading…" : "Reload filings"}
            </Button>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
