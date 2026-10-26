import type { Metadata } from "next";
import { DisclosuresView } from "@/components/disclosures/DisclosuresView";

export const metadata: Metadata = { title: "High-profile trades" };

export default async function DisclosuresPage({ searchParams }: PageProps<"/terminal/disclosures">) {
  const sp = await searchParams;
  const symbol = typeof sp.symbol === "string" && sp.symbol.trim() ? sp.symbol.trim() : undefined;
  // key: a new ?symbol= from the command bar remounts the view with that filter.
  return <DisclosuresView key={symbol ?? ""} symbol={symbol} />;
}
