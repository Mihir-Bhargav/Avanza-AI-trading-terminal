import type { Metadata } from "next";
import { MarketsView } from "@/components/markets/MarketsView";

export const metadata: Metadata = { title: "Markets" };

/** ?index=nasdaq100 (etc.) preselects an index; unknown values fall back to the S&P 500. */
export default async function MarketsPage({ searchParams }: PageProps<"/terminal/markets">) {
  const sp = await searchParams;
  const index = typeof sp.index === "string" ? sp.index.toLowerCase() : undefined;
  return <MarketsView initialIndex={index} />;
}
