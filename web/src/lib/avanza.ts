/**
 * Types and paths for the Avanza instrument finder (existing backend routes in
 * terminal/app.py). Read-only: search, instrument metadata and price history.
 * Nothing here can place an order.
 */

export interface FinderRow {
  name: string;
  type: string;
  orderbook_id: string;
  market: string | null;
  currency: string | null;
  last: number | null;
  change_pct: number | null;
  spread: number | null;
  /** Percent units. Only meaningful when spread_known is true. */
  spread_pct: number | null;
  tradeable: boolean;
  /** False outside market hours: an unknown cost must never look cheap. */
  spread_known: boolean;
}
export interface FinderResponse {
  query: string;
  count: number;
  rows: FinderRow[];
}

export interface InstrumentDetail {
  orderbook_id: string;
  name: string;
  type: string;
  sub_type: string | null;
  direction: string | null;
  leverage: number | null;
  barrier: number | null;
  financing: number | null;
  parity: number | null;
  currency: string | null;
  last: number | null;
  bid: number | null;
  ask: number | null;
  spread: number | null;
  spread_pct: number | null;
  change_pct: number | null;
  is_realtime: boolean;
  updated_ms: number | null;
  tradeable: boolean;
  category: string | null;
  sub_category: string | null;
  /** Yahoo ticker of the underlying, when it can be resolved. */
  underlying: string | null;
  underlying_price: number | null;
  barrier_distance_pct: number | null;
  atrs_to_barrier: number | null;
  session_authenticated: boolean;
  error?: string;
}

export interface InstrumentChart {
  orderbook_id: string;
  name: string;
  candles: { time: number; open: number; high: number; low: number; close: number }[];
  line: { time: number; value: number }[];
  is_line: boolean;
  currency: string | null;
  is_realtime: boolean;
  prev_close: number | null;
  error?: string;
}

export const avanzaPaths = {
  find: (q: string) => `/api/avanza/find?q=${encodeURIComponent(q)}`,
  instrument: (oid: string) => `/api/avanza/instrument/${encodeURIComponent(oid)}`,
  chart: (oid: string) => `/api/avanza/chart/${encodeURIComponent(oid)}`,
};
