"use client";
/**
 * Funds 13F: what well-known funds opened, added to, trimmed and closed last
 * quarter, from their two latest 13F-HR filings on SEC EDGAR (diffed by the
 * backend, terminal/funds13f.py). The backend reads the SEC in a background
 * thread; while it is still loading this view re-reads every few seconds.
 */
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { ApiError, paths, type DisclosureRow, type DisclosuresResponse, type FundSide, type FundStatus } from "@/lib/api";
import { cx } from "@/lib/cx";
import { DASH, fmtClock } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { Button } from "../Button";
import { fmtUsdCompact } from "./InsidersView";
import { Kes } from "../Kes";
import { Segmented } from "../Segmented";
import { StateView } from "../StateView";

type SideFilter = "all" | "buys" | "sells" | FundSide;
const SIDES: { value: SideFilter; label: string; ariaLabel?: string }[] = [
  { value: "all", label: "All" },
  { value: "buys", label: "Buys", ariaLabel: "New and added positions" },
  { value: "sells", label: "Sells", ariaLabel: "Trimmed and closed positions" },
  { value: "NEW", label: "New" },
  { value: "EXIT", label: "Exits", ariaLabel: "Closed positions" },
];
const COLS = "minmax(0,1.35fr) 58px minmax(0,1.7fr) 76px 60px minmax(0,1.05fr) 86px";
const LOADING_POLL_MS = 3_000;

const CHIP: Record<FundSide, string> = {
  NEW: "bg-up/[0.16] text-up",
  ADD: "bg-up/[0.08] text-up/90",
  TRIM: "bg-amber/[0.12] text-amber",
  EXIT: "bg-down/[0.14] text-down",
};
const CHIP_TITLE: Record<FundSide, string> = {
  NEW: "Opened: not in the previous quarter's 13F",
  ADD: "Added: more shares than the previous quarter",
  TRIM: "Trimmed: fewer shares than the previous quarter",
  EXIT: "Closed: in the previous quarter's 13F, gone from this one",
};

function quarter(period: string | null | undefined): string {
  if (!period) return DASH;
  const [y, m] = period.split("-").map(Number);
  return m ? `Q${Math.ceil(m / 3)} ${y}` : period;
}

function shortDate(d: string | null | undefined): string {
  if (!d) return DASH;
  const t = new Date(`${d}T12:00:00`);
  return Number.isNaN(t.getTime()) ? d : t.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `${v < 0.05 && v > 0 ? "<0.1" : v.toFixed(digits)}%`;
}

function isSide(s: string | null): s is FundSide {
  return s === "NEW" || s === "ADD" || s === "TRIM" || s === "EXIT";
}

function matchesSide(r: DisclosureRow, f: SideFilter): boolean {
  if (f === "all") return true;
  if (f === "buys") return r.side === "NEW" || r.side === "ADD";
  if (f === "sells") return r.side === "TRIM" || r.side === "EXIT";
  return r.side === f;
}

function ActionChip({ side }: { side: string | null }) {
  if (!isSide(side)) return <span className="text-muted">{DASH}</span>;
  return (
    <span
      title={CHIP_TITLE[side]}
      className={cx("num inline-flex h-[20px] w-[46px] items-center justify-center rounded-[5px] text-[10px] font-semibold tracking-[0.7px]", CHIP[side])}
    >
      {side}
    </span>
  );
}

function changeText(r: DisclosureRow): { main: string; sub: string | null; tone: string } {
  const split = r.split_adjusted
    ? r.split_adjusted >= 1
      ? `after ${r.split_adjusted}:1 split`
      : `after 1:${Math.round(1 / r.split_adjusted)} reverse split`
    : null;
  if (r.side === "NEW") return { main: "new position", sub: null, tone: "text-up" };
  if (r.side === "EXIT") return { main: "sold all", sub: null, tone: "text-down" };
  const c = r.change_pct ?? 0;
  const main = `${c > 0 ? "+" : "−"}${Math.abs(c) >= 10 ? Math.round(Math.abs(c)) : Math.abs(c).toFixed(1)}% shares`;
  return { main, sub: split, tone: c > 0 ? "text-up" : "text-amber" };
}

function Row({ r, onFund }: { r: DisclosureRow; onFund: (key: string) => void }) {
  const exit = r.side === "EXIT";
  const ch = changeText(r);
  const value = exit ? r.prev_value : r.value;
  const share = exit ? r.prev_pct_portfolio : r.pct_portfolio;
  return (
    <div
      role="row"
      className={cx(
        "grid min-h-[50px] items-center gap-x-3 border-b border-raised px-5 py-1.5 text-[13px] transition-colors hover:bg-[#161B22]",
        r.yours === "HELD" && "bg-amber/[0.04]",
      )}
      style={{ gridTemplateColumns: COLS }}
    >
      <span role="cell" className="flex min-w-0 flex-col">
        <button
          type="button"
          onClick={() => r.fund_key && onFund(r.fund_key)}
          className="truncate text-left text-text hover:text-amber"
          title={`Show only ${r.who}`}
        >
          {r.who ?? DASH}
        </button>
        <span className="truncate text-[11px] text-faint">{r.manager ?? ""}</span>
      </span>
      <span role="cell">
        <ActionChip side={r.side} />
      </span>
      <span role="cell" className="flex min-w-0 flex-col">
        <span className="flex items-center gap-1.5">
          {r.symbol ? (
            <Link
              href={`/terminal/chart/${encodeURIComponent(r.symbol)}`}
              className="num font-semibold text-text hover:text-amber hover:underline"
              title={`Open the ${r.symbol} chart`}
            >
              {r.symbol}
            </Link>
          ) : (
            <span className="num text-muted" title={`No confident ticker match for CUSIP ${r.cusip ?? "?"}; left blank rather than guessed`}>
              {DASH}
            </span>
          )}
          {r.yours ? (
            <span
              className={cx(
                "num inline-flex h-[16px] items-center rounded-[4px] px-1 text-[9px] font-semibold tracking-[0.6px]",
                r.yours === "HELD" ? "bg-amber/14 text-amber" : "bg-zone/14 text-zone-text",
              )}
            >
              {r.yours}
            </span>
          ) : null}
        </span>
        <span className="truncate text-[11px] text-muted" title={[r.issuer, r.security, r.cusip].filter(Boolean).join(" · ")}>
          {r.issuer ?? DASH}
        </span>
      </span>
      <span role="cell" className="flex flex-col items-end">
        <span className={cx("num", exit ? "text-muted" : "font-semibold text-text-2")}>{fmtUsdCompact(value)}</span>
        {exit ? <span className="num text-[11px] text-faint">was</span> : null}
      </span>
      <span role="cell" className="flex flex-col items-end">
        <span className={cx("num", exit ? "text-muted" : "text-text-2")}>{pct(share)}</span>
        {exit ? <span className="num text-[11px] text-faint">was</span> : null}
      </span>
      <span role="cell" className="flex min-w-0 flex-col">
        <span className={cx("num truncate text-xs", ch.tone)}>{ch.main}</span>
        {ch.sub ? <span className="truncate text-[11px] text-faint">{ch.sub}</span> : null}
      </span>
      <span
        role="cell"
        className="flex flex-col items-end"
        title={`Quarter ended ${r.traded ?? "?"}; filed ${r.filed ?? "?"}${r.lag_days != null ? ` (${r.lag_days} days later)` : ""}${r.amended ? `; amended ${r.amended}` : ""}`}
      >
        <span className="num text-text-2">{quarter(r.traded)}</span>
        <span className={cx("num text-[11px]", r.lag_days != null && r.lag_days > 45 ? "text-amber" : "text-faint")}>
          filed {shortDate(r.filed)}
          {r.amended ? "*" : ""}
        </span>
      </span>
    </div>
  );
}

function MostBought({ data, onSymbol }: { data: DisclosuresResponse; onSymbol: (s: string) => void }) {
  const items = data.most_bought.slice(0, 8);
  const max = Math.max(1, ...items.map((m) => m.count));
  const total = data.funds?.filter((f) => f.in_window).length ?? 0;
  return (
    <section aria-labelledby="fmost-h" className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-[18px] py-4">
      <div className="flex items-baseline">
        <h2 id="fmost-h" className="m-0 text-sm font-semibold text-text">
          Most bought by these funds
        </h2>
        <span className="num ml-auto shrink-0 pl-2 text-[10px] tracking-[0.8px] text-faint">NEW + ADD · LATEST 13F</span>
      </div>
      {items.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items.map((m) => (
            <li key={m.symbol} className="flex items-center gap-2.5 text-xs" title={m.funds?.join(", ")}>
              <button type="button" onClick={() => onSymbol(m.symbol)} className="num w-12 truncate text-left font-semibold text-text hover:text-amber">
                {m.symbol}
              </button>
              <span aria-hidden="true" className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-[3px] bg-raised">
                <span className="block h-1.5 bg-up/70" style={{ width: `${(m.count / max) * 100}%` }} />
              </span>
              <span className="num w-[52px] whitespace-nowrap text-right text-text-2">
                {m.count}
                <span className="text-faint"> of {total}</span>
              </span>
              <span className="num w-[52px] text-right text-[11px] text-faint">{m.value != null ? `+${fmtUsdCompact(m.value)}` : ""}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[13px] text-muted">{data.loading ? "Still reading filings…" : "No opened or added positions with a known ticker."}</p>
      )}
    </section>
  );
}

function FundDot({ f }: { f: FundStatus }) {
  const tone = f.status === "error" ? "bg-down" : f.status === "pending" ? "bg-zone animate-pulse" : f.in_window === false ? "bg-faint" : "bg-up";
  return <span aria-hidden="true" className={cx("h-1.5 w-1.5 shrink-0 rounded-full", tone)} />;
}

function FundsList({ funds, selected, onSelect }: { funds: FundStatus[]; selected: string; onSelect: (k: string) => void }) {
  return (
    <section aria-labelledby="flist-h" className="flex flex-col gap-2 rounded-[14px] border border-line bg-surface px-[18px] py-4">
      <div className="flex items-baseline">
        <h2 id="flist-h" className="m-0 text-sm font-semibold text-text">
          Funds tracked
        </h2>
        <span className="num ml-auto text-[10px] tracking-[0.8px] text-faint">LATEST 13F · REPORTED</span>
      </div>
      <ul className="m-0 flex list-none flex-col p-0">
        {funds.map((f) => (
          <li key={f.key}>
            <button
              type="button"
              onClick={() => onSelect(selected === f.key ? "all" : f.key)}
              aria-pressed={selected === f.key}
              className={cx(
                "flex w-full items-center gap-2 rounded-md px-1.5 py-[5px] text-left text-xs hover:bg-raised",
                selected === f.key && "bg-raised",
              )}
              title={f.error ?? (f.notes.join("\n") || undefined)}
            >
              <FundDot f={f} />
              <span className={cx("min-w-0 flex-1 truncate", f.in_window === false || f.status === "error" ? "text-muted" : "text-text-2")}>{f.name}</span>
              <span className="num shrink-0 text-[11px] text-faint">
                {f.status === "error" ? "failed" : f.status === "pending" ? "loading" : quarter(f.period)}
              </span>
              <span className="num w-[46px] shrink-0 text-right text-[11px] text-soft">{f.total_value != null ? fmtUsdCompact(f.total_value) : ""}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FundCard({ f, onClear }: { f: FundStatus; onClear: () => void }) {
  const lag = f.filed && f.period ? Math.round((Date.parse(f.filed) - Date.parse(f.period)) / 86_400_000) : null;
  const stat = (label: string, value: ReactNode, tone = "text-text-2") => (
    <div className="flex flex-col gap-0.5 rounded-lg bg-rail p-2">
      <span className="text-[10px] text-faint">{label}</span>
      <span className={cx("text-[15px]", tone)}>{value}</span>
    </div>
  );
  return (
    <section aria-labelledby="fcard-h" className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-[18px] py-4">
      <div className="flex items-start gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id="fcard-h" className="m-0 truncate text-[15px] font-semibold text-text">
            {f.name}
          </h2>
          <span className="text-xs text-muted">{f.manager}</span>
        </div>
        <Button variant="text" size="sm" className="ml-auto shrink-0" onClick={onClear}>
          All funds
        </Button>
      </div>
      <div className="num grid grid-cols-3 gap-2">
        {stat("REPORTED", f.total_value != null ? fmtUsdCompact(f.total_value) : DASH)}
        {stat("POSITIONS", f.positions ?? DASH)}
        {stat("CHANGES", f.moves)}
      </div>
      <span className="num text-xs text-muted">
        {quarter(f.period)} vs {quarter(f.prev_period)} · filed {shortDate(f.filed)}
        {lag != null ? ` · ${lag} days after quarter end` : ""}
        {f.amended ? ` · amended ${shortDate(f.amended)}` : ""}
      </span>
      {f.in_window === false ? (
        <span className="text-xs text-amber">Latest 13F is older than the window: this fund has stopped filing or is late. No rows shown.</span>
      ) : null}
      {f.error ? <span className="text-xs text-warn-text">Last SEC read failed: {f.error}</span> : null}
      {f.notes.map((n) => (
        <span key={n} className="text-[11px] leading-[1.45] text-faint">
          {n}
        </span>
      ))}
      <a href={f.sec_url} target="_blank" rel="noopener noreferrer" className="num self-start text-xs text-muted hover:text-amber">
        13F filings on SEC EDGAR ↗
      </a>
    </section>
  );
}

export function FundsView({ header, symbol }: { header: ReactNode; symbol?: string }) {
  const [fund, setFund] = useState<string>("all");
  const [side, setSide] = useState<SideFilter>("all");
  const [onlyMine, setOnlyMine] = useState(false);
  const [filter, setFilter] = useState<string | undefined>(symbol?.toUpperCase());
  const { data, error, isValidating, mutate } = useApi<DisclosuresResponse>(paths.disclosures("funds"), {
    swr: {
      revalidateIfStale: false,
      shouldRetryOnError: false,
      keepPreviousData: true,
      refreshInterval: (latest?: DisclosuresResponse) => (latest?.loading ? LOADING_POLL_MS : 0),
    },
  });

  const funds = useMemo(() => data?.funds ?? [], [data]);
  const rows = useMemo(() => {
    let r = data?.rows ?? [];
    if (fund !== "all") r = r.filter((x) => x.fund_key === fund);
    if (side !== "all") r = r.filter((x) => matchesSide(x, side));
    if (onlyMine) r = r.filter((x) => x.yours === "HELD" || x.yours === "WATCH");
    if (filter) r = r.filter((x) => (x.symbol ?? "").toUpperCase() === filter);
    return r;
  }, [data, fund, side, onlyMine, filter]);

  const notConfigured =
    error instanceof ApiError && error.status === 503 && (error.body as { configured?: boolean } | undefined)?.configured === false;
  const selected = funds.find((f) => f.key === fund);
  const stale = funds.filter((f) => f.in_window === false);
  const failed = funds.filter((f) => f.status === "error");

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
              the backend. The same setting powers Insiders · live; 13F filings are free, no key needed.
            </>
          }
        />
      );
    if (!data)
      return error ? (
        <StateView kind="error" error={error} onRetry={() => void mutate()} />
      ) : (
        <StateView kind="loading" title="Reading 13F filings" />
      );
    if (!data.rows.length && data.loading)
      return (
        <StateView
          kind="loading"
          title="Loading from the SEC"
          message={`Reading each fund's two latest 13F filings from EDGAR (${data.progress?.done ?? 0} of ${data.progress?.total ?? "?"} funds so far). The first load takes about half a minute; after that everything is cached.`}
        />
      );
    if (!rows.length)
      return (
        <StateView
          kind="empty"
          title={data.rows.length ? "No changes match these filters" : "No 13F changes in the window"}
          message={data.rows.length ? "Try All, or clear the fund and ticker filters." : `No fund filed a 13F in the last ${data.window_days ?? 180} days.`}
        />
      );
    return rows.map((r, i) => <Row key={`${r.fund_key}-${r.cusip}-${i}`} r={r} onFund={setFund} />);
  })();

  return (
    <div className="flex min-h-0 flex-1 gap-4 px-6 py-5">
      <section aria-labelledby="disc-h" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[14px] border border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5 px-5 pb-3.5 pt-4">
          {header}
          <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-2">
            <label className="flex items-center gap-2 text-[13px] text-soft">
              <span className="sr-only">Fund</span>
              <select
                value={fund}
                onChange={(e) => setFund(e.target.value)}
                aria-controls="funds-table"
                className="h-[30px] max-w-[260px] cursor-pointer rounded-lg border border-line bg-rail px-2.5 text-[13px] text-text-2 outline-none hover:border-line-2 focus-visible:border-amber"
              >
                <option value="all">All funds{funds.length ? ` (${funds.filter((f) => f.in_window !== false).length})` : ""}</option>
                {funds.map((f) => (
                  <option key={f.key} value={f.key} disabled={f.status !== "ok"}>
                    {f.name} · {f.manager}
                    {f.in_window === false ? " (no recent 13F)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <Segmented ariaLabel="Action" value={side} onChange={setSide} options={SIDES} size="sm" controls="funds-table" />
            <label className="flex cursor-pointer items-center gap-2 text-[13px] text-soft">
              <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} className="h-[15px] w-[15px] accent-amber" />
              <span>My holdings &amp; watchlist</span>
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
          </div>
          <span className="num w-full text-[11px] tracking-[0.6px] text-muted">
            <span className="text-faint">RULE · </span>
            {(data?.rule ?? "13F · quarterly, filed up to 45 days after quarter end").toUpperCase()} · LATEST VS PREVIOUS QUARTER
          </span>
        </div>

        {data && (data.loading || failed.length || data.tickers?.error || (data.holdings_note && onlyMine)) ? (
          <div className="flex flex-col gap-1 border-t border-line bg-amber/[0.05] px-5 py-2 text-xs leading-[1.45] text-soft" role="status">
            {data.loading ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-zone-text">LOADING</span>
                {data.progress?.done ?? 0} of {data.progress?.total ?? "?"} funds read from the SEC; more rows appear as they arrive.
              </span>
            ) : null}
            {failed.length ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">PARTIAL</span>
                {failed.map((f) => `${f.name}: ${f.error ?? "failed"}`).join(". ")}. Retried in 15 minutes.
              </span>
            ) : null}
            {data.tickers?.error ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">TICKERS</span>
                {data.tickers.error}
              </span>
            ) : null}
            {data.holdings_note && onlyMine ? (
              <span>
                <span className="num mr-1.5 text-[10px] tracking-[0.8px] text-amber">HOLDINGS</span>
                {data.holdings_note}; only watchlist names can match.
              </span>
            ) : null}
          </div>
        ) : null}

        <div id="funds-table" role="table" aria-label="Fund 13F changes" className="flex min-h-0 flex-1 flex-col">
          <div
            role="row"
            className="num grid gap-x-3 border-y border-line bg-[#0F1216] px-5 py-2 text-[10px] tracking-[0.9px] text-faint"
            style={{ gridTemplateColumns: COLS }}
          >
            <span role="columnheader">FUND</span>
            <span role="columnheader">ACTION</span>
            <span role="columnheader">COMPANY</span>
            <span role="columnheader" className="text-right" title="Position value at quarter end (for exits: at the previous quarter end)">
              VALUE
            </span>
            <span role="columnheader" className="text-right" title="Share of the fund's reported long-equity value">
              % PORT
            </span>
            <span role="columnheader">CHANGE</span>
            <span role="columnheader" className="text-right">
              PERIOD
            </span>
          </div>
          <div className={cx("min-h-0 flex-1 overflow-y-auto", isValidating && !data?.loading && "opacity-90")}>{body}</div>
        </div>

        <div className="border-t border-line px-5 py-2.5 text-[11px] leading-[1.5] text-faint">
          13F shows long US-listed stock positions at quarter end only: no shorts, no cash, no non-US holdings, and nothing about trades
          made and reversed within the quarter. It is filed up to 45 days late, so a position can be gone before you see it. Options and
          convertibles are left out here. Change = share count versus the previous 13F; value and % of portfolio are at quarter end. Tickers
          come from matching the SEC issuer name; blank means no confident match. * = the quarter was amended.
        </div>
      </section>

      <aside aria-label="Fund context" className="flex w-[360px] shrink-0 flex-col gap-3.5 overflow-y-auto">
        {data && selected ? <FundCard f={selected} onClear={() => setFund("all")} /> : null}
        {data ? <MostBought data={data} onSymbol={(s) => setFilter(s)} /> : null}
        {funds.length ? <FundsList funds={funds} selected={fund} onSelect={setFund} /> : null}
        <section aria-label="Kes on 13F filings" className="flex gap-3 rounded-[14px] border border-kes-line bg-kes-surface px-4 py-3.5">
          <Kes mood="cautious" size={40} perch="none" className="shrink-0" />
          <div className="flex flex-col gap-1.5">
            <span className="text-[13px] font-semibold text-text">Kes</span>
            <span className="text-[13px] leading-[1.5] text-[#D5DBE2]">
              These are quarter-end snapshots, filed about six weeks later. A fund can have sold since, or hedged the position in ways a 13F
              never shows. Read it as who owns what, not as a signal to follow.
              {stale.length ? ` ${stale.map((f) => f.name).join(", ")} ${stale.length === 1 ? "has" : "have"} no 13F in the window.` : ""}
            </span>
          </div>
        </section>
        <div className="num mt-auto flex flex-col gap-1.5 text-[11px] leading-[1.5] text-faint">
          <span>Source: SEC EDGAR 13F-HR filings, read directly from sec.gov (no third party, no API key)</span>
          {data ? (
            <span>
              Built {fmtClock(data.as_of)}
              {data.tickers ? ` · tickers matched for ${data.tickers.mapped} of ${data.tickers.total} changes` : ""}
              {data.max_moves_per_fund ? ` · biggest ${data.max_moves_per_fund} changes per fund` : ""}
            </span>
          ) : null}
          {data ? (
            <Button variant="text" size="sm" className="self-start" onClick={() => void mutate()} disabled={isValidating}>
              {isValidating ? "Reloading…" : "Reload"}
            </Button>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
