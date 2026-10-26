import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@/components/Button";
import { Kes } from "@/components/Kes";
import { Wordmark } from "@/components/Wordmark";
import { HeroArt } from "@/components/landing/HeroArt";
import { RangeIllustration } from "@/components/landing/RangeIllustration";
import { routes } from "@/lib/commands";

/* Landing page (Landing.dc.html). Static marketing; every figure here is illustrative. */

const WRAP = "mx-auto w-full max-w-[1440px] px-10 xl:px-[120px]";

const PRINCIPLES = [
  { n: "01", t: "One page, one job", d: "Cockpit decides, Chart studies, Portfolio reviews, News explains." },
  { n: "02", t: "No number without its age", d: "Live, delayed, closed or stale, shown once on every panel." },
  { n: "03", t: "Computed, never generated", d: "Figures come from data. The agent only explains them." },
  { n: "04", t: "Read-only, always", d: "It can read your account. It cannot place an order." },
];

const PAGES = [
  { code: "HOME", name: "Cockpit", desc: "Today's setups ranked by how they have played out before, and a checklist before you enter.", keys: "HOME ⏎", href: routes.home },
  { code: "GP", name: "Chart", desc: "One instrument, today's zones shaded, every level listed beside the chart.", keys: "MU GP ⏎", href: routes.chart("MU") },
  { code: "PORT", name: "Portfolio", desc: "Holdings, allocation, currency exposure and a brief when you ask for one.", keys: "PORT ⏎", href: routes.portfolio },
  { code: "N", name: "News & Ask", desc: "News that explains moves in what you own, and Kes to question.", keys: "N ⏎", href: routes.news() },
  { code: "DISC", name: "Disclosures", desc: "Congress, insider and fund filings, with the filing delay shown so history is never read as a signal.", keys: "DISC ⏎", href: routes.disclosures() },
];

const RULES = [
  { n: "01", t: "Target and stop first", code: "TP + SL before entry", d: "Both levels decided before the order, never after watching it move." },
  { n: "02", t: "Leverage the noise allows", code: "max ≈ 100 / (3.5 × ATR%)", d: "Above this, a normal day's swing can knock the position out." },
  { n: "03", t: "Check the calendar", code: "earnings ≤ hold period?", d: "ATR looks backward. A binary print makes the leverage maths misleading." },
  { n: "04", t: "Know the decay", code: "daily reset ≠ 2 × move", d: "Daily-reset products lose value on a choppy path, even when the direction is right." },
];

function Eyebrow({ children, onIvory = false }: { children: ReactNode; onIvory?: boolean }) {
  return <span className={`num text-[13px] tracking-[2.2px] ${onIvory ? "text-ochre" : "text-amber"}`}>{children}</span>;
}

const Arrow = () => <span aria-hidden="true">→</span>;

export default function Landing() {
  return (
    <div className="min-h-dvh bg-[#060708] text-text-2">
      {/* ------------------------------------------------------------ nav */}
      <header className={`${WRAP} flex h-[84px] items-center gap-10`}>
        <Link href="/" aria-label="Range, home" className="rounded-lg">
          <Wordmark size={32} />
        </Link>
        <nav aria-label="Site" className="flex gap-8 text-[15px]">
          <a href="#pages" className="text-soft hover:text-text">Product</a>
          <a href="#kes" className="text-soft hover:text-text">Kes</a>
          <a href="#discipline" className="text-soft hover:text-text">Discipline</a>
        </nav>
        <Button href={routes.home} variant="primary" size="sm" className="ml-auto">
          Open terminal
        </Button>
      </header>

      <main>
        {/* ---------------------------------------------------------- hero */}
        <section aria-labelledby="hero-h" className="relative h-[880px] overflow-hidden border-b border-[#14181E]">
          <HeroArt />
          <div className={`${WRAP} relative pt-[148px]`}>
            <div className="flex max-w-[780px] flex-col">
              <div className="flex items-center gap-3">
                <span aria-hidden="true" className="h-px w-7 bg-amber" />
                <span className="num text-xs tracking-[2.2px] text-amber">PERSONAL TRADING TERMINAL</span>
              </div>
              <h1
                id="hero-h"
                className="mb-0 mt-[26px] font-serif text-[80px] font-normal leading-[0.96] tracking-[-1.6px] text-[#F7F7F5] xl:text-[108px]"
              >
                Trade the range.
                <br />
                <span className="italic text-[#A9B0BA]">Not the noise.</span>
              </h1>
              <p className="mb-0 mt-[30px] max-w-[560px] text-xl leading-[1.5] text-muted">
                A calm, precise terminal for one trader. Zones and levels drawn properly, your portfolio at a glance, and
                Kes, an agent that explains every move and never trades for you.
              </p>
              <div className="mt-10 flex items-center gap-[30px]">
                <Button href={routes.home} variant="primary" size="md">
                  Open the terminal <Arrow />
                </Button>
                <a href="#kes" className="border-b border-[#4A525E] pb-[3px] text-base font-medium text-text hover:border-text">
                  Meet Kes, your agent
                </a>
              </div>
              <dl className="num m-0 mt-[88px] flex gap-12">
                {[
                  ["5", "PAGES, ONE JOB EACH"],
                  ["100%", "OF NUMBERS SHOW THEIR AGE"],
                  ["0", "ORDER BUTTONS"],
                ].map(([v, l]) => (
                  <div key={l} className="flex flex-col-reverse gap-1.5">
                    <dt className="text-[11px] tracking-[1px] text-faint">{l}</dt>
                    <dd className="m-0 text-[22px] text-text">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------- principles */}
        <section aria-label="Principles" className="border-y border-[#1A1F26]">
          <div className={`${WRAP} grid grid-cols-2 gap-8 py-10 lg:grid-cols-4`}>
            {PRINCIPLES.map((p) => (
              <div key={p.n} className="flex flex-col gap-2">
                <span className="num text-xs text-amber">{p.n}</span>
                <span className="text-[17px] font-semibold text-text">{p.t}</span>
                <span className="text-sm leading-[1.45] text-muted">{p.d}</span>
              </div>
            ))}
          </div>
        </section>

        {/* --------------------------------------------------------- pages */}
        <section id="pages" aria-labelledby="pages-h" className="on-ivory scroll-mt-4 bg-ivory text-ink">
          <div className={`${WRAP} flex min-h-[760px] flex-col gap-12 pb-24 pt-28`}>
            <div className="flex flex-wrap items-end gap-10">
              <div className="flex flex-col gap-3.5">
                <Eyebrow onIvory>THE PRODUCT</Eyebrow>
                <h2 id="pages-h" className="m-0 font-serif text-[72px] font-normal leading-none tracking-[-0.8px]">
                  One page, one job.
                </h2>
              </div>
              <p className="mb-2 ml-auto mt-0 max-w-[460px] text-lg leading-[1.5] text-ink-2">
                Type a ticker and a code, land on exactly one screen that does one thing well. The way terminal traders
                have worked for decades, without the cramped single page.
              </p>
            </div>
            <ul className="m-0 grid list-none grid-cols-2 gap-4 p-0 lg:grid-cols-5">
              {PAGES.map((p) => (
                <li key={p.code} className="flex">
                  <Link
                    href={p.href}
                    className="flex w-full flex-col gap-3.5 rounded-card border border-ivory-line bg-white p-5 text-ink transition-colors hover:border-[#CFC8B9] xl:p-6"
                  >
                    <span className="num self-start rounded-chip bg-ink px-2.5 py-1 text-xs tracking-[1px] text-amber">{p.code}</span>
                    <span className="text-[22px] font-semibold xl:text-2xl">{p.name}</span>
                    <span className="text-[15px] leading-[1.5] text-ink-2">{p.desc}</span>
                    <span className="num mt-auto pt-2 text-[13px] text-[#5A6270]">{p.keys}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* --------------------------------------------------------- range */}
        <section aria-labelledby="range-h">
          <div className={`${WRAP} flex min-h-[720px] flex-col justify-center gap-12 py-20 xl:flex-row xl:items-center xl:gap-20`}>
            <div className="flex max-w-[470px] shrink-0 flex-col gap-[18px]">
              <Eyebrow>THE RANGE</Eyebrow>
              <h2 id="range-h" className="m-0 font-serif text-[68px] font-normal leading-none text-[#F7F7F5]">
                Drawn properly.
              </h2>
              <p className="m-0 text-lg leading-[1.55] text-muted">
                Each morning the day&apos;s power range is set from the last ten sessions. Range shades it across today
                only, and lists every level beside the chart, sorted by price and measured in ATR, so nothing collides and
                nothing is guessed.
              </p>
              <p className="m-0 text-lg leading-[1.55] text-muted">
                When price crosses a zone with the trend, you see how often that has worked before, and how much leverage
                the stock&apos;s normal noise can survive.
              </p>
            </div>
            <RangeIllustration />
          </div>
        </section>

        {/* ----------------------------------------------------------- Kes */}
        <section id="kes" aria-labelledby="kes-h" className="on-ivory scroll-mt-4 bg-ivory text-ink">
          <div className={`${WRAP} flex min-h-[740px] items-center gap-12 py-20 xl:gap-[72px]`}>
            <Kes
              mood="watching"
              size={380}
              perch="wide"
              perchColor="#E29416"
              label="Kes the kestrel perched on a price line"
              className="h-auto w-[280px] shrink-0 xl:w-[380px]"
            />
            <div className="flex min-w-0 flex-1 flex-col gap-5">
              <Eyebrow onIvory>YOUR TRADING AGENT</Eyebrow>
              <h2 id="kes-h" className="m-0 font-serif text-[72px] font-normal leading-none tracking-[-0.8px]">
                Meet Kes.
              </h2>
              <p className="m-0 max-w-[560px] text-lg leading-[1.55] text-ink-2">
                A kestrel hovers perfectly still before it commits. Kes watches your ranges, explains what is moving,
                checks your plan before you enter, and cheers discipline, not profit.
              </p>
              <div className="flex max-w-[600px] flex-col gap-2.5">
                {[
                  "Nasdaq data is 15 minutes old. I will not guess where it is now.",
                  "Stop set before entry, four trades running. That is the streak that pays.",
                ].map((line) => (
                  <p
                    key={line}
                    className="m-0 self-start rounded-[18px_18px_18px_6px] border border-ivory-line bg-white px-[18px] py-3.5 text-base leading-[1.45]"
                  >
                    {line}
                  </p>
                ))}
              </div>
              <div className="mt-1.5 flex items-center gap-4">
                <div className="flex gap-1.5" role="img" aria-label="Example streak: 4 of 7">
                  {Array.from({ length: 7 }, (_, i) => (
                    <span key={i} className="h-2.5 w-[34px] rounded-[5px]" style={{ background: i < 4 ? "#E29416" : "#DDD6C8" }} />
                  ))}
                </div>
                <span className="text-sm text-ink-2">Discipline streak: trades with a stop and a target set first</span>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------- discipline */}
        <section id="discipline" aria-labelledby="disc-h" className="scroll-mt-4">
          <div className={`${WRAP} flex min-h-[640px] flex-col gap-12 pb-24 pt-28`}>
            <div className="flex flex-col gap-3.5">
              <Eyebrow>DISCIPLINE, BUILT IN</Eyebrow>
              <h2 id="disc-h" className="m-0 font-serif text-[68px] font-normal leading-none text-[#F7F7F5]">
                Four checks before any entry.
              </h2>
            </div>
            <ol className="m-0 grid list-none grid-cols-2 gap-5 p-0 lg:grid-cols-4">
              {RULES.map((r) => (
                <li key={r.n} className="flex flex-col gap-3.5 rounded-card border border-[#262D37] bg-rail p-[26px]">
                  <span className="num text-xs text-amber">{r.n}</span>
                  <span className="text-xl font-semibold text-text">{r.t}</span>
                  <code className="num rounded-control bg-surface px-3 py-2.5 text-[13px] text-text-2">{r.code}</code>
                  <span className="text-sm leading-[1.5] text-muted">{r.d}</span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ----------------------------------------------------------- CTA */}
        <section aria-labelledby="cta-h" className="flex h-[420px] flex-col items-center justify-center gap-[30px] border-t border-[#1A1F26] px-10">
          <h2 id="cta-h" className="m-0 text-center font-serif text-[80px] font-normal leading-none text-[#F7F7F5]">
            Today&apos;s range is set.
          </h2>
          <Button href={routes.home} variant="primary" size="lg">
            Open the terminal <Arrow />
          </Button>
        </section>
      </main>

      {/* -------------------------------------------------------- footer */}
      <footer className="border-t border-[#14181E] bg-black">
        <div className={`${WRAP} flex flex-col gap-8 py-12 lg:flex-row lg:gap-20`}>
          <div className="flex shrink-0 flex-col gap-2.5">
            <Wordmark size={28} tag={false} />
            <span className="num text-[11px] text-faint">© 2026</span>
          </div>
          <p className="m-0 max-w-[760px] text-[13px] leading-[1.6] text-placeholder">
            Range is a personal research tool, not investment advice. It reads brokerage accounts in read-only mode and
            cannot place, modify or cancel orders. Market data can be delayed; every figure shows its source and age.
            Leveraged products can lose value quickly, including through daily-reset decay.
          </p>
        </div>
      </footer>
    </div>
  );
}
