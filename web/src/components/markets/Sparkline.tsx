/**
 * Tiny intraday sparkline (today's 5-minute closes). Coloured by the day's
 * direction (vs previous close, same sign as the % shown next to it), with a
 * dotted line at the previous close when it is known.
 */
import { cx } from "@/lib/cx";

export function Sparkline({
  points,
  changePct,
  width = 72,
  height = 22,
  className,
}: {
  points: number[];
  changePct: number | null;
  width?: number;
  height?: number;
  className?: string;
}) {
  if (points.length < 2) {
    return (
      <span className={cx("num inline-block text-center text-[10px] text-faint", className)} style={{ width }}>
        no bars
      </span>
    );
  }
  const last = points[points.length - 1];
  const prev = changePct != null && changePct > -100 ? last / (1 + changePct / 100) : null;
  let lo = Math.min(...points);
  let hi = Math.max(...points);
  if (prev != null) {
    lo = Math.min(lo, prev);
    hi = Math.max(hi, prev);
  }
  const span = hi - lo || 1;
  const pad = 2;
  const x = (i: number) => (i / (points.length - 1)) * (width - pad * 2) + pad;
  const y = (v: number) => height - pad - ((v - lo) / span) * (height - pad * 2);
  const d = points.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const tone = changePct == null || changePct === 0 ? "text-muted" : changePct > 0 ? "text-up" : "text-down";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cx("block shrink-0 overflow-visible", tone, className)}
      aria-hidden="true"
    >
      {prev != null ? (
        <line
          x1={pad}
          x2={width - pad}
          y1={y(prev)}
          y2={y(prev)}
          stroke="var(--line-3)"
          strokeWidth="1"
          strokeDasharray="2 2"
        />
      ) : null}
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(points.length - 1)} cy={y(last)} r="1.8" fill="currentColor" />
    </svg>
  );
}
