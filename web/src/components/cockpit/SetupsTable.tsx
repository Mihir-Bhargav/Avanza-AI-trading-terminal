"use client";
import Link from "next/link";
import { Chip } from "@/components/Chip";
import { DataCell, DataHeader, DataRow, DataTable } from "@/components/DataTable";
import { Panel, PanelHeader } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import {
  STATE_LABEL,
  barIsPrevSession,
  relevantDist,
  relevantHist,
  shortDate,
  stateTone,
  zoneSide,
} from "@/components/chart/ttm";
import type { ApiError, SetupRow, SetupsResponse } from "@/lib/api";
import { routes } from "@/lib/commands";
import { cx } from "@/lib/cx";
import { fmtClock, fmtFracPct, fmtLev, fmtSigned } from "@/lib/format";
import { useNow } from "@/lib/useNow";

const COLS = "1.45fr 0.6fr 1.15fr 0.75fr 0.95fr 0.75fr 0.7fr 0.75fr 28px";

export function SetupsTable({
  data,
  error,
  isLoading,
  onRetry,
  selected,
  onSelect,
}: {
  data: SetupsResponse | undefined;
  error: ApiError | undefined;
  isLoading: boolean;
  onRetry: () => void;
  selected: string | null;
  onSelect: (symbol: string) => void;
}) {
  const now = useNow(60_000);
  const errs = data?.errors ?? [];

  const right = (
    <>
      {errs.length ? (
        <span title={errs.map((e) => `${e.symbol}: ${e.error}`).join("\n")}>
          <Chip tone="warn">
            {errs.length} symbol{errs.length === 1 ? "" : "s"} unavailable
          </Chip>
        </span>
      ) : null}
      {error && data ? <Chip tone="warn">Refresh failed</Chip> : null}
      {data ? <span className="num text-[11px] text-faint">AS OF {fmtClock(data.as_of)}</span> : null}
    </>
  );

  let body;
  if (isLoading) body = <StateView kind="loading" title="Reading today's setups" message="Classifying 16 instruments against today's zones." />;
  else if (error && !data) body = <StateView kind="error" error={error} onRetry={onRetry} />;
  else if (!data || data.rows.length === 0)
    body = <StateView kind="empty" title="No setups" message="The zone panel returned no instruments." />;
  else
    body = (
      <DataTable label="Today's setups" className="min-h-0 flex-1">
        <DataHeader
          cols={COLS}
          columns={[
            { label: "INSTRUMENT" },
            { label: "TREND" },
            { label: "ZONE" },
            { label: <span title="Signed distance to the relevant zone in daily ATR. Positive = through the zone.">DIST ATR</span>, align: "right" },
            { label: "HIST WIN (N)", align: "right" },
            { label: "AVG 3D", align: "right" },
            { label: "LEV CAP", align: "right" },
            { label: "EARNINGS", align: "right" },
            { label: <span className="sr-only">Chart</span> },
          ]}
        />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {data.rows.map((r) => (
            <Row key={r.symbol} r={r} now={now} selected={r.symbol === selected} onSelect={onSelect} />
          ))}
        </div>
      </DataTable>
    );

  return (
    <Panel aria-labelledby="setups-h" className="min-h-0 flex-1">
      <PanelHeader
        id="setups-h"
        title="Today's setups"
        tag="TTM POWER RANGE"
        right={
          <>
            <span className="text-xs text-muted">A cross is a prompt to look, not an order.</span>
            {right}
          </>
        }
      />
      {body}
    </Panel>
  );
}

function Row({ r, now, selected, onSelect }: { r: SetupRow; now: number | null; selected: boolean; onSelect: (s: string) => void }) {
  const dist = relevantDist(r);
  const hist = relevantHist(r);
  const prev = barIsPrevSession(r, now);
  const earnSoon = r.earnings_days != null && r.earnings_days <= 7;
  const avgTone = hist.avg_fwd_ret == null ? "" : hist.avg_fwd_ret > 0 ? "text-up" : hist.avg_fwd_ret < 0 ? "text-down" : "";
  return (
    <DataRow
      cols={COLS}
      selected={selected}
      onClick={() => onSelect(r.symbol)}
      ariaLabel={`${r.symbol}, ${STATE_LABEL[r.state]}`}
      className={cx(selected && "shadow-[inset_2px_0_0_var(--amber)]")}
    >
      <DataCell className="flex flex-col">
        <span className="num truncate font-semibold text-text">{r.symbol}</span>
        <span className="truncate text-[11px] text-muted">
          {r.name}
          {prev && r.bar_date ? (
            <span className="text-faint" title={`Classified on the ${r.bar_date} daily bar; this market has not opened yet today.`}>
              {" "}
              · {shortDate(r.bar_date)} bar
            </span>
          ) : null}
        </span>
      </DataCell>
      <DataCell className={r.trend === "up" ? "text-up" : "text-down"}>{r.trend === "up" ? "↑ Up" : "↓ Down"}</DataCell>
      <DataCell>
        <Chip tone={stateTone(r.state)}>{STATE_LABEL[r.state]}</Chip>
      </DataCell>
      <DataCell align="right" mono className={cx(dist != null && dist > 0 && "text-text")}>
        <span title={`Distance to ${zoneSide(r) === "z1" ? "Z1" : "Z3"}; positive = through the zone`}>{fmtSigned(dist, 2)}</span>
      </DataCell>
      <DataCell align="right" mono>
        {hist.n ? (
          <>
            {fmtFracPct(hist.win_rate)} <span className="text-faint">({hist.n})</span>
          </>
        ) : (
          <span className="text-faint">n=0</span>
        )}
      </DataCell>
      <DataCell align="right" mono className={avgTone}>
        {fmtFracPct(hist.avg_fwd_ret, 1, true)}
      </DataCell>
      <DataCell align="right" mono>
        {fmtLev(r.lev_cap)}
      </DataCell>
      <DataCell align="right" mono className={earnSoon ? "text-down-soft" : "text-soft"}>
        {r.earnings_days != null ? (
          <span title={r.earnings_date ?? undefined}>
            {r.earnings_days}d{earnSoon ? " !" : ""}
          </span>
        ) : r.earnings_error ? (
          <span className="text-warn-text" title={r.earnings_error}>
            ?
          </span>
        ) : (
          <span className="text-faint">—</span>
        )}
      </DataCell>
      <DataCell align="right">
        <Link
          href={routes.chart(r.symbol)}
          aria-label={`Open ${r.symbol} chart`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-faint hover:bg-raised hover:text-amber"
        >
          →
        </Link>
      </DataCell>
    </DataRow>
  );
}
