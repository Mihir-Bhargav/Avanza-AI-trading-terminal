import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/Button";
import { Kes } from "@/components/Kes";
import { Wordmark } from "@/components/Wordmark";
import { routes } from "@/lib/commands";

export const metadata: Metadata = { title: "Not found" };

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col bg-[#060708] text-text-2">
      <header className="mx-auto flex h-[84px] w-full max-w-[1440px] items-center px-10 xl:px-[120px]">
        <Link href="/" aria-label="Range, home" className="rounded-lg">
          <Wordmark size={32} />
        </Link>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-6 px-10 pb-24 text-center">
        <Kes mood="thinking" size={140} label="Kes, thinking" />
        <span className="num text-xs tracking-[2.2px] text-amber">404 · OUTSIDE THE RANGE</span>
        <h1 className="m-0 font-serif text-[72px] font-normal leading-none text-[#F7F7F5]">Nothing here.</h1>
        <p className="m-0 max-w-[480px] text-lg leading-[1.5] text-muted">
          This page doesn&apos;t exist. I won&apos;t guess where you meant to go, but these two are safe bets.
        </p>
        <div className="mt-2 flex items-center gap-6">
          <Button href={routes.home} variant="primary" size="sm">
            Open the terminal <span aria-hidden="true">→</span>
          </Button>
          <Link href="/" className="border-b border-[#4A525E] pb-[3px] text-[15px] font-medium text-text hover:border-text">
            Back to the landing page
          </Link>
        </div>
      </main>
    </div>
  );
}
