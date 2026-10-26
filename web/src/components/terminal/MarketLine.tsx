"use client";
/**
 * Market line under the header. Polls /api/market-line every 15 s. Each item
 * shows its own freshness when it is not live; the right edge shows when the
 * line was computed. Backend down -> an explicit error, never blank or zeros.
 */
import type { ReactNode } from "react";
import { useApi } from "@/lib/useApi";
import { paths, BACKEND_LABEL, type MarketLineItem, type MarketLineResponse } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtAge, fmtClock, fmtPct, fmtPrice } from "@/lib/format";

function ItemTag({ item }: { item: MarketLineItem }) {
  const age = item.age_min == null ? "" : fmtAge(item.age_min).toUpperCase();
  switch (item.freshness) {
    case "live":
      return null;
    case "delayed":
      return <span className="text-amber">{age || "DELAYED"}</span>;
    case "stale":
      return <span className="text-down-soft">STALE{age ? ` ${age}` : ""}</span>;
    case "closed":
      return <span className="text-faint">CLOSED</span>;
    default:
      return <span className="text-faint">AGE ?</span>;
  }
}

function Item({ item }: { item: MarketLineItem }) {
  const chg = item.change_pct;
  return (
    <li className="flex shrink-0 items-center gap-1.5 text-muted">
      <span>{item.label}</span>
      <span className="text-text-2">{fmtPrice(item.last)}</span>
      <span className={cx(chg == null ? "text-faint" : chg > 0 ? "text-up" : chg < 0 ? "text-down" : "text-muted")}>
        {fmtPct(chg)}
      </span>
      <ItemTag item={item} />
    </li>
  );
}

export function MarketLine() {
  const { data, error, isLoading } = useApi<MarketLineResponse>(paths.marketLine(), { refreshInterval: 15_000 });

  let right: ReactNode = null;
  if (data && error) {
    right = (
      <span className="text-down-soft" role="status">
        UPDATE FAILED · SHOWING {fmtClock(data.as_of)}
      </span>
    );
  } else if (data) {
    const allLive = data.items.length > 0 && data.items.every((i) => i.freshness === "live");
    right = (
      <span className="text-faint">
        {allLive ? "ALL LIVE · " : ""}AS OF {fmtClock(data.as_of, true)} · POLL 15S
      </span>
    );
  }

  return (
    <div
      aria-label="Market line"
      role="region"
      className="num flex h-[30px] shrink-0 items-center gap-[22px] overflow-hidden whitespace-nowrap border-b border-line bg-rail px-6 text-[11px]"
    >
      {data ? (
        data.items.length ? (
          <ul className="m-0 flex min-w-0 list-none gap-[22px] overflow-hidden p-0">
            {data.items.map((it) => (
              <Item key={it.key} item={it} />
            ))}
          </ul>
        ) : (
          <span className="text-faint">NO MARKETS CONFIGURED</span>
        )
      ) : error ? (
        <span role="alert" className="flex min-w-0 items-center gap-2 truncate text-down-soft">
          <span aria-hidden="true" className="h-[7px] w-[7px] shrink-0 rounded-full bg-down" />
          {error.unreachable
            ? `MARKET LINE UNAVAILABLE · BACKEND NOT REACHABLE AT ${BACKEND_LABEL.toUpperCase()} · RETRYING`
            : `MARKET LINE FAILED · ${error.message.toUpperCase()}`}
        </span>
      ) : isLoading ? (
        <span className="text-faint" role="status">
          LOADING MARKET LINE…
        </span>
      ) : null}
      {right ? <span className="ml-auto shrink-0 pl-4">{right}</span> : null}
    </div>
  );
}
