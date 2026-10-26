"use client";
/** Left navigation rail: wordmark, function codes, "coming next", Kes status card. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApi } from "@/lib/useApi";
import { paths, type KesBriefing, type KesMood } from "@/lib/api";
import { routes } from "@/lib/commands";
import { cx } from "@/lib/cx";
import { Kes, KES_MOOD_LABEL } from "../Kes";
import { Wordmark } from "../Wordmark";
import { ColorSafeToggle } from "./ColorSafeToggle";

const NAV = [
  { code: "HOME", label: "Cockpit", href: routes.home, match: (p: string) => p === "/terminal" },
  { code: "MAP", label: "Markets", href: routes.markets, match: (p: string) => p.startsWith("/terminal/markets") },
  { code: "GP", label: "Chart", href: routes.chart(), match: (p: string) => p.startsWith("/terminal/chart") },
  { code: "PORT", label: "Portfolio", href: routes.portfolio, match: (p: string) => p.startsWith("/terminal/portfolio") },
  { code: "N", label: "News & Ask", href: routes.news(), match: (p: string) => p.startsWith("/terminal/news") },
  { code: "DISC", label: "Disclosures", href: routes.disclosures(), match: (p: string) => p.startsWith("/terminal/disclosures") },
  { code: "MINI", label: "Avanza finder", href: routes.avanza(), match: (p: string) => p.startsWith("/terminal/avanza") },
];

const LATER = [
  { code: "EQS", label: "Scanner" },
  { code: "SIG", label: "Signals" },
  { code: "ALRT", label: "Alerts" },
];

const moodTone: Record<KesMood, string> = {
  watching: "text-up",
  pleased: "text-up",
  alert: "text-down-soft",
  cautious: "text-amber",
  thinking: "text-muted",
};

function KesStatus() {
  const { data, error, isLoading } = useApi<KesBriefing>(paths.kesBriefing(), { refreshInterval: 60_000 });
  let mood: KesMood = "watching";
  let line = "";
  let tone = "text-muted";
  if (data) {
    mood = data.mood;
    line = KES_MOOD_LABEL[data.mood].toLowerCase();
    tone = moodTone[data.mood];
  } else if (error) {
    mood = "alert";
    line = error.unreachable ? "backend offline" : "briefing failed";
    tone = "text-down-soft";
  } else if (isLoading) {
    mood = "thinking";
    line = "checking in";
  }
  return (
    <div className="mt-3 flex flex-col gap-2.5 rounded-xl border border-line bg-surface p-3">
      <div className="flex items-center gap-2.5">
        <Kes mood={mood} size={40} perch="none" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[13px] font-semibold text-text">Kes</span>
          <span className={cx("truncate text-[11px]", tone)} aria-live="polite">
            {line}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-[7px] border-t border-line pt-[9px] text-[11px] text-muted">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        <span>Read-only · never trades</span>
      </div>
    </div>
  );
}

export function Rail() {
  const pathname = usePathname() ?? "";
  return (
    <nav
      aria-label="Primary"
      className="flex w-[216px] shrink-0 flex-col overflow-y-auto border-r border-line bg-rail px-3.5 py-5"
    >
      <Link href="/" aria-label="Range, back to the landing page" className="rounded-lg px-2 pb-[22px]">
        <Wordmark size={30} />
      </Link>

      <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
        {NAV.map((item) => {
          const on = item.match(pathname);
          return (
            <li key={item.code}>
              <Link
                href={item.href}
                aria-current={on ? "page" : undefined}
                className={cx(
                  "flex h-10 items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium transition-colors",
                  on ? "bg-raised text-text" : "text-soft hover:bg-surface hover:text-text",
                )}
              >
                <span className={cx("num w-10 text-[10px] tracking-[1px]", on ? "text-amber" : "text-faint")}>{item.code}</span>
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>

      <div id="coming-next" className="num mx-2.5 mb-1.5 mt-6 text-[10px] tracking-[1.4px] text-faint">
        COMING NEXT
      </div>
      <ul aria-labelledby="coming-next" className="m-0 flex list-none flex-col p-0">
        {LATER.map((item) => (
          <li key={item.code} className="flex h-8 items-center gap-2.5 px-2.5 text-[13px] text-faint">
            <span className="num w-10 text-[10px] tracking-[1px]">{item.code}</span>
            <span>{item.label}</span>
          </li>
        ))}
      </ul>

      <div className="mt-auto pt-4">
        <ColorSafeToggle />
        <KesStatus />
      </div>
    </nav>
  );
}
