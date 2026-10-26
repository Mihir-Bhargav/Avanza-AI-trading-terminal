"use client";
/**
 * News column. Three tabs over the existing news endpoints:
 *   For you  ticker news (rank=explain) for held stocks (only if Avanza is
 *            already signed in; this page never triggers a login) and the
 *            setups universe, plus the news bot's explained movers.
 *   Market   /api/news/market?market=us
 *   Sweden   /api/news/market?market=sweden
 * "Explains the move" is shown only where the backend's news bot marked a
 * mover as explained; nothing here guesses at causality.
 */
import { useState } from "react";
import useSWR from "swr";
import {
  apiGet,
  paths,
  type ApiError,
  type MarketNewsResponse,
  type NewsBotResponse,
  type NewsItem,
  type PortfolioStatus,
  type PositionsResponse,
  type SetupsResponse,
  type TickerNewsResponse,
} from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtAge, fmtClock, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useNow } from "@/lib/useNow";
import { Segmented } from "../Segmented";
import { StateView } from "../StateView";

type Tab = "you" | "market" | "sweden";
const TABS: { value: Tab; label: string }[] = [
  { value: "you", label: "For you" },
  { value: "market", label: "Market" },
  { value: "sweden", label: "Sweden" },
];
const MAX_TICKERS = 8;
const POLL = 5 * 60_000;

interface Tagged extends NewsItem {
  symbol?: string;
  change_pct?: number | null;
  explained?: boolean;
  held?: boolean;
}

interface Target {
  /** Symbol sent to the news endpoint (Yahoo form, e.g. ERIC-B.ST). */
  query: string;
  /** Label on the chip (e.g. ERIC-B). */
  label: string;
  change_pct: number | null;
  held: boolean;
}

const marketFor = (sym: string) => (sym.toUpperCase().endsWith(".ST") ? "sweden" : "us");
const safeUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : null);

function fmtWhen(ts: string | null, now: number | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "—";
  if (now !== null && new Date(now).toDateString() === d.toDateString()) return fmtClock(ts);
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
}

function Item({ n, now }: { n: Tagged; now: number | null }) {
  const href = safeUrl(n.url);
  const chg = n.change_pct;
  return (
    <article className="relative flex gap-[18px] border-t border-raised px-[22px] py-3.5">
      <div className="flex w-[86px] shrink-0 flex-col gap-[3px]">
        <span className="num text-xs text-soft" title={n.age_min != null ? `${fmtAge(n.age_min)} ago` : "age unknown"}>
          {fmtWhen(n.ts, now)}
        </span>
        <span className="truncate text-[11px] text-faint" title={n.source}>
          {n.source}
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h2 className="m-0 text-[15px] font-medium leading-[1.35] text-text">
          {href ? (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-text hover:text-amber-hover hover:underline">
              {n.title}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : (
            n.title
          )}
        </h2>
        {n.symbol || n.explained ? (
          <div className="flex items-center gap-2 text-xs">
            {n.symbol ? (
              <span className="num rounded-chip bg-raised px-2 py-0.5 text-text-2">
                {n.symbol}
                {chg != null ? (
                  <span className={cx("ml-1.5", chg > 0 ? "text-up" : chg < 0 ? "text-down" : "text-muted")}>{fmtPct(chg, 1)}</span>
                ) : null}
                {n.held ? <span className="ml-1.5 text-[10px] tracking-[0.6px] text-amber">HELD</span> : null}
              </span>
            ) : null}
            {n.explained ? <span className="rounded-chip bg-amber/14 px-2 py-0.5 text-amber">Explains the move</span> : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function dedupe(items: Tagged[]): Tagged[] {
  const seen = new Map<string, Tagged>();
  for (const it of items) {
    // Same headline from two feeds (or two tickers) is one story.
    const k = it.title.toLowerCase().replace(/\s+/g, " ").trim();
    const prev = seen.get(k);
    // Keep the richest copy: explained beats not, tagged beats untagged.
    if (!prev || (it.explained && !prev.explained) || (it.symbol && !prev.symbol)) seen.set(k, it);
  }
  return [...seen.values()];
}

/** Newest first by the article's own timestamp (age_min is relative to when each response was built). */
const tsOf = (n: Tagged) => (n.ts ? Date.parse(n.ts) : NaN);
const byTime = (a: Tagged, b: Tagged) => {
  const ta = tsOf(a);
  const tb = tsOf(b);
  if (Number.isNaN(ta) && Number.isNaN(tb)) return 0;
  if (Number.isNaN(ta)) return 1;
  if (Number.isNaN(tb)) return -1;
  return tb - ta;
};

type ForYou = { items: Tagged[]; failed: { symbol: string; error: string }[] };

async function loadForYou(targets: Target[]): Promise<ForYou> {
  const settled = await Promise.allSettled(
    targets.map((t) =>
      apiGet<TickerNewsResponse>(paths.tickerNews(t.query, { limit: 4, market: marketFor(t.query), rank: "explain" })),
    ),
  );
  const items: Tagged[] = [];
  const failed: ForYou["failed"] = [];
  settled.forEach((s, i) => {
    const t = targets[i];
    if (s.status === "fulfilled")
      for (const n of s.value.items) items.push({ ...n, symbol: t.label, change_pct: t.change_pct, held: t.held });
    else failed.push({ symbol: t.label, error: s.reason instanceof Error ? s.reason.message : String(s.reason) });
  });
  if (failed.length === targets.length && targets.length) throw settled.find((s) => s.status === "rejected")!.reason;
  return { items, failed };
}

export function NewsList({ focus }: { focus?: string }) {
  const [tab, setTab] = useState<Tab>("you");
  const now = useNow(60_000);

  // Inputs for "For you". Portfolio positions are only read when a session already exists.
  const status = useApi<PortfolioStatus>(paths.portfolioStatus(), { refreshInterval: POLL });
  const authed = !!status.data?.authenticated;
  const positions = useApi<PositionsResponse>(authed ? paths.positions() : null, {
    refreshInterval: POLL,
    swr: { shouldRetryOnError: false },
  });
  const setups = useApi<SetupsResponse>(paths.setups(), { refreshInterval: POLL });
  const bot = useApi<NewsBotResponse>(paths.newsBot(), { refreshInterval: 60_000 });

  const inputsSettled = (status.data || status.error) && (setups.data || setups.error) && (!authed || positions.data || positions.error);

  const targets: Target[] = [];
  const add = (t: Target) => {
    if (targets.length < MAX_TICKERS && !targets.some((x) => x.label === t.label)) targets.push(t);
  };
  if (focus) add({ query: focus, label: focus.split(".")[0].toUpperCase(), change_pct: null, held: false });
  for (const p of positions.data?.positions ?? [])
    if (p.instrument_type === "STOCK" && p.yahoo_ticker)
      add({ query: p.yahoo_ticker, label: p.yahoo_ticker.split(".")[0], change_pct: p.day_change_pct, held: true });
  for (const r of setups.data?.rows ?? [])
    if (!r.yahoo.startsWith("^")) add({ query: r.yahoo, label: r.symbol, change_pct: null, held: false });

  const forYou = useSWR<ForYou, ApiError>(
    tab === "you" && inputsSettled ? ["news-for-you", ...targets.map((t) => t.query)] : null,
    () => loadForYou(targets),
    { refreshInterval: POLL, revalidateOnFocus: false, errorRetryInterval: 30_000 },
  );
  const market = useApi<MarketNewsResponse>(
    tab === "market" ? paths.marketNews({ market: "us", limit: 30 }) : tab === "sweden" ? paths.marketNews({ market: "sweden", limit: 30 }) : null,
    { refreshInterval: POLL },
  );

  let items: Tagged[] = [];
  let error: unknown;
  let loading = false;
  let retry = () => {};
  if (tab === "you") {
    const botItems: Tagged[] = [];
    for (const h of bot.data?.hits ?? [])
      h.news.forEach((n, i) => botItems.push({ ...n, symbol: h.symbol, change_pct: h.change_pct, explained: h.explained && i === 0 }));
    items = dedupe([...botItems, ...(forYou.data?.items ?? [])]).sort(byTime);
    // With no tickers to read (setups failed, no holdings), an empty list is a
    // failure, not "no headlines": surface the input error instead.
    error = forYou.error ?? (!targets.length && !items.length ? (setups.error ?? status.error) : undefined);
    loading = !forYou.data && !forYou.error;
    retry = () => {
      void setups.mutate();
      void forYou.mutate();
    };
  } else {
    items = (market.data?.items ?? []).map((n) => ({ ...n }));
    error = market.error;
    loading = !market.data && !market.error;
    retry = () => void market.mutate();
  }

  let hint = "";
  if (tab === "you") {
    const held = targets.filter((t) => t.held).length;
    const parts = [
      targets.length ? `${targets.length} tickers${held ? `, ${held} held` : ""}` : null,
      !authed ? "no holdings (Avanza signed out)" : positions.error ? "holdings unavailable" : null,
      bot.data ? (bot.data.status.last_scan_min == null ? "mover scan not run yet" : `movers scanned ${fmtAge(bot.data.status.last_scan_min)} ago`) : bot.error ? "mover scan unavailable" : null,
    ].filter(Boolean);
    hint = parts.join(" · ");
  } else if (tab === "market") hint = market.data ? `US wire · ${market.data.feeds} feeds` : "US wire";
  else hint = "Stockholm market · Swedish-language sources";

  return (
    <section aria-labelledby="news-h" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[16px] border border-line bg-surface">
      <div className="flex items-center gap-3.5 px-[22px] pb-3 pt-4">
        <h1 id="news-h" className="m-0 text-lg font-semibold text-text">
          News
        </h1>
        <Segmented ariaLabel="News filter" value={tab} onChange={setTab} options={TABS} controls="news-list" className="shrink-0" />
        <span className="min-w-0 flex-1 truncate text-right text-xs text-muted" title={hint}>
          {hint}
        </span>
      </div>
      {tab === "you" && forYou.data?.failed.length ? (
        <p role="status" className="m-0 border-t border-raised px-[22px] py-2 text-xs text-warn-text">
          News failed for {forYou.data.failed.map((f) => f.symbol).join(", ")} ({forYou.data.failed[0].error}).
        </p>
      ) : null}
      {tab === "you" && setups.error ? (
        <p role="status" className="m-0 border-t border-raised px-[22px] py-2 text-xs text-warn-text">
          Setups unavailable ({setups.error.message}), so the watchlist tickers are missing.
        </p>
      ) : null}
      <div id="news-list" role="tabpanel" aria-label={TABS.find((t) => t.value === tab)?.label} className="min-h-0 flex-1 overflow-y-auto">
        {items.length ? (
          items.map((n, i) => <Item key={`${n.url}-${i}`} n={n} now={now} />)
        ) : error ? (
          <StateView kind="error" error={error} onRetry={retry} />
        ) : loading ? (
          <StateView kind="loading" title={tab === "you" ? "Reading news for your tickers" : "Reading the wire"} />
        ) : (
          <StateView
            kind="empty"
            title="No recent headlines"
            message={tab === "you" ? "Nothing in the last two days for these tickers." : "The feed returned nothing for the last day."}
          />
        )}
      </div>
    </section>
  );
}
