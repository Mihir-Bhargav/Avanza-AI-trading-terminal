"""
Shapes raw Avanza responses into what the MCP tools return.

Currency rule: Avanza reports position value, cost basis and account totals in
SEK, and prices in the instrument's own currency. Every holding carries both.
Totals are only ever summed over SEK amounts; any amount whose unit is not SEK
is reported separately, never added in.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .avanza_readonly import ReadOnlyAvanza

# ticker_map.json lists real holdings, so it is gitignored; the example ships.
_here = Path(__file__).parent
_map_file = _here / "ticker_map.json"
_TICKERS = json.loads((_map_file if _map_file.exists()
                       else _here / "ticker_map.example.json").read_text())["map"]

# tool period -> (overview performance key, insights timePeriod or None)
PERIODS = {
    "1d":  (None,           "TODAY"),
    "1w":  ("ONE_WEEK",     "ONE_WEEK"),
    "1m":  ("ONE_MONTH",    None),
    "3m":  ("THREE_MONTHS", None),
    "ytd": ("THIS_YEAR",    "THIS_YEAR"),
    "1y":  ("ONE_YEAR",     None),
    "3y":  ("THREE_YEARS",  "THREE_YEARS_ROLLING"),
    "all": ("ALL_TIME",     None),
}


def _v(q) -> float | None:
    return q.get("value") if isinstance(q, dict) else None


def _u(q) -> str | None:
    return q.get("unit") if isinstance(q, dict) else None


def _r(x, n=2):
    return None if x is None else round(x, n)


_TYPE_ALIAS = {"INVESTERINGSSPARKONTO": "ISK", "AKTIEFONDKONTO": "AF",
               "KAPITALFORSAKRING": "KF", "SPARKONTO": "SPARKONTO",
               "TJANSTEPENSION": "TJP", "PENSIONSFORSAKRING": "PENSION"}


def _user_name(acc: dict) -> str | None:
    """Only a name the user chose. Avanza's defaultName IS the account number,
    so it is never returned."""
    n = acc.get("name")
    n = n.get("userDefinedName") if isinstance(n, dict) else n
    return n if n and not str(n).strip().isdigit() else None


class Portfolio:
    """Account numbers never leave this class. Avanza's account `id` is the
    account number itself, so every tool speaks in aliases (ISK, AF, ...) and
    translates at the boundary."""

    def __init__(self, client: ReadOnlyAvanza | None = None):
        self.c = client or ReadOnlyAvanza()

    def _aliases(self) -> tuple[list[dict], dict[str, str]]:
        accs = self.c.fetch("overview").get("accounts", [])
        by_type = defaultdict(list)
        for a in sorted(accs, key=lambda a: str(a.get("id"))):
            by_type[_TYPE_ALIAS.get(a.get("type"), a.get("type") or "ACCOUNT")].append(a)
        id2alias = {}
        for base, group in by_type.items():
            for i, a in enumerate(group, 1):
                id2alias[a.get("id")] = base if len(group) == 1 else f"{base}-{i}"
        return accs, id2alias

    def _resolve(self, alias: str | None, id2alias: dict) -> str | None:
        if alias is None:
            return None
        for real, al in id2alias.items():
            if al.lower() == str(alias).lower():
                return real
        raise ValueError(f"unknown account '{alias}'; valid: {sorted(id2alias.values())}")

    # ---------------------------------------------------------- summary
    def account_summary(self) -> dict:
        accs, id2alias = self._aliases()
        out, tot, other = [], defaultdict(float), []
        for a in accs:
            row = {
                "account": id2alias[a.get("id")],
                "name": _user_name(a),
                "type": a.get("type"),
                "status": a.get("status"),
                "total_value": _v(a.get("totalValue")),
                "cash": _v(a.get("balance")),
                "buying_power": _v(a.get("buyingPower")),
                "buying_power_without_credit": _v(a.get("buyingPowerWithoutCredit")),
                "unit": _u(a.get("totalValue")),
            }
            out.append(row)
            for f in ("total_value", "cash", "buying_power"):
                if row[f] is None:
                    continue
                if row["unit"] == "SEK":
                    tot[f] += row[f]
                else:
                    other.append({"account": row["account"], "field": f,
                                  "value": row[f], "unit": row["unit"]})
        return {"accounts": out,
                "totals_sek": {k: _r(v) for k, v in tot.items()},
                "non_sek_amounts_not_in_totals": other}

    # -------------------------------------------------------- positions
    def positions(self, account: str | None = None) -> dict:
        _, id2alias = self._aliases()
        account_id = self._resolve(account, id2alias)
        raw = self.c.fetch("positions")
        rows = []
        for p in raw.get("withOrderbook", []) + raw.get("withoutOrderbook", []):
            acc, ins = p.get("account", {}), p.get("instrument", {})
            if account_id and acc.get("id") != account_id:
                continue
            ob = ins.get("orderbook") or {}
            q = ob.get("quote") or {}
            qty = _v(p.get("volume"))
            last = _v(q.get("latest"))
            factor = ins.get("volumeFactor") or 1.0
            value_sek = _v(p.get("value"))
            cost_sek = _v(p.get("acquiredValue"))
            value_ccy = qty * last * factor if qty is not None and last is not None else None
            pnl = value_sek - cost_sek if value_sek is not None and cost_sek is not None else None
            obid = ob.get("id")
            rows.append({
                "account": id2alias.get(acc.get("id"), "UNKNOWN"),
                "name": ob.get("name") or ins.get("name"),
                "instrument_type": ins.get("type"),
                "isin": ins.get("isin"),
                "orderbook_id": obid,
                "yahoo_ticker": _TICKERS.get(obid, {}).get("yahoo") if obid else None,
                "currency": ins.get("currency"),
                "quantity": qty,
                "last_price": last,
                "last_price_updated": q.get("updated"),
                "avg_cost": _v(p.get("averageAcquiredPriceInstrumentCurrency")),
                "avg_cost_sek": _v(p.get("averageAcquiredPrice")),
                "market_value": _r(value_ccy),
                "market_value_sek": value_sek,
                "cost_basis_sek": cost_sek,
                "pnl_sek": _r(pnl),
                "pnl_pct": _r(pnl / cost_sek * 100) if pnl is not None and cost_sek else None,
                "day_change_pct": _v((p.get("lastTradingDayPerformance") or {}).get("relative")),
                # SEK per unit of instrument currency, as Avanza priced it
                "implied_fx_to_sek": _r(value_sek / value_ccy, 4) if value_sek and value_ccy else None,
                "value_unit": _u(p.get("value")),
            })

        cash = [{"account": id2alias.get(c.get("account", {}).get("id"), "UNKNOWN"),
                 "cash": _v(c.get("totalBalance")),
                 "unit": _u(c.get("totalBalance"))}
                for c in raw.get("cashPositions", [])
                if not account_id or c.get("account", {}).get("id") == account_id]

        sek_rows = [r for r in rows if r["value_unit"] == "SEK" and r["market_value_sek"] is not None]
        total = sum(r["market_value_sek"] for r in sek_rows)
        by_ccy = defaultdict(float)
        for r in sek_rows:
            by_ccy[r["currency"]] += r["market_value_sek"]
        return {
            "positions": rows,
            "cash": cash,
            "totals_sek": {
                "market_value": _r(total),
                "cost_basis": _r(sum(r["cost_basis_sek"] or 0 for r in sek_rows)),
                "pnl": _r(sum(r["pnl_sek"] or 0 for r in sek_rows)),
            },
            # FX exposure: SEK value grouped by the currency each holding is priced in
            "exposure_by_currency_sek": {k: {"value": _r(v), "pct": _r(v / total * 100) if total else None}
                                         for k, v in sorted(by_ccy.items(), key=lambda kv: -kv[1])},
            "non_sek_positions_not_in_totals": [r["name"] for r in rows if r not in sek_rows],
        }

    # ----------------------------------------------------- transactions
    def transactions(self, account: str | None = None, from_date: str | None = None,
                     to_date: str | None = None, max_elements: int = 200) -> dict:
        _, id2alias = self._aliases()
        account_id = self._resolve(account, id2alias)
        query = {"maxElements": max(1, min(int(max_elements), 1000))}
        if from_date:
            query["from"] = date.fromisoformat(from_date).isoformat()
        if to_date:
            query["to"] = date.fromisoformat(to_date).isoformat()
        raw = self.c.fetch("transactions", query=query)
        out = []
        for t in raw.get("transactions", []):
            acc = t.get("account") or {}
            if account_id and acc.get("id") != account_id:
                continue
            ob = t.get("orderbook") or {}
            out.append({
                "date": t.get("date"),
                "trade_date": t.get("tradeDate"),
                "account": id2alias.get(acc.get("id"), "UNKNOWN"),
                "type": t.get("type"),
                "description": t.get("description"),
                "instrument": t.get("instrumentName") or ob.get("name"),
                "isin": t.get("isin") or ob.get("isin"),
                "orderbook_id": ob.get("id"),
                "quantity": _v(t.get("volume")),
                "price": _v(t.get("priceInTradedCurrency")),
                "price_unit": _u(t.get("priceInTradedCurrency")),
                "amount": _v(t.get("amount")),
                "amount_unit": _u(t.get("amount")),
                "commission": _v(t.get("commission")),
                "commission_unit": _u(t.get("commission")),
                "currency_rate": _v(t.get("currencyRate")),
                "cancelled": t.get("cancelled"),
            })
        return {"transactions": out, "count": len(out),
                "first_transaction_date": raw.get("firstTransactionDate")}

    # ------------------------------------------------------ performance
    def performance(self, period: str = "1m", account: str | None = None) -> dict:
        if period not in PERIODS:
            raise ValueError(f"period must be one of {list(PERIODS)}")
        ov_key, ins_key = PERIODS[period]
        accs, id2alias = self._aliases()
        account_id = self._resolve(account, id2alias)
        if account_id:
            accs = [a for a in accs if a.get("id") == account_id]

        per_account = []
        if ov_key:
            for a in accs:
                perf = (a.get("performance") or {}).get(ov_key) or {}
                per_account.append({
                    "account": id2alias[a.get("id")], "name": _user_name(a), "type": a.get("type"),
                    "change": _v(perf.get("absolute")), "change_unit": _u(perf.get("absolute")),
                    "change_pct": _v(perf.get("relative")),
                })

        result = {"period": period, "per_account": per_account,
                  "source": {"per_account": f"overview.{ov_key}" if ov_key else None,
                             "positions": f"insights.{ins_key}" if ins_key else None}}
        if not ov_key:
            result["note"] = "1d has no per-account figure in the overview; see insights below"

        if ins_key:
            ins = self.c.fetch("insights", body={"timePeriod": ins_key,
                                                 "accountIds": [a.get("id") for a in accs]})
            dev = ins.get("developmentResponse") or {}
            bw = dev.get("bestAndWorst") or {}

            def flat(groups):
                rows = []
                for g in groups or []:
                    for pos in g.get("positions", []):
                        o = pos.get("outcome") or {}
                        rows.append({"name": pos.get("shortName") or g.get("instrumentDisplayName"),
                                     "isin": pos.get("isin"),
                                     "instrument_type": g.get("instrumentType"),
                                     "outcome_sek": o.get("total"),
                                     "outcome_pct": o.get("totalDevelopmentInPercent"),
                                     "dividends_sek": o.get("dividends")})
                return rows

            tot = dev.get("totalOutcome") or {}
            result["insights"] = {
                "total_outcome_sek": tot.get("total"),
                "price_development_sek": tot.get("development"),
                "dividends_sek": tot.get("dividends"),
                "best": flat(bw.get("bestPositions")),
                "worst": flat(bw.get("worstPositions")),
            }
        else:
            result["insights"] = None
            result["insights_note"] = ("Avanza's insights report only supports 1d, 1w, "
                                       "ytd and 3y; per-position breakdown unavailable for this period")
        return result
