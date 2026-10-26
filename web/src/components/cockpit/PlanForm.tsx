"use client";
/**
 * "Before you enter" checklist. Records a trade PLAN (target, stop, side,
 * leverage) through POST /api/plans. It is a note of intent: nothing here
 * places, modifies or cancels an order, and the copy says so.
 */
import { useState, type FormEvent } from "react";
import { useSWRConfig } from "swr";
import { Button } from "@/components/Button";
import { Segmented } from "@/components/Segmented";
import { describeError } from "@/components/StateView";
import type { SavedPlanResponse, SetupRow } from "@/lib/api";
import { paths, savePlan } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtLev, fmtPrice } from "@/lib/format";

type Side = "long" | "short";

function parse(v: string): number | null {
  const n = Number(v.replace(",", ".").replace(/\s/g, ""));
  return v.trim() !== "" && Number.isFinite(n) ? n : null;
}

function Check({ ok }: { ok: boolean }) {
  return ok ? (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--up)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12l5 5L20 7" />
    </svg>
  ) : (
    <span aria-hidden="true" className="inline-block h-3.5 w-3.5 rounded-[4px] border border-line-3" />
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  ok,
  suffix,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  ok: boolean;
  suffix?: string;
}) {
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1">
      <span className="flex items-center gap-1.5 text-xs text-muted">
        <Check ok={ok} />
        {label}
      </span>
      <span className="flex h-8 items-center rounded-lg border border-line-2 bg-rail px-2.5 focus-within:border-amber">
        <input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="num w-full min-w-0 border-0 bg-transparent text-[13px] text-text outline-none"
        />
        {suffix ? <span className="num text-[11px] text-faint">{suffix}</span> : null}
      </span>
    </label>
  );
}

export function PlanForm({ row, price }: { row: SetupRow; price: number | null }) {
  const { mutate } = useSWRConfig();
  const [side, setSide] = useState<Side>(row.trend === "down" ? "short" : "long");
  const [tp, setTp] = useState("");
  const [sl, setSl] = useState("");
  const [lev, setLev] = useState("1");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: true; plan: SavedPlanResponse } | { ok: false; message: string } | null>(null);

  const tpN = parse(tp);
  const slN = parse(sl);
  const levN = parse(lev);
  const cap = row.lev_cap;
  const levOver = levN != null && cap != null && levN > cap;
  const earnSoon = row.earnings_days != null && row.earnings_days <= 7;
  const ready = tpN != null && tpN > 0 && slN != null && slN > 0 && levN != null && levN > 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const plan = await savePlan({ symbol: row.symbol, side, take_profit: tpN!, stop_loss: slN!, leverage: levN! });
      setResult({ ok: true, plan });
      setTp("");
      setSl("");
      void mutate(paths.plans());
      void mutate(paths.kesBriefing());
    } catch (err) {
      setResult({ ok: false, message: describeError(err).message });
    } finally {
      setBusy(false);
    }
  };

  const ph = price ?? row.close;
  return (
    <form onSubmit={submit} aria-describedby="plan-note">
      <fieldset className="m-0 flex flex-col gap-2 rounded-control border border-line-2 px-3.5 pb-3 pt-1">
        <legend className="px-1.5 text-xs text-muted">Before you enter</legend>
        <div className="flex items-center gap-3">
          <Segmented<Side>
            ariaLabel="Side"
            size="sm"
            value={side}
            onChange={setSide}
            options={[
              { value: "long", label: "Long" },
              { value: "short", label: "Short" },
            ]}
          />
          <span className="num ml-auto text-[11px] text-faint">last {fmtPrice(ph)}</span>
        </div>
        <div className="grid grid-cols-3 gap-2.5">
          <Field id="plan-tp" label="Take-profit" value={tp} onChange={setTp} placeholder={side === "long" ? "above last" : "below last"} ok={tpN != null && tpN > 0} />
          <Field id="plan-sl" label="Stop-loss" value={sl} onChange={setSl} placeholder={side === "long" ? "below last" : "above last"} ok={slN != null && slN > 0} />
          <Field id="plan-lev" label="Leverage" value={lev} onChange={setLev} placeholder="1" ok={levN != null && levN > 0 && !levOver} suffix="x" />
        </div>
        <div className={cx("num text-[11px]", levOver ? "text-warn-text" : "text-faint")} role={levOver ? "alert" : undefined}>
          {cap == null
            ? "No leverage cap: ATR unavailable."
            : levOver
              ? `${fmtLev(levN)} is above the ${fmtLev(cap)} cap (100 / (3.5 × ATR%)).`
              : `Cap ${fmtLev(cap)} = 100 / (3.5 × ${row.atr_pct.toFixed(2)}% ATR).`}
        </div>
        {earnSoon ? (
          <div className="flex gap-2.5 rounded-lg bg-down/10 px-2.5 py-2 text-xs leading-snug text-warn-text">
            <span className="num font-semibold" aria-hidden="true">
              !
            </span>
            <span>
              Earnings in {row.earnings_days} day{row.earnings_days === 1 ? "" : "s"}
              {row.earnings_date ? ` (${row.earnings_date})` : ""}. ATR is backward-looking and understates a binary print.
            </span>
          </div>
        ) : null}
        <div className="mt-1 flex items-center gap-3">
          <Button type="submit" variant="outlineAmber" size="md" disabled={!ready || busy} className="h-8 shrink-0 px-4 text-[13px]">
            {busy ? "Logging…" : "Log plan"}
          </Button>
          <p id="plan-note" className="m-0 text-[11px] leading-snug text-faint">
            Logs your plan. Range never places orders.
          </p>
        </div>
        {result ? (
          result.ok ? (
            <p role="status" className="m-0 text-xs text-up">
              Plan logged for {result.plan.symbol} · streak {result.plan.streak}
              {result.plan.checked_against ? <span className="text-faint"> · checked against {result.plan.checked_against}</span> : null}
            </p>
          ) : (
            <p role="alert" className="m-0 text-xs text-warn-text">
              {result.message}
            </p>
          )
        ) : null}
      </fieldset>
    </form>
  );
}
