"use client";
/**
 * TradingView's free Stock Heatmap widget, embedded (not reimplemented).
 *
 * React renders only an empty host <div>; the widget's container, config
 * <script> and iframe are created imperatively in an effect, so server and
 * client markup match (no hydration mismatch). Changing `dataSource` (or
 * retrying) tears the old widget down completely before building the new one,
 * so at most one iframe ever exists.
 *
 * Config keys and dataSource values were verified by rendering the widget in
 * headless Chrome (2026-09-24). An unknown dataSource silently falls back to
 * SPX500, which is why the options live in one checked list (lib/markets.ts).
 *
 * Failure is shown, not hidden: script load error (offline, blocker) or no
 * iframe after RENDER_TIMEOUT_MS -> StateView with a retry.
 */
import { useEffect, useRef, useState } from "react";
import { StateView } from "../StateView";

const SCRIPT_SRC = "https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js";
const RENDER_TIMEOUT_MS = 15_000;

type Status = "loading" | "ready" | "error";

export function MarketHeatmap({ dataSource, label }: { dataSource: string; label: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ key: string; status: Status; reason?: string }>({ key: "", status: "loading" });
  const key = `${dataSource}#${attempt}`;
  const status: Status = state.key === key ? state.status : "loading";

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let done = false;
    const settle = (s: Status, reason?: string) => {
      if (done) return;
      // A slow widget that shows up after the timeout still wins.
      if (s === "ready") done = true;
      setState({ key, status: s, reason });
    };

    const container = document.createElement("div");
    container.className = "tradingview-widget-container";
    container.style.height = "100%";
    container.style.width = "100%";
    const target = document.createElement("div");
    target.className = "tradingview-widget-container__widget";
    target.style.height = "100%";
    container.appendChild(target);

    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.type = "text/javascript";
    script.textContent = JSON.stringify({
      exchanges: [],
      dataSource,
      grouping: "sector",
      blockSize: "market_cap_basic",
      blockColor: "change",
      locale: "en",
      symbolUrl: "",
      colorTheme: "dark",
      hasTopBar: true,
      isDataSetEnabled: false,
      isZoomEnabled: true,
      hasSymbolTooltip: true,
      isMonoSize: false,
      width: "100%",
      height: "100%",
    });
    script.onerror = () => settle("error", "The TradingView script could not be loaded (offline, or blocked by an ad/tracker blocker).");
    container.appendChild(script);
    host.replaceChildren(container);

    // The script inserts an iframe when it runs; watch for it rather than trusting onload.
    const onFrame = () => {
      const frame = container.querySelector("iframe");
      if (!frame) return false;
      frame.title = `${label} market heatmap by TradingView`;
      settle("ready");
      return true;
    };
    const observer = new MutationObserver(() => {
      if (onFrame()) observer.disconnect();
    });
    observer.observe(container, { childList: true, subtree: true });
    const timer = window.setTimeout(() => {
      if (!onFrame()) settle("error", `TradingView did not render the ${label} heatmap within ${RENDER_TIMEOUT_MS / 1000} s.`);
    }, RENDER_TIMEOUT_MS);

    return () => {
      done = true;
      observer.disconnect();
      window.clearTimeout(timer);
      host.replaceChildren(); // removes the iframe: no leaked widgets
    };
  }, [dataSource, label, key]);

  return (
    <div className="relative h-full w-full">
      <div ref={hostRef} className="h-full w-full" />
      {status !== "ready" ? (
        <div className="absolute inset-0 flex items-center justify-center bg-surface">
          {status === "loading" ? (
            <StateView kind="loading" title={`Loading the ${label} heatmap`} message="Drawn by TradingView's embedded widget." />
          ) : (
            <StateView
              kind="error"
              title="Heatmap unavailable"
              message={state.reason}
              onRetry={() => setAttempt((a) => a + 1)}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}
