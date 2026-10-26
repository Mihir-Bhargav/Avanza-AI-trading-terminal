"use client";
import { useState } from "react";
import { Panel } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import type { SetupsResponse } from "@/lib/api";
import { paths } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { FocusCard } from "./FocusCard";
import { KesCard } from "./KesCard";
import { MovingHoldings } from "./MovingHoldings";
import { PortfolioCard } from "./PortfolioCard";
import { SetupsTable } from "./SetupsTable";

/** The cockpit (/terminal): portfolio + Kes, today's TTM setups, and a focus card for the selected one. */
export function Cockpit() {
  const setups = useApi<SetupsResponse>(paths.setups(), { refreshInterval: 300_000 });
  const [picked, setPicked] = useState<string | null>(null);
  const rows = setups.data?.rows ?? [];
  const row = rows.find((r) => r.symbol === picked) ?? rows[0] ?? null;

  return (
    <div className="flex min-h-[760px] flex-1 flex-col gap-4 px-6 py-5">
      <h1 className="sr-only">Cockpit</h1>
      <div className="flex min-h-[132px] shrink-0 gap-4">
        <PortfolioCard />
        <KesCard />
      </div>
      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <SetupsTable
            data={setups.data}
            error={setups.error}
            isLoading={setups.isLoading}
            onRetry={() => setups.mutate()}
            selected={row?.symbol ?? null}
            onSelect={setPicked}
          />
          <MovingHoldings />
        </div>
        {row ? (
          <FocusCard row={row} />
        ) : (
          <Panel as="aside" aria-label="Focus" className="w-[392px] shrink-0 justify-center">
            {setups.isLoading ? (
              <StateView kind="loading" title="Waiting for setups" />
            ) : (
              <StateView kind="empty" title="Nothing selected" message="Pick a setup on the left to see its chart and checklist." />
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}
