---
name: portfolio-brief
description: On-demand, read-only portfolio brief for a brokerage account exposed through the portfolio MCP server — P&L, concentration, FX exposure, upcoming earnings for holdings, and news behind notable moves. Use when the user asks for a portfolio brief (daily or weekly), "how is my portfolio", or what is moving in their holdings. Never scheduled; runs only when asked. Never places, suggests placing, or prepares an order.
---

# Portfolio brief

Argument: `daily` (default) or `weekly`.

## Hard rules

- **Read-only, always.** Never place, modify or cancel an order, and never call a
  tool that could. Only an explicit, unambiguous instruction from the user could
  change this, and the skill does not assume one.
- **Every number comes from `get_brief_data`.** Do not compute weights, percentages,
  totals or dates yourself. Quote the tool's fields. If a number is not there, say
  it is not available rather than deriving it.
- **Nothing leaves the chat.** Do not write the brief, amounts or holdings into any
  file in the repository. Save to a location outside the repo only if the user
  names one.
- **No silent gaps.** If a tool fails or returns nothing (earnings lookup, news),
  say so in the brief. Do not omit the section.

## Steps

1. Call `avanza-portfolio` → `get_brief_data` (`earnings_within_days`: 30 for
   daily, 45 for weekly).
2. For **weekly**, also call `get_transactions` with `from_date` = 7 days ago. List
   trades and sum `commission` per trade. Quote each one. State the total as
   "commissions paid this week" only if every trade has a commission value.
3. **News, targeted, not a firehose.** Fetch news only for holdings in `flags` (big
   day move, deep loss) or in `earnings.upcoming`, plus the top 3 holdings by weight:
   - stocks: `yahoo-finance` → `get_yahoo_finance_news`
   - market context: `efn-news` → `get_latest_news` or `get_market_commentary`
     (one call; skim for anything touching holdings or currency and rates)

   For each flagged move, find the actual catalyst. If you cannot find one, write
   "no identifiable catalyst found". Do not invent a reason.
4. Write the brief in the format below.

## Format

```
PORTFOLIO BRIEF — <daily|weekly> — <as_of>

Value <portfolio> <currency> · invested <invested> · cash <cash> (<cash_pct>%)
Unrealized <unrealized_pnl> <currency> (<unrealized_pnl_pct>%)
1d <insights_total> · 1w <change> (<pct>%) · 1m … · ytd …

MOVERS & FLAGS
- <name> <day_change_pct>% today — <catalyst, or "no identifiable catalyst">
- <name> <pnl_pct>% unrealized — <one line: thesis intact / broken / unknown>
- stale prices: <list, or none>

CONCENTRATION
Top holding <name> <top1>% of invested · top 3 <top3>%
By type: … · By currency: … 

EARNINGS AHEAD (<within_days>d)
- <ticker> <date> (in <n> days), or "none"; list lookup failures explicitly

NEWS THAT MATTERS
- 2–5 bullets, each tied to a specific holding or to currency and rates. Source-linked.

WEEK IN TRADES (weekly only)
- <date> <BUY/SELL> <instrument>, commission <x> <currency>

WORTH A LOOK (optional, max 2)
- Observations only, e.g. "<name> is 3% of invested and down 15%: earnings in 12
  days decides whether the thesis holds." No buy or sell instructions. If the user
  asks about acting on one, apply the repository's trading rules first (take-profit
  and stop-loss before entry, leverage cap, earnings check).
```

Keep it tight. A daily brief should read in under a minute.
