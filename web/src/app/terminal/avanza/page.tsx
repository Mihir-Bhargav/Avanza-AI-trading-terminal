import type { Metadata } from "next";
import { AvanzaFinder } from "@/components/avanza/AvanzaFinder";

export const metadata: Metadata = { title: "Avanza finder" };

/** ?q=bull x2 amd runs the search. Keyed on the query so a new search starts clean. */
export default async function AvanzaPage({ searchParams }: PageProps<"/terminal/avanza">) {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q.trim() : "";
  return <AvanzaFinder key={q} initialQuery={q} />;
}
