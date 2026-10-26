"use client";
/** Last ten transactions, newest first, with courtage shown on every trade. */
import type { ApiError, Transaction, TransactionsResponse } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtNumber, fmtPrice, fmtSigned, signOf } from "@/lib/format";
import { Chip, type ChipTone } from "../Chip";
import { StateView } from "../StateView";
import { fmtShortDate, humanType } from "./util";

const TYPE_TONE: Record<string, ChipTone> = { BUY: "up", SELL: "down", DIVIDEND: "zone" };

function money(v: number | null, unit: string | null, signed = false) {
  if (v == null) return "—";
  const s = signed ? fmtSigned(v, Math.abs(v) >= 100 ? 0 : 2) : fmtNumber(v, Math.abs(v) >= 100 ? 0 : 2);
  return unit ? `${s} ${unit}` : s;
}

function Row({ t }: { t: Transaction }) {
  const detail =
    t.quantity != null && t.price != null ? `${fmtNumber(t.quantity, t.quantity % 1 ? 2 : 0)} × ${fmtPrice(t.price)} ${t.price_unit ?? ""}`.trim() : null;
  const courtage =
    t.commission == null ? null : `courtage ${fmtNumber(t.commission, t.commission % 1 ? 2 : 0)}${t.commission_unit ? ` ${t.commission_unit}` : ""}`;
  return (
    <li className={cx("flex flex-col gap-1 border-t border-raised px-5 py-2.5", t.cancelled && "opacity-50")}>
      <div className="flex items-center gap-2.5 text-[13px]">
        <span className="num w-[46px] shrink-0 text-xs text-muted">{fmtShortDate(t.date)}</span>
        <Chip tone={TYPE_TONE[t.type] ?? "neutral"}>{humanType(t.type)}</Chip>
        <span
          className={cx("min-w-0 flex-1 truncate text-text-2", t.cancelled && "line-through")}
          title={t.instrument ?? t.description ?? undefined}
        >
          {t.instrument ?? t.description ?? "—"}
        </span>
        <span className={cx("num shrink-0 text-right", signOf(t.amount) > 0 ? "text-up" : "text-text-2")}>
          {money(t.amount, t.amount_unit, true)}
        </span>
      </div>
      <div className="num flex gap-2 pl-[56px] text-[10px] tracking-[0.4px] text-faint">
        <span className="min-w-0 flex-1 truncate">
          {t.account}
          {detail ? ` · ${detail}` : ""}
          {t.cancelled ? " · CANCELLED" : ""}
        </span>
        {courtage ? <span className="shrink-0">{courtage}</span> : null}
      </div>
    </li>
  );
}

export function RecentActivity({
  data,
  error,
  onRetry,
}: {
  data: TransactionsResponse | undefined;
  error: ApiError | undefined;
  onRetry: () => void;
}) {
  const rows = data
    ? [...data.transactions].sort((a, b) => (b.date ?? "").localeCompare(a.date ?? "")).slice(0, 10)
    : [];
  const courtage = rows.reduce((s, t) => s + (t.commission_unit === "SEK" && !t.cancelled ? t.commission ?? 0 : 0), 0);
  return (
    <section aria-labelledby="act-h" className="flex flex-col overflow-hidden rounded-[16px] border border-line bg-surface pb-1">
      <div className="flex items-baseline gap-2.5 px-5 pb-2.5 pt-4">
        <h2 id="act-h" className="m-0 text-sm font-semibold text-text">
          Recent activity
        </h2>
        {data ? (
          <span className="num text-xs text-muted">
            last {rows.length}
            {courtage > 0 ? ` · ${fmtNumber(courtage, courtage % 1 ? 2 : 0)} SEK courtage` : ""}
          </span>
        ) : null}
      </div>
      {!data ? (
        error ? (
          <StateView kind="error" error={error} onRetry={onRetry} compact />
        ) : (
          <StateView kind="loading" title="Reading transactions" compact />
        )
      ) : rows.length === 0 ? (
        <StateView kind="empty" title="No transactions" message="Avanza returned no transactions for these accounts." compact />
      ) : (
        <ul className="m-0 list-none p-0" aria-label="Recent transactions">
          {rows.map((t, i) => (
            <Row key={`${t.date}-${t.instrument}-${i}`} t={t} />
          ))}
        </ul>
      )}
    </section>
  );
}
