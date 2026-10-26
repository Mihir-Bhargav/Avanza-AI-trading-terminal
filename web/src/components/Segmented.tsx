"use client";
/**
 * Segmented control as an accessible tablist (arrow keys, Home/End, roving
 * tabindex). Used for timeframes, portfolio periods, news filters, filing types.
 *
 *   <Segmented ariaLabel="Period" value={p} onChange={setP}
 *     options={[{ value: "1d", label: "1D" }, ...]} mono />
 *
 * `mono` uses Geist Mono (codes like 15m, 1D); `size` sm = 30px buttons
 * (chart/disclosures), md = 32px (portfolio/news). If the segments control a
 * panel, pass `controls` (the panel id) and give that panel role="tabpanel".
 */
import { useRef, type KeyboardEvent } from "react";
import { cx } from "@/lib/cx";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  /** Accessible name when the visible label is terse (e.g. "1W" -> "1 week"). */
  ariaLabel?: string;
  disabled?: boolean;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  mono = false,
  size = "md",
  surface = "rail",
  controls,
  className,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  mono?: boolean;
  size?: "sm" | "md";
  /** Track colour: "rail" (#0E1115, inside panels) or "surface" (#12151A, on the page ground). */
  surface?: "rail" | "surface";
  controls?: string;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0);

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const pos = enabled.indexOf(index);
    let next: number | undefined;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = enabled[(pos + 1) % enabled.length];
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = enabled[(pos - 1 + enabled.length) % enabled.length];
    else if (e.key === "Home") next = enabled[0];
    else if (e.key === "End") next = enabled[enabled.length - 1];
    if (next === undefined) return;
    e.preventDefault();
    refs.current[next]?.focus();
    onChange(options[next].value);
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cx(
        "inline-flex items-center border border-line p-[3px]",
        surface === "rail" ? "bg-rail" : "bg-surface",
        size === "sm" ? "rounded-[9px]" : "rounded-control",
        className,
      )}
    >
      {options.map((o, i) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={controls}
            aria-label={o.ariaLabel}
            tabIndex={selected ? 0 : -1}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={cx(
              "cursor-pointer border-0 transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              size === "sm" ? "h-[30px] min-w-11 rounded-chip px-2.5" : "h-8 min-w-[46px] rounded-[7px] px-3.5",
              mono ? "num text-xs" : "text-[13px]",
              selected ? "bg-seg-on text-text" : "bg-transparent text-muted hover:text-text-2",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
