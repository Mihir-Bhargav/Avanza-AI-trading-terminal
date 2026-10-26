/**
 * "The range, drawn properly": static illustrative candles with today's zones
 * shaded, plus the level ladder. Sample figures, not market data.
 */
import { cx } from "@/lib/cx";
import { chart, ladder } from "./art";

const C = chart(440, 420, 22, 20, 11, 23);
const LADDER = ladder();

export function RangeIllustration() {
  return (
    <div className="flex min-w-0 flex-1 gap-4 rounded-card border border-[#262D37] bg-rail p-5">
      <svg
        viewBox="0 0 440 420"
        role="img"
        aria-label="Illustration: candles with today's upper and lower zones shaded across today only"
        className="block h-auto w-[440px] max-w-[58%] shrink"
      >
        <line x1={C.todayX} x2={C.todayX} y1="6" y2="414" stroke="#2B323C" strokeDasharray="3 4" />
        <rect x={C.todayX} y={C.upperY} width={C.bandW} height={C.upperH} fill="rgba(245,166,35,0.14)" />
        <rect x={C.todayX} y={C.lowerY} width={C.bandW} height={C.lowerH} fill="rgba(90,169,255,0.14)" />
        <path d={C.wickUp} className="stroke-up" strokeWidth="1" />
        <path d={C.wickDn} className="stroke-down" strokeWidth="1" />
        <path d={C.up} className="fill-up" />
        <path d={C.dn} className="fill-down" />
      </svg>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="num pb-2.5 pt-1 text-[10px] tracking-[1px] text-faint">LEVELS · FROM LAST</span>
        <ul className="m-0 flex list-none flex-col p-0" aria-label="Sample levels, sorted by price">
          {LADDER.map((l) => (
            <li
              key={l.name}
              className={cx(
                "flex h-10 items-center gap-2 rounded-lg px-2.5 text-[13px]",
                l.current ? "bg-amber/10 text-amber" : "text-text-2",
              )}
            >
              <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: l.swatch }} />
              <span className="w-[62px]">{l.name}</span>
              <span className="num">{l.price}</span>
              <span className="num ml-auto text-xs text-muted">{l.dist}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
