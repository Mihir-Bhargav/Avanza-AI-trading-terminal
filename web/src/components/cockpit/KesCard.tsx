"use client";
import Link from "next/link";
import { useState } from "react";
import { Kes, KES_MOOD_LABEL } from "@/components/Kes";
import { Panel } from "@/components/Panel";
import { StateView } from "@/components/StateView";
import type { KesBriefing, PlansResponse } from "@/lib/api";
import { paths } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtClock } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const SEGMENTS = 7;

function Streak() {
  const { data, error, isLoading, mutate } = useApi<PlansResponse>(paths.plans(), { refreshInterval: 120_000 });
  return (
    <div className="flex w-[176px] shrink-0 flex-col gap-[7px] self-stretch border-l border-kes-line pl-5 justify-center">
      <span className="text-xs text-muted">Discipline streak</span>
      {isLoading ? (
        <span className="text-xs text-faint">Loading…</span>
      ) : error && !data ? (
        <span className="text-xs text-warn-text" role="alert">
          Plans unavailable.{" "}
          <button type="button" className="cursor-pointer text-amber underline-offset-2 hover:underline" onClick={() => mutate()}>
            Retry
          </button>
        </span>
      ) : (
        <>
          <span className="font-serif text-[34px] leading-none text-text">
            {data?.streak ?? 0}{" "}
            <span className="font-sans text-[13px] text-muted">{data?.streak === 1 ? "plan" : "plans"}</span>
          </span>
          <div className="flex gap-1" aria-hidden="true">
            {Array.from({ length: SEGMENTS }, (_, i) => (
              <span
                key={i}
                className={cx("h-[7px] w-5 rounded-full", i < Math.min(data?.streak ?? 0, SEGMENTS) ? "bg-amber" : "bg-line-3")}
              />
            ))}
          </div>
          <span className="text-[11px] leading-snug text-faint">Plans logged with target and stop</span>
        </>
      )}
    </div>
  );
}

export function KesCard() {
  const { data, error, isLoading, mutate } = useApi<KesBriefing>(paths.kesBriefing(), { refreshInterval: 300_000 });
  const [expanded, setExpanded] = useState(false);

  let main;
  if (isLoading) main = <StateView kind="loading" compact title="Kes is reading today's setups" className="flex-1 px-0" />;
  else if (error && !data) main = <StateView kind="error" compact error={error} onRetry={() => mutate()} className="flex-1 px-0" />;
  else if (data)
    main = (
      <>
        <Kes mood={data.mood} size={80} perch="none" label={`Kes, ${KES_MOOD_LABEL[data.mood].toLowerCase()}`} className="shrink-0" />
        <div className="flex min-w-0 flex-1 flex-col gap-[7px]">
          <span className="num text-[11px] tracking-[1.2px] text-amber">KES · BRIEFING {fmtClock(data.as_of)}</span>
          <p id="kes-text" className={cx("m-0 text-[14px] leading-[1.45] text-text", !expanded && "line-clamp-3")}>
            {data.text}
          </p>
          {data.links.length || data.plans_error || data.text.length > 150 ? (
            <div className="flex flex-wrap items-center gap-4 text-[13px] font-medium">
              {data.links.map((l) => (
                <Link key={l.href} href={l.href} className="text-amber hover:text-amber-hover">
                  {l.label} →
                </Link>
              ))}
              {data.text.length > 150 ? (
                <button
                  type="button"
                  aria-expanded={expanded}
                  aria-controls="kes-text"
                  onClick={() => setExpanded((e) => !e)}
                  className="cursor-pointer text-muted hover:text-text-2"
                >
                  {expanded ? "Less" : "Read all"}
                </button>
              ) : null}
              {data.plans_error ? <span className="text-xs font-normal text-warn-text">Plans: {data.plans_error}</span> : null}
            </div>
          ) : null}
        </div>
      </>
    );
  else main = <StateView kind="empty" compact title="No briefing" className="flex-1 px-0" />;

  return (
    <Panel variant="kes" aria-label="Kes briefing" className="min-w-0 flex-1 flex-row items-center gap-5 px-[22px] py-4">
      {main}
      <Streak />
    </Panel>
  );
}
