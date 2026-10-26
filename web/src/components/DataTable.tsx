/**
 * Grid-based table primitives matching the design's list panels (setups,
 * holdings, disclosures): a mono uppercase header row and 42-46px rows with a
 * hairline divider. Columns share one CSS grid template.
 *
 *   const cols = "1.3fr 0.7fr 1.35fr 0.8fr";
 *   <DataTable label="Today's setups">
 *     <DataHeader cols={cols} columns={[{ label: "INSTRUMENT" }, { label: "DIST ATR", align: "right" }]} />
 *     {rows.map(r => (
 *       <DataRow key={r.symbol} cols={cols} href={`/terminal/chart/${r.symbol}`} selected={...}>
 *         <DataCell>…</DataCell><DataCell align="right" mono>…</DataCell>
 *       </DataRow>))}
 *   </DataTable>
 *
 * `header` variant "plain" (inside a panel, setups/holdings) or "band" (bordered,
 * #0F1216 background, disclosures). `gap` adds column gap (disclosures uses 12px).
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export function DataTable({ label, className, children }: { label?: string; className?: string; children: ReactNode }) {
  return (
    <div role="table" aria-label={label} className={cx("flex min-h-0 flex-col", className)}>
      {children}
    </div>
  );
}

export interface ColumnDef {
  label: ReactNode;
  align?: "left" | "right" | "center";
}

export function DataHeader({
  cols,
  columns,
  variant = "plain",
  gap,
  className,
}: {
  cols: string;
  columns: ColumnDef[];
  variant?: "plain" | "band";
  gap?: number;
  className?: string;
}) {
  return (
    <div
      role="row"
      className={cx(
        "num grid px-5 text-[10px] tracking-[0.9px] text-faint",
        variant === "plain" ? "pb-2" : "border-y border-line bg-[#0F1216] py-2",
        className,
      )}
      style={{ gridTemplateColumns: cols, columnGap: gap }}
    >
      {columns.map((c, i) => (
        <span key={i} role="columnheader" className={alignClass(c.align)}>
          {c.label}
        </span>
      ))}
    </div>
  );
}

export function DataRow({
  cols,
  href,
  onClick,
  selected = false,
  height = 46,
  gap,
  className,
  children,
  ariaLabel,
}: {
  cols: string;
  href?: string;
  onClick?: () => void;
  selected?: boolean;
  height?: number;
  gap?: number;
  className?: string;
  children: ReactNode;
  ariaLabel?: string;
}) {
  const cls = cx(
    "grid items-center border-t border-raised px-5 text-[13px] text-text-2",
    selected ? "bg-[#171C23]" : "bg-transparent",
    (href || onClick) && "cursor-pointer transition-colors hover:bg-[#161B22]",
    className,
  );
  const style = { gridTemplateColumns: cols, height, columnGap: gap };
  if (href)
    return (
      <Link href={href} role="row" aria-label={ariaLabel} aria-current={selected || undefined} className={cls} style={style}>
        {children}
      </Link>
    );
  if (onClick)
    return (
      <div
        role="row"
        tabIndex={0}
        aria-label={ariaLabel}
        aria-selected={selected}
        className={cls}
        style={style}
        onClick={onClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick();
          }
        }}
      >
        {children}
      </div>
    );
  return (
    <div role="row" className={cls} style={style}>
      {children}
    </div>
  );
}

export function DataCell({
  align,
  mono = false,
  className,
  children,
}: {
  align?: "left" | "right" | "center";
  mono?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <span role="cell" className={cx("min-w-0", mono && "num", alignClass(align), className)}>
      {children}
    </span>
  );
}

function alignClass(a?: "left" | "right" | "center") {
  return a === "right" ? "text-right" : a === "center" ? "text-center" : "";
}
