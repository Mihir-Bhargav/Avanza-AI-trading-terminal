"use client";
/**
 * Colour-safe mode switch: swaps up/down green/red for blue/orange by setting
 * <html data-colorsafe="true">. Persisted per browser in localStorage.
 */
import { useSyncExternalStore } from "react";
import { cx } from "@/lib/cx";

const KEY = "range.colorsafe";

function subscribe(onChange: () => void) {
  const mo = new MutationObserver(onChange);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-colorsafe"] });
  return () => mo.disconnect();
}
const read = () => document.documentElement.dataset.colorsafe === "true";

export function setColorSafe(on: boolean) {
  if (on) document.documentElement.dataset.colorsafe = "true";
  else delete document.documentElement.dataset.colorsafe;
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* storage unavailable (private mode): the toggle still works for this page view */
  }
}

export function ColorSafeToggle({ className }: { className?: string }) {
  const on = useSyncExternalStore(subscribe, read, () => false);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => setColorSafe(!on)}
      className={cx("flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-[12px] text-muted hover:text-text-2", className)}
      title="Swap green/red for blue/orange"
    >
      <span
        aria-hidden="true"
        className={cx(
          "relative h-4 w-7 shrink-0 rounded-full border transition-colors",
          on ? "border-amber bg-amber/25" : "border-line-3 bg-surface",
        )}
      >
        <span
          className={cx(
            "absolute top-[2px] h-2.5 w-2.5 rounded-full transition-[left]",
            on ? "left-[13px] bg-amber" : "left-[2px] bg-muted",
          )}
        />
      </span>
      <span>Colour-safe</span>
      <span aria-hidden="true" className="num ml-auto text-[10px]">
        <span className="text-up">+</span> <span className="text-down">{"−"}</span>
      </span>
    </button>
  );
}
