import type { Metadata } from "next";
import { NewsView } from "@/components/news/NewsView";

export const metadata: Metadata = { title: "News & Ask" };

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-^=]{0,15}$/;
const clean = (v: string | string[] | undefined) => {
  const s = typeof v === "string" ? v.trim().toUpperCase() : "";
  return SYMBOL_RE.test(s) ? s : undefined;
};

/** ?symbol=MU (command bar "MU N") puts MU first in the news; ?ask=MU also prefills a question for Kes. */
export default async function NewsPage({ searchParams }: PageProps<"/terminal/news">) {
  const sp = await searchParams;
  const symbol = clean(sp.symbol);
  const ask = clean(sp.ask);
  return <NewsView key={`${symbol ?? ""}|${ask ?? ""}`} symbol={symbol} ask={ask} />;
}
