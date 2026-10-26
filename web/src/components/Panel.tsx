/**
 * Panel: the rounded surface every terminal section sits in.
 *   variant "default" surface #12151A / line #1F242C
 *           "kes"     slightly lifted #151A21 / #262D37 (Kes briefing, Kes notes)
 *           "chart"   rail colour #0E1115 (chart canvas)
 *   padded  adds the standard 16/20px padding (off by default so tables can run edge to edge)
 * Pass aria-labelledby (the PanelHeader title id) or aria-label.
 *
 * PanelHeader: title row.  <PanelHeader id="setups-h" title="Today's setups"
 *   tag="TTM POWER RANGE" right={<FreshnessBadge .../>} />
 *   level  heading level (default 2); size "md" 16px (default) | "sm" 14px
 */
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cx } from "@/lib/cx";

const variants = {
  default: "bg-surface border-line",
  kes: "bg-kes-surface border-kes-line",
  chart: "bg-rail border-line",
} as const;

export function Panel({
  variant = "default",
  padded = false,
  as: Tag = "section",
  className,
  children,
  ...rest
}: {
  variant?: keyof typeof variants;
  padded?: boolean;
  as?: "section" | "aside" | "div" | "article";
  className?: string;
  children: ReactNode;
} & Omit<ComponentPropsWithoutRef<"section">, "className" | "children">) {
  return (
    <Tag
      className={cx(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-panel border",
        variants[variant],
        padded && "px-5 py-4",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function PanelHeader({
  id,
  title,
  tag,
  right,
  level = 2,
  size = "md",
  className,
}: {
  id?: string;
  title: ReactNode;
  tag?: ReactNode;
  right?: ReactNode;
  level?: 1 | 2 | 3;
  size?: "sm" | "md";
  className?: string;
}) {
  const H = `h${level}` as "h1" | "h2" | "h3";
  return (
    <div className={cx("flex items-baseline gap-3 px-5 pb-3 pt-4", className)}>
      <H id={id} className={cx("m-0 font-semibold text-text", size === "md" ? "text-base" : "text-sm")}>
        {title}
      </H>
      {tag ? <span className="num text-[11px] tracking-[0.8px] text-amber">{tag}</span> : null}
      {right ? <div className="ml-auto flex items-center gap-3 text-xs text-muted">{right}</div> : null}
    </div>
  );
}

/** Mono uppercase eyebrow used inside panels ("MOVERS & FLAGS", "BEFORE ANY ENTRY"). */
export function Eyebrow({ tone = "amber", className, children }: { tone?: "amber" | "muted" | "faint"; className?: string; children: ReactNode }) {
  return (
    <div
      className={cx(
        "num text-[10px] tracking-[1px]",
        tone === "amber" ? "text-amber" : tone === "muted" ? "text-muted" : "text-faint",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Small stat tile (label + value) as used in "WIN 3D / AVG 3D / SAMPLE". */
export function StatTile({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx("num flex flex-col gap-0.5 rounded-lg bg-rail p-2", className)}>
      <span className="text-[10px] text-faint">{label}</span>
      <span className="text-[15px] text-text-2">{children}</span>
    </div>
  );
}
