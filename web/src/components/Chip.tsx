/**
 * Small status tag (System.dc.html components row).
 *   amber   "Crossed Z1 ↑"      neutral "Near Z3"      zone "Earnings date"
 *   up / down tinted by sign     warn   soft red warning text
 * `mono` switches to Geist Mono for tickers and numbers.
 */
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export type ChipTone = "amber" | "neutral" | "zone" | "up" | "down" | "warn";

const tones: Record<ChipTone, string> = {
  amber: "bg-amber/14 text-amber",
  neutral: "bg-raised text-soft",
  zone: "bg-zone/14 text-zone-text",
  up: "bg-up/12 text-up",
  down: "bg-down/12 text-down-soft",
  warn: "bg-down/10 text-warn-text",
};

export function Chip({
  tone = "neutral",
  mono = false,
  className,
  children,
}: {
  tone?: ChipTone;
  mono?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-chip px-[9px] py-[3px] text-xs leading-[1.4]",
        mono && "num",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
