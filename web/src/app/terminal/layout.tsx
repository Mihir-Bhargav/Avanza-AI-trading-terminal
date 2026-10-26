import type { Metadata } from "next";
import { Header } from "@/components/terminal/Header";
import { MarketLine } from "@/components/terminal/MarketLine";
import { Rail } from "@/components/terminal/Rail";

export const metadata: Metadata = { title: { default: "Cockpit", template: "%s · Range" } };

/**
 * Terminal shell: rail | (header, market line, page). Pages render into <main>,
 * which scrolls on its own; the shell never scrolls. Pages should lay out with
 * the design's 20px/24px padding: <div className="flex gap-4 px-6 py-5">.
 */
export default function TerminalLayout({ children }: LayoutProps<"/terminal">) {
  return (
    <div className="relative flex h-dvh min-w-[1024px] overflow-hidden bg-ground text-text-2">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-amber px-3 py-2 text-sm font-semibold text-on-amber focus:not-sr-only focus:absolute focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <MarketLine />
        <main id="main" className="flex min-h-0 flex-1 flex-col overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
