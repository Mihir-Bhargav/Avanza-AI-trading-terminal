import type { Metadata } from "next";
import { ChartWorkspace } from "@/components/chart/ChartWorkspace";

export async function generateMetadata({ params }: PageProps<"/terminal/chart/[symbol]">): Promise<Metadata> {
  const { symbol } = await params;
  return { title: `${decodeURIComponent(symbol).toUpperCase()} Chart` };
}

export default async function ChartPage({ params }: PageProps<"/terminal/chart/[symbol]">) {
  const symbol = decodeURIComponent((await params).symbol).trim().toUpperCase();
  // key: a new symbol starts with fresh timeframe/indicator state and a new chart.
  return <ChartWorkspace key={symbol} symbol={symbol} />;
}
