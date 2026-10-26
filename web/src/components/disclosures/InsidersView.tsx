"use client";
/**
 * Insiders · live: market-wide open-market buys and sells by CEOs, CFOs,
 * directors and 10% owners, straight from SEC Form 4 filings. The backend
 * polls EDGAR every ~2 minutes; this view re-reads /api/insiders every 60 s.
 */
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, paths, type InsiderRow, type InsidersQuery, type InsidersResponse } from "@/lib/api";
import { cx } from "@/lib/cx";
import { DASH, fmtNumber, fmtPrice, minutesSince } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { Button } from "../Button";
import { Kes } from "../Kes";
import { Segmented } from "../Segmented";
import { StateView } from "../StateView";

type Side = "buy" | "sell" | "all";
type MinKey = "any" | "100k" | "1m" | "10m";

const SIDES: { value: Side; label: string }[] = [
  { value: "buy", label: "Buys" },
  { value: "sell", label: "Sells" },
  { value: "all", label: "All" },
];
const MINS: { value: MinKey; label: string; ariaLabel: string }[] = [
  { value: "any", label: "Any", ariaLabel: "Any size" },
  { value: "100k", label: "$100K+", ariaLabel: "At least 100 thousand dollars" },
  { value: "1m", label: "$1M+", ariaLabel: "At least 1 million dollars" },
  { value: "10m", label: "$10M+", ariaLabel: "At least 10 million dollars" },
];
const MIN_VALUE: Record<MinKey, number | undefined> = { any: undefined, "100k": 100_000, "1m": 1_000_000, "10m": 10_000_000 };
const COLS = "100px minmax(0,1.5fr) minmax(0,1.9fr) 40px minmax(0,1.25fr) 80px 44px";
const POLL_MS = 60_000;

/** "$1.2M", "$350K", "$4.1B". */
export function fmtUsdCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  // Thresholds sit just below each unit so 999 999 reads "$1.0M", not "$1000K".
  if (a >= 999.5e6) return `$${(v / 1e9).toFixed(a >= 9.95e9 ? 0 : 1)}B`;
  if (a >= 999.5e3) return `$${(v / 1e6).toFixed(a >= 9.95e6 ? 0 : 1)}M`;
  if (a >= 999.5) return `$${Math.round(v / 1e3)}K`;
  return `$${Math.round(v)}`;
}

function ago(iso: string | null | undefined, now: number): string {
  const m = minutesSince(iso, now);
  if (m == null) return DASH;
  if (m < 1) return "just now";
  if (m < 60) return `${Math.round(m)} min ago`;
  if (m < 60 * 24) return `${Math.round(m / 60)} h ago`;
  const d = Math.round(m / (60 * 24));
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

function fullTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-GB", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function shortDate(d: string | null): string {
  if (!d) return DASH;
  const t = new Date(`${d}T12:00:00`);
  return Number.isNaN(t.getTime()) ? d : t.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

function fmtShares(n: number | null): string {
  if (n == null) return DASH;
  if (Math.abs(n) >= 1e6) return `${fmtNumber(n / 1e6, 2)}M`;
  return fmtNumber(n, Math.abs(n) % 1 ? 2 : 0);
}

function Badge({ tone, title, children }: { tone: "amber" | "zone" | "neutral" | "plan"; title?: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className={cx(
        "num inline-flex h-[18px] items-center rounded-[5px] px-1.5 text-[9.5px] font-semibold tracking-[0.6px]",
        tone === "amber" && "bg-amber/14 text-amber",
        tone === "zone" && "bg-zone/14 text-zone-text",
        tone === "neutral" && "bg-raised text-soft",
        tone === "plan" && "border border-line text-faint",
      )}
    >
      {children}
    </span>
  );
}

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-[13px] text-soft">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-[15px] w-[15px] accent-amber" />
      <span>{children}</span>
    </label>
  );
}

function Row({ r, now }: { r: InsiderRow; now: number }) {
  const buy = r.side === "BUY";
  return (
    <div
      role="row"
      className={cx(
        "relative grid min-h-[52px] items-center gap-x-3 border-b border-raised px-5 py-1.5 text-[13px] transition-colors hover:bg-[#161B22]",
        r.notable && (buy ? "bg-up/[0.045]" : "bg-amber/[0.035]"),
      )}
      style={{ gridTemplateColumns: COLS }}
    >
      {r.notable ? (
        <span aria-hidden="true" className={cx("absolute inset-y-1.5 left-0 w-[3px] rounded-r", buy ? "bg-up" : "bg-amber")} />
      ) : null}
      <span
        role="cell"
        className="flex min-w-0 flex-col"
        title={`Filed ${fullTime(r.filed_at)}${r.lag_days != null ? ` · ${r.lag_days} day${r.lag_days === 1 ? "" : "s"} after the trade` : ""}`}
      >
        <span className="num whitespace-nowrap text-text-2">{ago(r.filed_at, now)}</span>
        <span className={cx("num whitespace-nowrap text-[11px]", r.lag_days != null && r.lag_days > 2 ? "text-amber" : "text-faint")}>
          traded {shortDate(r.trade_date)}
        </span>
      </span>
      <span role="cell" className="flex min-w-0 flex-col">
        <span className="flex items-center gap-1.5">
          {r.ticker ? (
            <Link
              href={`/terminal/chart/${encodeURIComponent(r.ticker)}`}
              className="num font-semibold text-text hover:text-amber hover:underline"
              title={`Open the ${r.ticker} chart`}
            >
              {r.ticker}
            </Link>
          ) : (
            <span className="num text-muted" title="No ticker in the filing (often a private fund)">
              {DASH}
            </span>
          )}
          {r.yours ? <Badge tone={r.yours === "HELD" ? "amber" : "zone"}>{r.yours}</Badge> : null}
        </span>
        <span className="truncate text-[11px] text-muted" title={r.issuer ?? undefined}>
          {r.issuer ?? DASH}
        </span>
      </span>
      <span role="cell" className="flex min-w-0 flex-col">
        <span className="truncate text-text" title={r.who ?? undefined}>
          {r.who ?? DASH}
        </span>
        <span className={cx("truncate text-[11px]", r.is_ceo_like ? "text-text-2" : "text-faint")} title={r.role ?? undefined}>
          {r.role ?? DASH}
        </span>
      </span>
      <span role="cell" className={cx("num text-xs font-semibold", buy ? "text-up" : "text-down")}>
        {r.side}
      </span>
      <span role="cell" className="flex min-w-0 flex-col items-end">
        <span className={cx("num font-semibold", r.notable ? (buy ? "text-up" : "text-amber") : "text-text-2")}>{fmtUsdCompact(r.value)}</span>
        <span className="num max-w-full truncate text-[11px] text-faint">
          {fmtShares(r.shares)} × {r.price != null ? `$${fmtPrice(r.price)}` : "no price"}
        </span>
      </span>
      <span role="cell" className="flex flex-wrap items-center justify-end gap-1">
        {r.notable ? <Badge tone={buy ? "zone" : "amber"}>NOTABLE</Badge> : null}
        {r.plan_10b5_1 ? (
          <Badge
            tone="plan"
            title="Filed as part of a pre-arranged Rule 10b5-1 trading plan: scheduled in advance, so it says little about the insider's current view."
          >
            10b5-1
          </Badge>
        ) : null}
      </span>
      <span role="cell" className="text-right">
        <a
          href={r.sec_url}
          target="_blank"
          rel="noopener noreferrer"
          className="num whitespace-nowrap text-xs text-muted hover:text-amber"
          aria-label={`SEC filing for ${r.who ?? "this insider"} in ${r.ticker ?? r.issuer ?? "this company"} (opens in a new tab)`}
        >
          SEC ↗
        </a>
      </span>
    </div>
  );
}

function TopBuys({ data }: { data: InsidersResponse }) {
  const items = data.top_buys.slice(0, 8);
  const max = Math.max(1, ...items.map((m) => m.value));
  return (
    <section aria-labelledby="topbuys-h" className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-[18px] py-4">
      <div className="flex items-baseline">
        <h2 id="topbuys-h" className="m-0 text-sm font-semibold text-text">
          Biggest insider buys this week
        </h2>
        <span className="num ml-auto shrink-0 pl-2 text-[10px] tracking-[0.8px] text-faint">7 DAYS</span>
      </div>
      {items.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items.map((m) => (
            <li key={m.ticker} className="flex items-center gap-2.5 text-xs" title={m.issuer ?? undefined}>
              <Link href={`/terminal/chart/${encodeURIComponent(m.ticker)}`} className="num w-12 truncate font-semibold text-text hover:text-amber">
                {m.ticker}
              </Link>
              <span aria-hidden="true" className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-[3px] bg-raised">
                <span className="block h-1.5 bg-up/70" style={{ width: `${Math.max(2, (m.value / max) * 100)}%` }} />
              </span>
              <span className="num w-[52px] text-right text-text-2">{fmtUsdCompact(m.value)}</span>
              <span className="num w-[58px] whitespace-nowrap text-right text-[11px] text-faint">
                {m.buyers} buyer{m.buyers === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[13px] text-muted">
          {data.backfilling ? "Still reading recent filings…" : "No open-market insider buys in the filings read so far this week."}
        </p>
      )}
    </section>
  );
}

function PollStatus({ data, now }: { data: InsidersResponse; now: number }) {
  const stale = (minutesSince(data.last_poll, now) ?? 0) > (data.poll_seconds / 60) * 3;
  return (
    <section aria-label="SEC feed status" className="flex flex-col gap-1.5 rounded-[14px] border border-line bg-surface px-[18px] py-3.5 text-xs">
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={cx("h-2 w-2 rounded-full", data.poll_error || stale ? "bg-amber" : data.backfilling ? "bg-zone" : "bg-up")}
        />
        <span className="text-text-2">
          {data.backfilling ? "Backfilling · " : ""}
          {data.last_poll ? `SEC feed polled ${ago(data.last_poll, now)}` : "First SEC poll in progress"}
          <span className="text-faint"> · {fmtNumber(data.filings_seen, 0)} filings seen</span>
        </span>
      </div>
      {data.poll_error ? <span className="text-warn-text">Last poll failed: {data.poll_error}</span> : null}
      {stale && !data.poll_error ? <span className="text-amber">No successful poll for a while; rows may be behind.</span> : null}
      {data.parse_failures ? (
        <span className="text-faint" title={data.last_parse_failure ?? undefined}>
          {data.parse_failures} filing{data.parse_failures === 1 ? "" : "s"} could not be parsed this session.
        </span>
      ) : null}
      {data.store_error ? <span className="text-warn-text">{data.store_error}</span> : null}
      <span className="num text-[11px] text-faint">
        Polls every {Math.round(data.poll_seconds / 60)} min · page refreshes every minute
        {data.feed_updated ? ` · feed built ${ago(data.feed_updated, now)}` : ""}
      </span>
    </section>
  );
}

function KesNote({ data }: { data?: InsidersResponse }) {
  const held = data?.holdings_note ? " HELD isn't marked right now, so check overlaps with what you own yourself." : "";
  return (
    <section aria-label="Kes on insider trades" className="flex gap-3 rounded-[14px] border border-kes-line bg-kes-surface px-4 py-3.5">
      <Kes mood="cautious" size={40} perch="none" className="shrink-0" />
      <div className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-text">Kes</span>
        <span className="text-[13px] leading-[1.5] text-[#D5DBE2]">
          This is history and context, not timing: the trade already happened, sometimes days before the filing. An open-market buy with
          the insider&apos;s own money is the strongest signal here. A sale under a pre-arranged 10b5-1 plan is the weakest; it was
          scheduled months ago.{held}
        </span>
      </div>
    </section>
  );
}

export function InsidersView({ header, symbol }: { header: ReactNode; symbol?: string }) {
  const [side, setSide] = useState<Side>("buy");
  const [minKey, setMinKey] = useState<MinKey>("100k");
  const [ceoOnly, setCeoOnly] = useState(false);
  const [mine, setMine] = useState(false);
  const [notableOnly, setNotableOnly] = useState(false);
  const [filter, setFilter] = useState<string | undefined>(symbol?.toUpperCase());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const query: InsidersQuery = useMemo(
    () => ({ days: 7, side, min_value: MIN_VALUE[minKey], ceo_only: ceoOnly, mine, notable_only: notableOnly, symbols: filter }),
    [side, minKey, ceoOnly, mine, notableOnly, filter],
  );
  const { data, error, isLoading, isValidating, mutate } = useApi<InsidersResponse>(paths.insiders(query), {
    refreshInterval: POLL_MS,
    swr: { keepPreviousData: true },
  });

  const notConfigured =
    error instanceof ApiError && error.status === 503 && (error.body as { configured?: boolean } | undefined)?.configured === false;

  const body = (() => {
    if (notConfigured)
      return (
        <StateView
          kind="info"
          mood="watching"
          title="The SEC feed isn't enabled"
          message={
            <>
              Add <span className="num text-text-2">SEC_USER_AGENT=&quot;Range Terminal you@example.com&quot;</span> to .env and restart
              the backend. The SEC asks every automated reader to identify itself with a contact address; nothing else is needed, and the
              data is free.
            </>
          }
        />
      );
    if (!data)
      return error ? (
        <StateView kind="error" error={error} onRetry={() => void mutate()} />
      ) : (
        <StateView kind="loading" title="Reading SEC filings" />
      );
    if (!data.rows.length && data.backfilling)
      return (
        <StateView
          kind="loading"
          title="Backfilling from the SEC"
          message={`Reading the latest Form 4 filings, about three a second to stay inside the SEC's limits. ${fmtNumber(data.filings_seen, 0)} read so far; matching trades appear as they are found.`}
        />
      );
    if (!data.rows.length)
      return (
        <StateView
          kind="empty"
          title="No trades match these filters"
          message={`Nothing in the last ${data.window_days} days of filings read so far. Try a lower size, "All", or clear the other filters.`}
        />
      );
    return data.rows.map((r) => <Row key={r.id} r={r} now={now} />);
  })();

  return (
    <div className="flex min-h-0 flex-1 gap-4 px-6 py-5">
      <section aria-labelledby="disc-h" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[14px] border border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5 px-5 pb-3.5 pt-4">
          {header}
          <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-2">
            <Segmented ariaLabel="Side" value={side} onChange={setSide} options={SIDES} size="sm" controls="ins-table" />
            <Segmented ariaLabel="Minimum value" value={minKey} onChange={setMinKey} options={MINS} size="sm" mono controls="ins-table" />
            <Toggle checked={ceoOnly} onChange={setCeoOnly}>
              CEO/CFO/Chair only
            </Toggle>
            <Toggle checked={notableOnly} onChange={setNotableOnly}>
              Notable only
            </Toggle>
            <Toggle checked={mine} onChange={setMine}>
              My holdings &amp; watchlist
            </Toggle>
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
          </div>
          <span className="num w-full text-[11px] tracking-[0.6px] text-muted">
            <span className="text-faint">RULE · </span>SEC FORM 4 · FILED WITHIN 2 BUSINESS DAYS · OPEN-MARKET BUYS (P) AND SELLS (S) ONLY
          </span>
        </div>

        {data && (data.poll_error || (data.holdings_note && mine) || data.truncated) ? (
          <div className="flex flex-col gap-1 border-t border-line bg-amber/[0.05] px-5 py-2 text-xs leading-[1.45] text-soft" role="status">
            {data.poll_error ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">FEED</span>
                Last SEC poll failed ({data.poll_error}); showing what was read before.
              </span>
            ) : null}
            {data.holdings_note && mine ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">HOLDINGS</span>
                {data.holdings_note}; only watchlist names can match.
              </span>
            ) : null}
            {data.truncated ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">LIMIT</span>
                Showing the newest {data.rows.length} of {fmtNumber(data.total_matching, 0)} matching trades. Raise the size filter to see
                fewer, bigger ones.
              </span>
            ) : null}
          </div>
        ) : null}

        <div id="ins-table" role="table" aria-label="Insider trades" className="flex min-h-0 flex-1 flex-col">
          <div
            role="row"
            className="num grid gap-x-3 border-y border-line bg-[#0F1216] px-5 py-2 text-[10px] tracking-[0.9px] text-faint"
            style={{ gridTemplateColumns: COLS }}
          >
            <span role="columnheader">FILED</span>
            <span role="columnheader">COMPANY</span>
            <span role="columnheader">INSIDER</span>
            <span role="columnheader">SIDE</span>
            <span role="columnheader" className="text-right" title="Value = shares × price">
              VALUE
            </span>
            <span role="columnheader" className="text-right">
              FLAGS
            </span>
            <span role="columnheader" className="text-right">
              <span className="sr-only">Filing</span>
            </span>
          </div>
          <div className={cx("min-h-0 flex-1 overflow-y-auto", isValidating && !isLoading && "opacity-90")}>{body}</div>
        </div>

        <div className="border-t border-line px-5 py-2.5 text-[11px] leading-[1.5] text-faint">
          Notable = a buy of {fmtUsdCompact(data?.thresholds.notable_buy_usd ?? 250_000)}+ or any buy by a CEO, CFO, president or chair, or a
          sale of {fmtUsdCompact(data?.thresholds.notable_sell_usd ?? 5_000_000)}+. 10b5-1 marks trades under a pre-arranged plan: planned
          sales are the weakest signal here. Amber trade date = filed more than two days after the trade. Grants, option exercises, tax withholding and amendments are left out. Names are as filed with
          the SEC.
        </div>
      </section>

      <aside aria-label="Insider context" className="flex w-[360px] shrink-0 flex-col gap-3.5 overflow-y-auto">
        {data ? (
          <>
            <TopBuys data={data} />
            <PollStatus data={data} now={now} />
          </>
        ) : null}
        <KesNote data={data} />
        <div className="num mt-auto flex flex-col gap-1.5 text-[11px] leading-[1.5] text-faint">
          <span>Source: SEC EDGAR Form 4, read directly from sec.gov (no third party, no API key)</span>
          {data ? (
            <Button variant="text" size="sm" className="self-start" onClick={() => void mutate()} disabled={isValidating}>
              {isValidating ? "Reloading…" : "Reload now"}
            </Button>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
