/**
 * Command-bar grammar (Bloomberg-style "TICKER FUNCTION"):
 *   HOME | MAP | PORT | N | DISC | GP  -> that page (GP alone opens the default symbol)
 *   BULL X2 AMD | MINI L OMX | MINI     -> Avanza finder (certificates/minis ranked by spread)
 *   MU | MU GP                          -> chart for MU
 *   NVDA N | NVDA DISC                  -> news / disclosures filtered to NVDA
 *   ERIC B GP                           -> multi-word tickers are allowed before the code
 */

export const DEFAULT_SYMBOL = "MU";

export const routes = {
  home: "/terminal",
  markets: "/terminal/markets",
  chart: (symbol: string = DEFAULT_SYMBOL) => `/terminal/chart/${encodeURIComponent(symbol)}`,
  portfolio: "/terminal/portfolio",
  news: (symbol?: string) => (symbol ? `/terminal/news?symbol=${encodeURIComponent(symbol)}` : "/terminal/news"),
  avanza: (q?: string) => (q ? `/terminal/avanza?q=${encodeURIComponent(q)}` : "/terminal/avanza"),
  disclosures: (symbol?: string) =>
    symbol ? `/terminal/disclosures?symbol=${encodeURIComponent(symbol)}` : "/terminal/disclosures",
} as const;

const CODES = ["HOME", "MAP", "GP", "PORT", "N", "DISC", "MINI"] as const;

// Avanza product names. A query starting with one is an instrument search, not a ticker.
const PRODUCT_WORDS = ["BULL", "BEAR", "MINI", "TURBO", "UNLIMITED"];
type Code = (typeof CODES)[number];

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9 .\-^=&]{0,23}$/;

export type CommandResult = { ok: true; href: string } | { ok: false; error: string };

export function parseCommand(raw: string): CommandResult {
  const tokens = raw.trim().toUpperCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return { ok: false, error: "Type a ticker or a code, e.g. MU GP, PORT, N" };
  if (tokens.length > 1 && PRODUCT_WORDS.includes(tokens[0])) {
    return { ok: true, href: routes.avanza(raw.trim().replace(/\s+/g, " ")) };
  }

  const last = tokens[tokens.length - 1];
  const code = (CODES as readonly string[]).includes(last) ? (last as Code) : null;
  const symbol = (code ? tokens.slice(0, -1) : tokens).join(" ");

  if (symbol && !SYMBOL_RE.test(symbol)) return { ok: false, error: `"${symbol}" doesn't look like a ticker` };

  switch (code) {
    case "HOME":
      return { ok: true, href: routes.home };
    case "MAP":
      return { ok: true, href: routes.markets };
    case "MINI":
      return { ok: true, href: routes.avanza(symbol || undefined) };
    case "PORT":
      return { ok: true, href: routes.portfolio };
    case "N":
      return { ok: true, href: routes.news(symbol || undefined) };
    case "DISC":
      return { ok: true, href: routes.disclosures(symbol || undefined) };
    case "GP":
      return { ok: true, href: routes.chart(symbol || DEFAULT_SYMBOL) };
    default:
      return { ok: true, href: routes.chart(symbol) };
  }
}
