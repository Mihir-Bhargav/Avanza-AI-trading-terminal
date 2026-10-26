/**
 * Kes, the kestrel mascot (Agent.dc.html). Artwork is exact per mood.
 *
 * Props
 *   mood    watching | alert | cautious | thinking | pleased (default watching)
 *   size    rendered px (square), default 40
 *   perch   "bar"  feet + short perch line (mood cards)          [default]
 *           "wide" feet + full-width perch line (landing Meet Kes)
 *           "legs" long legs, no line (perched on the hero art)
 *           "none" no feet (rail card, briefing, inline avatars)
 *   perchColor  defaults to amber; landing ivory uses #E29416
 *   detail  belly spots; defaults on at size >= 120
 *   highlights  eye glints (watching mood); defaults on at size >= 60
 *   x, y    position when nested inside another <svg>
 *   label   accessible name. Omit for decorative use (aria-hidden).
 */
import type { KesMood } from "@/lib/api";

export type { KesMood };

const INK = "#2A3440";
const PUPIL = "#14171C";

function Eyes({ mood, highlights }: { mood: KesMood; highlights: boolean }) {
  const whites = (
    <>
      <circle cx="46" cy="53" r="13" fill="#FFFFFF" />
      <circle cx="74" cy="53" r="13" fill="#FFFFFF" />
    </>
  );
  switch (mood) {
    case "alert":
      return (
        <>
          {whites}
          <circle cx="47" cy="54" r="5" fill={PUPIL} />
          <circle cx="73" cy="54" r="5" fill={PUPIL} />
        </>
      );
    case "cautious":
      return (
        <>
          {whites}
          <circle cx="50" cy="57" r="6.5" fill={PUPIL} />
          <circle cx="77" cy="57" r="6.5" fill={PUPIL} />
        </>
      );
    case "thinking":
      return (
        <>
          {whites}
          <circle cx="44" cy="49" r="6.5" fill={PUPIL} />
          <circle cx="71" cy="49" r="6.5" fill={PUPIL} />
        </>
      );
    case "pleased":
      return (
        <>
          {whites}
          <path d="M37 56q9-11 18 0M65 56q9-11 18 0" stroke={PUPIL} strokeWidth="5" strokeLinecap="round" fill="none" />
        </>
      );
    default:
      return (
        <>
          {whites}
          <circle cx="47" cy="55" r="6.5" fill={PUPIL} />
          <circle cx="73" cy="55" r="6.5" fill={PUPIL} />
          {highlights ? (
            <>
              <circle cx="49" cy="52" r="2" fill="#FFFFFF" />
              <circle cx="75" cy="52" r="2" fill="#FFFFFF" />
            </>
          ) : null}
        </>
      );
  }
}

function Brows({ mood }: { mood: KesMood }) {
  switch (mood) {
    case "alert":
      return <path d="M35 35l20 10M85 35l-20 10" stroke={INK} strokeWidth="5.5" strokeLinecap="round" />;
    case "cautious":
      return <path d="M36 43l17-6M84 43l-17-6" stroke={INK} strokeWidth="5" strokeLinecap="round" />;
    case "thinking":
      return <path d="M36 38l17 3M84 33l-17 8" stroke={INK} strokeWidth="5" strokeLinecap="round" />;
    case "pleased":
      return null;
    default:
      return <path d="M36 38l17 5M84 38l-17 5" stroke={INK} strokeWidth="5" strokeLinecap="round" />;
  }
}

function Accent({ mood }: { mood: KesMood }) {
  switch (mood) {
    case "alert":
      return (
        <>
          <circle cx="102" cy="20" r="13" fill="#FF6A5E" />
          <path d="M102 13v9M102 27v1" stroke="#FFFFFF" strokeWidth="4" strokeLinecap="round" />
        </>
      );
    case "thinking":
      return (
        <>
          <circle cx="94" cy="22" r="3" fill="#AEB6C0" />
          <circle cx="104" cy="16" r="3" fill="#AEB6C0" />
          <circle cx="114" cy="10" r="3" fill="#AEB6C0" />
        </>
      );
    case "pleased":
      return <path d="M100 14l3 7 7 1-5 5 1 7-6-4-6 4 1-7-5-5 7-1z" fill="#F5A623" />;
    default:
      return null;
  }
}

export const KES_MOOD_LABEL: Record<KesMood, string> = {
  watching: "Watching",
  alert: "Alert",
  cautious: "Cautious",
  thinking: "Thinking",
  pleased: "Pleased",
};

export function Kes({
  mood = "watching",
  size = 40,
  perch = "bar",
  perchColor = "#F5A623",
  detail,
  highlights,
  label,
  x,
  y,
  className,
}: {
  mood?: KesMood;
  size?: number;
  perch?: "bar" | "wide" | "legs" | "none";
  perchColor?: string;
  detail?: boolean;
  highlights?: boolean;
  label?: string;
  x?: number;
  y?: number;
  className?: string;
}) {
  const spots = detail ?? size >= 120;
  const a11y = label ? { role: "img" as const, "aria-label": label } : { "aria-hidden": true as const };
  return (
    <svg x={x} y={y} width={size} height={size} viewBox="0 0 120 120" className={className} {...a11y}>
      {label ? <title>{label}</title> : null}
      <path d="M24 64c-7 16-2 34 12 42l10-30z" fill="#B8662F" />
      <path d="M96 64c7 16 2 34-12 42l-10-30z" fill="#B8662F" />
      <ellipse cx="60" cy="64" rx="36" ry="41" fill="#5B7188" />
      <ellipse cx="60" cy="82" rx="22" ry="23" fill="#F1E4CC" />
      {spots ? (
        <>
          <circle cx="52" cy="84" r="2" fill="#D6BE96" />
          <circle cx="67" cy="89" r="2" fill="#D6BE96" />
          <circle cx="60" cy="75" r="2" fill="#D6BE96" />
        </>
      ) : null}
      <Eyes mood={mood} highlights={highlights ?? size >= 60} />
      {/* The signature detail: the kestrel's dark cheek stripe. */}
      <path d="M39 67c2 6 4 9 8 12M81 67c-2 6-4 9-8 12" stroke={INK} strokeWidth="4.5" strokeLinecap="round" fill="none" />
      <Brows mood={mood} />
      <path d="M54 62h12l-6 9z" fill="#F5A623" />
      {perch === "bar" ? (
        <path d="M50 103v9M70 103v9M30 113h60" stroke={perchColor} strokeWidth="4" strokeLinecap="round" />
      ) : null}
      {perch === "wide" ? (
        <>
          <path d="M50 103v9M70 103v9" stroke={perchColor} strokeWidth="4" strokeLinecap="round" />
          <path d="M4 113h112" stroke={perchColor} strokeWidth="3.5" strokeLinecap="round" />
        </>
      ) : null}
      {perch === "legs" ? (
        <path d="M50 103v14M70 103v14" stroke={perchColor} strokeWidth="4" strokeLinecap="round" />
      ) : null}
      <Accent mood={mood} />
    </svg>
  );
}
