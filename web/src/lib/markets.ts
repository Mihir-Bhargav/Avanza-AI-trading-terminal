/**
 * Markets page (MAP): types for GET /api/markets/sectors (terminal/markets.py)
 * and the index choices shared by the TradingView heatmap and the sector cards.
 */
import type { Freshness } from "./api";

export type SectorIndex = "sp500" | "nasdaq100" | "dow30" | "omxs30";

export interface MarketIndexOption {
  value: string;
  label: string;
  ariaLabel?: string;
  /**
   * TradingView stock-heatmap `dataSource`. Each was verified by rendering the
   * widget in headless Chrome on 2026-09-24. An unknown value does NOT error:
   * the widget silently falls back to SPX500, so never guess one.
   */
  tvDataSource: string;
  /** Our sector overview for this index, or null when we have no curated list. */
  sectors: SectorIndex | null;
}

export const MARKET_INDEXES: MarketIndexOption[] = [
  { value: "sp500", label: "S&P 500", tvDataSource: "SPX500", sectors: "sp500" },
  { value: "nasdaq100", label: "Nasdaq 100", tvDataSource: "NASDAQ100", sectors: "nasdaq100" },
  { value: "dow30", label: "Dow 30", ariaLabel: "Dow Jones Industrial Average", tvDataSource: "DJDJI", sectors: "dow30" },
  { value: "russell2000", label: "Russell 2000", tvDataSource: "TVCRUT", sectors: null },
  { value: "omxs30", label: "OMXS30", ariaLabel: "OMX Stockholm 30", tvDataSource: "OMXS30", sectors: "omxs30" },
];

export interface SectorHeadline {
  title: string;
  source: string;
  age_min: number | null;
  url: string | null;
  /** The mover the headline was looked up for. */
  symbol: string;
}

export interface SectorMember {
  symbol: string;
  name: string;
  last: number | null;
  change_pct: number | null;
  /** Today's session closes, 5-minute bars downsampled to at most 40 points. */
  spark: number[];
  freshness: Freshness;
  age_min: number | null;
  ts: string | null;
  prev_close_source: "daily" | "intraday" | null;
  error?: string;
}

export interface SectorOverview {
  sector: string;
  etf: string | null;
  change_pct: number | null;
  /** "etf" = SPDR sector ETF move; "members_avg" = equal-weighted listed members. */
  change_basis: "etf" | "members_avg";
  members_avg_pct: number | null;
  etf_quote: { last: number | null; change_pct: number | null; freshness: Freshness; age_min: number | null } | null;
  top_mover: string | null;
  headline: SectorHeadline | null;
  headline_error: string | null;
  members: SectorMember[];
}

export interface SectorsResponse {
  as_of: string;
  index: SectorIndex;
  label: string;
  market: "us" | "sweden";
  /** Date of the curated membership snapshot (watchlists/sector_leaders.json). */
  membership_as_of: string | null;
  sources: { prices: string; headlines: string };
  errors: string[];
  sectors: SectorOverview[];
}

export const marketsPaths = {
  sectors: (index: SectorIndex) => `/api/markets/sectors?index=${encodeURIComponent(index)}`,
} as const;
