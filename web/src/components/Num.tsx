/**
 * Mono, tabular number. Either pass `value` + `kind` to format, or children
 * that are already formatted. `colored` tints by sign (up/down tokens, so it
 * follows colour-safe mode); `tone` forces a colour.
 *
 *   <Num value={0.79} kind="pct" colored />      -> +0.79% (green)
 *   <Num value={3291.07} kind="price" />          -> 3 291.07
 *   <Num value={-0.28} kind="atr" />              -> −0.28 ATR
 *   <Num value={0.55} kind="fracPct" />           -> 55%
 *   <Num tone="muted">n=76</Num>
 */
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import {
  fmtAtr,
  fmtFracPct,
  fmtLev,
  fmtNumber,
  fmtPct,
  fmtPrice,
  fmtSEK,
  fmtSigned,
  signOf,
} from "@/lib/format";

export type NumKind = "number" | "signed" | "price" | "pct" | "fracPct" | "sek" | "atr" | "lev";
export type Tone = "default" | "strong" | "muted" | "faint" | "up" | "down" | "amber" | "zone";

const toneClass: Record<Tone, string> = {
  default: "",
  strong: "text-text",
  muted: "text-muted",
  faint: "text-faint",
  up: "text-up",
  down: "text-down",
  amber: "text-amber",
  zone: "text-zone",
};

function format(value: number | null | undefined, kind: NumKind, decimals?: number, signed?: boolean): string {
  switch (kind) {
    case "signed":
      return fmtSigned(value, decimals ?? 2);
    case "price":
      return fmtPrice(value, decimals);
    case "pct":
      return fmtPct(value, decimals ?? 2, signed ?? true);
    case "fracPct":
      return fmtFracPct(value, decimals ?? 0, signed ?? false);
    case "sek":
      return fmtSEK(value, { decimals: decimals ?? 0, signed });
    case "atr":
      return fmtAtr(value, decimals ?? 2);
    case "lev":
      return fmtLev(value, decimals ?? 1);
    default:
      return signed ? fmtSigned(value, decimals ?? 2) : fmtNumber(value, decimals ?? 2);
  }
}

export function Num({
  value,
  kind = "number",
  decimals,
  signed,
  colored = false,
  tone,
  className,
  children,
}: {
  value?: number | null;
  kind?: NumKind;
  decimals?: number;
  signed?: boolean;
  colored?: boolean;
  tone?: Tone;
  className?: string;
  children?: ReactNode;
}) {
  const s = signOf(value);
  const resolved: Tone = tone ?? (colored ? (s > 0 ? "up" : s < 0 ? "down" : "default") : "default");
  return (
    <span className={cx("num", toneClass[resolved], className)}>
      {children ?? format(value, kind, decimals, signed)}
    </span>
  );
}
