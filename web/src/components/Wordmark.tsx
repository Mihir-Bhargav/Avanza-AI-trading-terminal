/** "Range TERMINAL" wordmark. size: rail 30px, landing header 32px, footer 28px (no tag). */
import { cx } from "@/lib/cx";

export function Wordmark({ size = 30, tag = true, className }: { size?: number; tag?: boolean; className?: string }) {
  return (
    <span className={cx("flex items-baseline gap-2", className)}>
      <span className="font-serif leading-none text-text" style={{ fontSize: size }}>
        Range
      </span>
      {tag ? <span className="num text-[10px] tracking-[1.5px] text-amber">TERMINAL</span> : null}
    </span>
  );
}
