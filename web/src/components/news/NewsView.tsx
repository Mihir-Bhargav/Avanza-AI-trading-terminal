"use client";
/** News & Ask Kes page body: news on the left, the Kes chat on the right. */
import { AskKes } from "./AskKes";
import { NewsList } from "./NewsList";

export function NewsView({ symbol, ask }: { symbol?: string; ask?: string }) {
  const context = ask ?? symbol;
  return (
    <div className="flex min-h-0 flex-1 gap-4 px-6 py-5">
      <NewsList focus={symbol ?? ask} />
      <AskKes initialSymbols={context ? [context] : []} prefill={!!ask} />
    </div>
  );
}
