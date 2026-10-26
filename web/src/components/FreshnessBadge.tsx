/**
 * Data-age badge, shown once per panel (System.dc.html):
 *   LIVE · 1M   DELAYED 15M   CLOSED · LAST 17:30   STALE · 42M   AGE UNKNOWN
 * `ageMin` is minutes since the value was produced. `closedAt` (e.g. "17:30")
 * adds the last-trade time to the closed state. `suffix` appends text such as
 * "OLD" ("LIVE · 1M OLD" on the chart header).
 */
import type { Freshness } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtAge } from "@/lib/format";

const style: Record<Freshness, string> = {
  live: "bg-up/12 text-up",
  delayed: "bg-amber/14 text-amber",
  closed: "bg-raised text-soft",
  stale: "bg-down/12 text-down-soft",
  unknown: "bg-raised text-muted",
};

const spoken: Record<Freshness, string> = {
  live: "Live data",
  delayed: "Delayed data",
  closed: "Market closed",
  stale: "Stale data",
  unknown: "Data age unknown",
};

export function freshnessText(freshness: Freshness, ageMin?: number | null, closedAt?: string): string {
  const age = ageMin == null ? null : fmtAge(ageMin).toUpperCase();
  switch (freshness) {
    case "live":
      return age ? `LIVE · ${age}` : "LIVE";
    case "delayed":
      return age ? `DELAYED ${age}` : "DELAYED";
    case "closed":
      return closedAt ? `CLOSED · LAST ${closedAt}` : "CLOSED";
    case "stale":
      return age ? `STALE · ${age}` : "STALE";
    default:
      return "AGE UNKNOWN";
  }
}

export function FreshnessBadge({
  freshness,
  ageMin,
  closedAt,
  suffix,
  className,
}: {
  freshness: Freshness;
  ageMin?: number | null;
  closedAt?: string;
  suffix?: string;
  className?: string;
}) {
  const text = freshnessText(freshness, ageMin, closedAt) + (suffix ? ` ${suffix}` : "");
  const label = `${spoken[freshness]}${ageMin != null ? `, ${fmtAge(ageMin)} old` : ""}`;
  return (
    <span
      className={cx(
        "num inline-flex items-center whitespace-nowrap rounded-[5px] px-2 py-1 text-[10px] leading-none tracking-[0.8px]",
        style[freshness],
        className,
      )}
      title={label}
    >
      <span aria-hidden="true">{text}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
