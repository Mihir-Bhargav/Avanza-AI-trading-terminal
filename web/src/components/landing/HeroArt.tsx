/**
 * Hero line-art (Landing.dc.html art()). Drawn in a 1440×880 space and
 * right-anchored with "slice": narrower screens crop the empty left edge,
 * wider screens scale up, so the band, labels and Kes always stay in view.
 */
import { Kes } from "../Kes";
import { art } from "./art";

const A = art();

export function HeroArt() {
  return (
    <svg
      viewBox="0 0 1440 880"
      preserveAspectRatio="xMaxYMid slice"
      aria-hidden="true"
      className="absolute inset-0 block h-full w-full"
    >
      <defs>
        <linearGradient id="fadeCool" gradientUnits="userSpaceOnUse" x1="420" y1="0" x2="1060" y2="0">
          <stop offset="0" stopColor="#6E8FB5" stopOpacity="0" />
          <stop offset="1" stopColor="#8FB0D6" stopOpacity="0.5" />
        </linearGradient>
        <linearGradient id="fadeAmber" gradientUnits="userSpaceOnUse" x1="520" y1="0" x2="1080" y2="0">
          <stop offset="0" stopColor="#F5A623" stopOpacity="0" />
          <stop offset="1" stopColor="#F5A623" stopOpacity="0.95" />
        </linearGradient>
      </defs>
      <rect x={A.bandX} y={A.bandY} width={A.bandW} height={A.bandH} fill="rgba(245,166,35,0.055)" />
      <path d={A.edges} stroke="#F5A623" strokeOpacity="0.4" strokeWidth="1" strokeDasharray="2 6" />
      <path d={A.cool} fill="none" stroke="url(#fadeCool)" strokeWidth="1" />
      <path d={A.amber} fill="none" stroke="url(#fadeAmber)" strokeWidth="1.15" />
      <text x="1416" y={A.hiLabelY} textAnchor="end" fontFamily="var(--font-geist-mono)" fontSize="10" letterSpacing="1.2" fill="#8A939E">
        RANGE HIGH
      </text>
      <text x="1416" y={A.loLabelY} textAnchor="end" fontFamily="var(--font-geist-mono)" fontSize="10" letterSpacing="1.2" fill="#8A939E">
        RANGE LOW
      </text>
      <Kes x={1196} y={A.kesY} size={44} perch="legs" />
    </svg>
  );
}
