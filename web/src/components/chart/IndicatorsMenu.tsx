"use client";
/**
 * "Indicators · N" button with a popover listing /api/indicators, grouped by
 * where each one draws: on the price pane (overlays, volume) or in its own pane.
 */
import { useEffect, useId, useRef, useState } from "react";
import { describeError } from "@/components/StateView";
import type { IndicatorsResponse } from "@/lib/api";
import { paths } from "@/lib/api";
import { cx } from "@/lib/cx";
import { useApi } from "@/lib/useApi";

export function IndicatorsMenu({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const id = useId();
  const { data, error, isLoading, mutate } = useApi<IndicatorsResponse>(open ? paths.indicators() : null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = (ind: string) => onChange(value.includes(ind) ? value.filter((v) => v !== ind) : [...value, ind]);
  const list = data?.indicators ?? [];
  const groups = [
    { title: "PRICE PANE", items: list.filter((i) => i.pane === "overlay" || i.pane === "vol") },
    { title: "SEPARATE PANES", items: list.filter((i) => i.pane !== "overlay" && i.pane !== "vol") },
  ];

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={cx(
          "h-[38px] cursor-pointer rounded-[9px] border border-line-3 bg-transparent px-3.5 text-[13px] text-text-2 transition-colors hover:bg-raised",
          open && "bg-raised",
        )}
      >
        Indicators · <span className="num">{value.length}</span>
      </button>
      {open ? (
        <div
          id={id}
          role="dialog"
          aria-label="Indicators"
          className="absolute left-0 top-[44px] z-30 w-[280px] rounded-panel border border-line bg-surface p-2 shadow-[0_12px_32px_rgba(0,0,0,0.45)]"
        >
          {isLoading ? (
            <p className="m-0 px-3 py-3 text-xs text-muted">Loading indicators…</p>
          ) : error && !data ? (
            <div role="alert" className="flex items-center gap-3 px-3 py-3 text-xs text-warn-text">
              <span className="flex-1">{describeError(error).message}</span>
              <button type="button" className="cursor-pointer text-amber" onClick={() => mutate()}>
                Retry
              </button>
            </div>
          ) : (
            groups.map((g) =>
              g.items.length ? (
                <fieldset key={g.title} className="m-0 border-0 p-0 pb-1">
                  <legend className="num px-3 pb-1 pt-2 text-[10px] tracking-[1px] text-faint">{g.title}</legend>
                  {g.items.map((i) => {
                    const on = value.includes(i.id);
                    return (
                      <label
                        key={i.id}
                        className="flex h-8 cursor-pointer items-center gap-2.5 rounded-lg px-3 text-[13px] text-text-2 hover:bg-raised"
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggle(i.id)}
                          className="h-3.5 w-3.5 accent-[var(--amber)]"
                        />
                        <span className="flex-1">{i.label}</span>
                        <span className="num text-[10px] text-faint">{i.id}</span>
                      </label>
                    );
                  })}
                </fieldset>
              ) : null,
            )
          )}
        </div>
      ) : null}
    </div>
  );
}
