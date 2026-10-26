/**
 * Typed client for the Range backend (FastAPI, terminal/app.py).
 *
 * The backend is read-only toward the brokerage: nothing here places, modifies
 * or cancels an order, and nothing ever should. The only writes are local
 * (trade plans, AI questions).
 *
 * This module is server-safe (types, paths, apiGet/apiPost, ApiError).
 * The React hook lives in "@/lib/useApi" (client components only):
 *   const { data, error, isLoading } = useApi<SetupsResponse>(paths.setups());
 *   const { data } = useApi<MarketLineResponse>(paths.marketLine(), { refreshInterval: 15_000 });
 * Errors are ApiError instances; render them (StateView kind="error"), never hide them.
 */
// Empty = same-origin /api/*, proxied to the backend by next.config.ts (no CORS).
// Set NEXT_PUBLIC_API_BASE only to call a backend directly.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");
/** Human-readable backend location for error messages. */
export const BACKEND_LABEL = API_BASE || "127.0.0.1:8777 (via the /api proxy)";

/* ------------------------------------------------------------------ shared */

export type Freshness = "live" | "delayed" | "closed" | "stale" | "unknown";

/* ------------------------------------------------------------- market line */

export interface MarketLineItem {
  key: string;
  label: string;
  symbol: string;
  last: number | null;
  change_pct: number | null; // percent units: 0.79 = +0.79%
  freshness: Freshness;
  age_min: number | null;
  /** e.g. "yfinance", "yfinance-futures", "avanza-spot" */
  source?: string;
  /** Present when this item failed (last is null, freshness "unknown"). */
  error?: string;
}
export interface MarketLineResponse {
  as_of: string;
  items: MarketLineItem[];
}

/* ------------------------------------------------------------------ setups */

export type SetupState =
  | "crossed_z1_up"
  | "crossed_z3_down"
  | "at_z1"
  | "at_z3"
  | "near_z1"
  | "near_z3"
  | "inside";

/** Historical base rate for a zone cross. Null when there were no events (n = 0). */
export interface HistBlock {
  n: number;
  win_rate: number | null; // fraction 0..1
  avg_fwd_ret: number | null; // fraction: 0.016 = +1.6%
}

export interface SetupRow {
  symbol: string;
  yahoo: string;
  name: string;
  avanza_query: string | null;
  trend: "up" | "down";
  close: number;
  open: number;
  zone1: number;
  zone2: number;
  zone3: number;
  zone4: number;
  atr14: number;
  atr_pct: number; // percent units
  lev_cap: number | null; // max leverage ≈ 100 / (3.5 × ATR%)
  state: SetupState;
  dist_z1_atr: number | null;
  dist_z3_atr: number | null;
  with_trend: boolean;
  hist: { z1_up: HistBlock; z3_dn: HistBlock };
  earnings_date: string | null;
  earnings_days: number | null;
  /** Present when the earnings lookup failed (the row is still valid). */
  earnings_error?: string;
  bar_date?: string;
}
export interface SetupsResponse {
  as_of: string;
  rows: SetupRow[];
  /** Symbols whose row could not be built, with the reason. */
  errors?: { symbol: string; error: string }[];
}

/* --------------------------------------------------------------- portfolio */

export interface PortfolioStatus {
  configured: boolean;
  authenticated: boolean;
  /** Set after a failed Avanza login: no new attempt before this time. Show it. */
  login_blocked_until: string | null;
  /** Redacted reason for the last failed login. */
  last_login_failure: string | null;
}

export interface AccountSummary {
  account: string; // alias (ISK, AF, ...) — never the account number
  name: string | null;
  type: string | null;
  status: string | null;
  total_value: number | null;
  cash: number | null;
  buying_power: number | null;
  buying_power_without_credit: number | null;
  unit: string | null;
}
export interface PortfolioSummary {
  accounts: AccountSummary[];
  totals_sek: { total_value?: number; cash?: number; buying_power?: number };
  non_sek_amounts_not_in_totals: { account: string; field: string; value: number; unit: string }[];
}

export interface Position {
  account: string;
  name: string;
  instrument_type: string | null;
  isin: string | null;
  orderbook_id: string | null;
  yahoo_ticker: string | null;
  currency: string | null;
  quantity: number | null;
  last_price: number | null;
  last_price_updated: string | null;
  avg_cost: number | null;
  avg_cost_sek: number | null;
  market_value: number | null;
  market_value_sek: number | null;
  cost_basis_sek: number | null;
  pnl_sek: number | null;
  pnl_pct: number | null; // percent units
  day_change_pct: number | null; // percent units
  implied_fx_to_sek: number | null;
  value_unit: string | null;
}
export interface PositionsResponse {
  positions: Position[];
  cash: { account: string; cash: number | null; unit: string | null }[];
  totals_sek: { market_value: number | null; cost_basis: number | null; pnl: number | null };
  exposure_by_currency_sek: Record<string, { value: number | null; pct: number | null }>;
  non_sek_positions_not_in_totals: string[];
}

export type PerformancePeriod = "1d" | "1w" | "1m" | "3m" | "ytd" | "1y" | "3y" | "all";

export interface InsightInstrument {
  name: string;
  isin: string | null;
  instrument_type: string | null;
  outcome_sek: number | null;
  outcome_pct: number | null;
  dividends_sek: number | null;
}
export interface PerformanceResponse {
  period: PerformancePeriod;
  per_account: {
    account: string;
    name: string | null;
    type: string | null;
    change: number | null;
    change_unit: string | null;
    change_pct: number | null;
  }[];
  /** Which Avanza report each part came from, e.g. {per_account: "overview.ONE_WEEK", positions: "insights.ONE_WEEK"}. */
  source: { per_account: string | null; positions: string | null };
  insights: null | {
    total_outcome_sek: number | null;
    price_development_sek: number | null;
    dividends_sek: number | null;
    best: InsightInstrument[];
    worst: InsightInstrument[];
  };
  note?: string;
  insights_note?: string;
}

export interface Transaction {
  date: string;
  trade_date: string | null;
  account: string;
  type: string;
  description: string | null;
  instrument: string | null;
  isin: string | null;
  orderbook_id: string | null;
  quantity: number | null;
  price: number | null;
  price_unit: string | null;
  amount: number | null;
  amount_unit: string | null;
  commission: number | null;
  commission_unit: string | null;
  currency_rate: number | null;
  cancelled: boolean;
}
export interface TransactionsResponse {
  transactions: Transaction[];
  count: number;
  first_transaction_date: string | null;
}

export interface BriefHolding {
  name: string;
  ticker: string | null;
  type: string | null;
  currency: string | null;
  account: string;
  value_sek: number | null;
  weight_of_portfolio_pct: number | null;
  weight_of_invested_pct: number | null;
  pnl_sek: number | null;
  pnl_pct: number | null;
  day_change_pct: number | null;
}
export interface BriefPerformance {
  per_account: { account: string; change: number | null; change_pct: number | null }[];
  insights_total_sek: number | null;
  best: InsightInstrument[] | null;
  worst: InsightInstrument[] | null;
}
export interface PortfolioBrief {
  as_of: string;
  totals_sek: {
    portfolio: number | null;
    invested: number | null;
    cash: number | null;
    cash_pct: number | null;
    cost_basis: number | null;
    unrealized_pnl: number | null;
    unrealized_pnl_pct: number | null;
  };
  accounts: { account: string; type: string | null; total_value: number | null; cash: number | null }[];
  performance: Partial<Record<"1d" | "1w" | "1m" | "ytd", BriefPerformance>>;
  concentration: {
    top1_pct_of_invested: number | null;
    top3_pct_of_invested: number | null;
    by_instrument_type_pct: Record<string, number | null>;
    by_currency_pct: Record<string, number | null>;
  };
  holdings: BriefHolding[];
  /** Keys like "day_move_over_3pct"; values are holdings (or stale-price records). */
  flags: Record<string, unknown[]>;
  earnings: {
    within_days: number;
    upcoming: { ticker: string; date: string; days_until: number }[];
    checked: string[];
    lookup_failed: string[];
    not_applicable: string[];
    unmapped_stocks: string[];
  };
  news_targets: { stock_tickers: string[]; other_mapped: string[] };
}

/* ------------------------------------------------------------- disclosures */

export type DisclosureType = "congress" | "insiders" | "funds";

export interface DisclosureRow {
  filed: string | null;
  traded: string | null;
  lag_days: number | null;
  who: string | null;
  chamber: string | null;
  party: string | null;
  owner: string | null;
  role: string | null;
  symbol: string | null;
  side: string | null;
  amount_min: number | null;
  amount_max: number | null;
  amount_label: string | null;
  yours: "HELD" | "WATCH" | null;
  /** Insiders: the security/class traded. Funds: the 13F title of class. */
  security?: string | null;
  /* ---- funds (13F, SEC EDGAR) only; side is NEW | ADD | TRIM | EXIT ---- */
  fund_key?: string;
  manager?: string;
  issuer?: string | null;
  cusip?: string;
  /** USD at the latest quarter end (0 for EXIT). */
  value?: number;
  /** USD at the previous quarter end (0 for NEW). */
  prev_value?: number;
  shares?: number;
  prev_shares?: number;
  /** Share-count change in %, null for NEW, -100 for EXIT. */
  change_pct?: number | null;
  /** k for a k-for-1 split adjusted between the quarters (k < 1: reverse split). */
  split_adjusted?: number | null;
  /** % of the fund's reported long-equity value (latest / previous quarter). */
  pct_portfolio?: number | null;
  prev_pct_portfolio?: number | null;
  prev_period?: string | null;
  /** Date of a 13F-HR/A that amended this quarter, if any. */
  amended?: string | null;
}

export type FundSide = "NEW" | "ADD" | "TRIM" | "EXIT";

export interface FundStatus {
  key: string;
  name: string;
  manager: string;
  cik: number;
  ciks: number[];
  status: "pending" | "ok" | "error";
  error: string | null;
  period: string | null;
  filed: string | null;
  amended: string | null;
  prev_period: string | null;
  positions: number | null;
  total_value: number | null;
  moves: number;
  /** false when the latest 13F was filed before the `days` window (fund stopped filing). */
  in_window: boolean | null;
  notes: string[];
  sec_url: string;
}
export interface DisclosuresResponse {
  type: DisclosureType;
  configured: boolean;
  rule: string;
  as_of: string;
  source: string;
  partial: boolean;
  skipped: string[];
  /** Why each skipped symbol was skipped (e.g. live-fetch cap, non-US ticker). */
  skipped_reasons?: Record<string, string>;
  symbols?: string[];
  window_days?: number;
  live_fetches?: number;
  /** e.g. "portfolio session not authenticated; HELD is not marked" */
  holdings_note?: string | null;
  rows: DisclosureRow[];
  /** Funds: count = funds that opened or added; value = USD added; funds = their names. */
  most_bought: { symbol: string; count: number; value?: number; funds?: string[] }[];
  /* ---- funds (13F, SEC EDGAR) only ---- */
  /** True while the background SEC fetch is still reading funds. */
  loading?: boolean;
  progress?: { done: number; total: number };
  funds?: FundStatus[];
  tickers?: { mapped: number; total: number; error: string | null };
  max_moves_per_fund?: number;
  /** Alpha Vantage live calls today across all requests (free tier: 25/day). */
  budget?: { used: number; limit: number; date: string; by_function: Record<string, number>; exhausted: string | null };
}

/* ---------------------------------------------------- insiders (SEC Form 4) */

export type InsiderSide = "BUY" | "SELL";

export interface InsiderRow {
  id: string; // accession:line
  filed_at: string; // ISO with offset (SEC acceptance time)
  trade_date: string | null;
  lag_days: number | null;
  ticker: string | null;
  issuer: string | null;
  who: string | null; // as filed, title-cased; "+N" for joint filers
  role: string | null; // e.g. "Chief Executive Officer · Director"
  is_ceo_like: boolean;
  side: InsiderSide;
  shares: number | null;
  price: number | null; // USD per share; null when the filing gives none
  value: number | null; // shares × price, USD
  security: string | null;
  plan_10b5_1: boolean;
  notable: boolean;
  yours: "HELD" | "WATCH" | null;
  sec_url: string;
}
export interface InsidersResponse {
  configured: true;
  as_of: string;
  source: string;
  last_poll: string | null;
  feed_updated: string | null;
  poll_error: string | null;
  backfilling: boolean;
  filings_seen: number;
  parsed_this_session: number;
  parse_failures: number;
  last_parse_failure: string | null;
  store_error: string | null;
  poll_seconds: number;
  window_days: number;
  thresholds: { notable_buy_usd: number; notable_sell_usd: number };
  holdings_note: string | null;
  rows: InsiderRow[];
  total_matching: number;
  truncated: boolean;
  top_buys: { ticker: string; issuer: string | null; value: number; buyers: number }[];
}
export interface InsidersQuery {
  days?: number;
  side?: "buy" | "sell" | "all";
  min_value?: number;
  notable_only?: boolean;
  ceo_only?: boolean;
  mine?: boolean;
  symbols?: string;
}

/* --------------------------------------------------------------------- Kes */

export type KesMood = "watching" | "alert" | "cautious" | "thinking" | "pleased";

export interface KesBriefing {
  mood: KesMood;
  text: string;
  links: { label: string; href: string }[];
  as_of: string;
  plans_error?: string;
}

/* ------------------------------------------------------------------- plans */

export interface PlanInput {
  symbol: string;
  side: string;
  take_profit: number;
  stop_loss: number;
  leverage: number;
  note?: string;
}
/** Saved plan. Intent only: recording a plan never places anything. */
export interface Plan extends PlanInput {
  id: string;
  created_at: string;
  price_at_plan: number | null;
  lev_cap: number | null;
  checked_against: string | null;
}
/** POST /api/plans returns the stored plan plus the updated streak. */
export type SavedPlanResponse = Plan & { streak: number };
export interface PlansResponse {
  plans: Plan[];
  streak: number;
}

/* ------------------------------------------------------------------- chart */

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}
export interface ChartSeries {
  kind: "line" | "histogram";
  pane: string | number;
  color: string;
  title: string;
  lineWidth?: number;
  data: { time: number; value: number; color?: string }[];
}
export interface Quote {
  symbol: string;
  price: number;
  ts: string;
  change_pct: number | null;
  volume: number | null;
  source: string;
  age_min: number;
  /** Raw feed value: says "realtime" where the UI says "live" -- pass through normFreshness(). */
  freshness: Freshness | "realtime";
}
export interface ChartResponse {
  symbol: string;
  interval: string;
  candles: Candle[];
  series: ChartSeries[];
  levels: { label: string; price: number; color: string }[];
  quote: Quote | null;
  levels_from: string | null;
  levels_stale: boolean;
  cpr_verdict: string;
  market_open: boolean;
}
export interface IndicatorsResponse {
  indicators: { id: string; label: string; pane: string }[];
}

/* -------------------------------------------------------------------- news */

export interface NewsItem {
  title: string;
  url: string;
  source: string;
  feed: string;
  ts: string | null;
  age_min: number | null;
  score: number;
}
export interface MarketNewsResponse {
  market: string;
  items: NewsItem[];
  feeds: number;
  query: string;
}
export interface TickerNewsResponse {
  symbol: string;
  items: NewsItem[];
}
export interface NewsBotHit {
  symbol: string;
  change_pct: number;
  move_atr: number;
  news: NewsItem[];
  explained: boolean;
}
export interface NewsBotResponse {
  status: { watching: number; move_atr: number; last_scan_min: number | null; scanning: boolean };
  hits: NewsBotHit[];
}

/* ---------------------------------------------------------------------- AI */

export interface AskInput {
  question: string;
  symbols?: string[];
  market?: string;
  /** Recent turns, oldest first, so follow-up questions keep their thread. */
  history?: { role: "user" | "kes"; text: string }[];
}
export type AskResponse = { answer: string; symbols: string[] } | { error: string };

/* ------------------------------------------------------------------- paths */

const qs = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const out = s.toString();
  return out ? `?${out}` : "";
};
const seg = (s: string) => encodeURIComponent(s);

/** Path builders. Pass the result to useApi() or apiGet(). */
export const paths = {
  marketLine: () => "/api/market-line",
  setups: (symbol?: string) => `/api/setups${qs({ symbol })}`,
  portfolioStatus: () => "/api/portfolio/status",
  portfolioSummary: () => "/api/portfolio/summary",
  positions: (account?: string) => `/api/portfolio/positions${qs({ account })}`,
  performance: (period: PerformancePeriod) => `/api/portfolio/performance${qs({ period })}`,
  transactions: () => "/api/portfolio/transactions",
  brief: (earningsWithinDays = 30) => `/api/portfolio/brief${qs({ earnings_within_days: earningsWithinDays })}`,
  disclosures: (type: DisclosureType) => `/api/disclosures${qs({ type })}`,
  insiders: (q: InsidersQuery = {}) =>
    `/api/insiders${qs({
      days: q.days,
      side: q.side,
      min_value: q.min_value,
      notable_only: q.notable_only ? "true" : undefined,
      ceo_only: q.ceo_only ? "true" : undefined,
      mine: q.mine ? "true" : undefined,
      symbols: q.symbols,
    })}`,
  kesBriefing: () => "/api/kes/briefing",
  plans: () => "/api/plans",
  chart: (symbol: string, o: { interval?: string; lookback?: string; ind?: string[] } = {}) =>
    `/api/chart/${seg(symbol)}${qs({ interval: o.interval, lookback: o.lookback, ind: o.ind?.join(",") })}`,
  indicators: () => "/api/indicators",
  marketNews: (o: { limit?: number; market?: string } = {}) => `/api/news/market${qs(o)}`,
  tickerNews: (symbol: string, o: { limit?: number; market?: string; rank?: "recent" | string } = {}) =>
    `/api/news/ticker/${seg(symbol)}${qs(o)}`,
  newsBot: () => "/api/news/bot",
  aiAsk: () => "/api/ai/ask",
} as const;

/* ------------------------------------------------------------------ errors */

/**
 * status 0 = the backend could not be reached at all (down, CORS, offline).
 * Otherwise the HTTP status, with the backend's own `error` message when it sent one.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly body: unknown;
  constructor(message: string, status: number, path: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
    this.body = body;
  }
  get unreachable() {
    return this.status === 0;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(`Backend not reachable at ${BACKEND_LABEL}`, 0, path);
  }
  const text = await res.text();
  let body: unknown = undefined;
  let isJson = false;
  if (text) {
    try {
      body = JSON.parse(text);
      isJson = true;
    } catch {
      if (res.ok) throw new ApiError(`Invalid JSON from ${path}`, res.status, path, text);
    }
  }
  // Through the proxy a down backend is a non-JSON 5xx from Next, not a network
  // error. The backend itself always answers errors in JSON, so this is unreachable.
  if (!res.ok && res.status >= 500 && !isJson) {
    throw new ApiError(`No response from the backend at ${BACKEND_LABEL}: it is down or the request timed out`, 0, path);
  }
  if (!res.ok) {
    const msg =
      body && typeof body === "object" && "error" in body && typeof (body as { error: unknown }).error === "string"
        ? (body as { error: string }).error
        : `${res.status} ${res.statusText || "error"} from ${path}`;
    throw new ApiError(msg, res.status, path, body);
  }
  return body as T;
}

export const apiGet = <T>(path: string) => request<T>(path);
export const apiPost = <T>(path: string, payload: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(payload) });

/** Convenience writers. */
export const savePlan = (plan: PlanInput) => apiPost<SavedPlanResponse>(paths.plans(), plan);
export const askKes = (input: AskInput) => apiPost<AskResponse>(paths.aiAsk(), input);
