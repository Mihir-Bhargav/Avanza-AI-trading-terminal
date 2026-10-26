"use client";
/** Terminal header: command bar (⌘K / Ctrl+K), exchange session pills, live clock. */
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { parseCommand } from "@/lib/commands";
import { cx } from "@/lib/cx";
import { fmtWallClock, isVenueOpen, VENUES } from "@/lib/sessions";
import { useNow } from "@/lib/useNow";

const noopSubscribe = () => () => {};
const detectMac = () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function CommandBar() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const errorId = useId();
  const isMac = useSyncExternalStore(noopSubscribe, detectMac, () => true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const r = parseCommand(value);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    setError(null);
    setValue("");
    inputRef.current?.blur();
    router.push(r.href);
  };

  return (
    <form role="search" onSubmit={submit} className="relative w-full max-w-[520px] min-w-[260px] flex-1">
      <label className="flex h-9 items-center gap-2.5 rounded-lg border border-line-2 bg-surface pl-3 pr-1.5 focus-within:border-line-3">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#8A939E" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setValue("");
              setError(null);
              e.currentTarget.blur();
            }
          }}
          aria-label="Search a ticker or type a command"
          aria-keyshortcuts="Meta+K Control+K"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          placeholder="Search a ticker or type a command — MU GP, MAP, PORT, N"
          autoComplete="off"
          spellCheck={false}
          className="min-w-0 flex-1 border-0 bg-transparent font-sans text-[13px] text-text-2 outline-none focus-visible:outline-none"
        />
        <kbd className="num rounded border border-line-3 px-1.5 py-px text-[11px] text-muted" aria-hidden="true">
          {isMac ? "⌘K" : "Ctrl K"}
        </kbd>
        <button
          type="submit"
          className="num flex h-[22px] items-center rounded-[5px] bg-amber px-2 text-[10px] font-bold tracking-[0.8px] text-on-amber hover:bg-amber-hover"
        >
          GO
        </button>
      </label>
      <div aria-live="assertive" className="absolute left-0 top-[calc(100%+6px)] z-20">
        {error ? (
          <p id={errorId} className="m-0 rounded-lg border border-line-2 bg-surface px-3 py-2 text-xs text-warn-text shadow-lg">
            {error}
          </p>
        ) : null}
      </div>
    </form>
  );
}

function Sessions({ now }: { now: number | null }) {
  return (
    <ul aria-label="Exchange sessions (regular hours schedule)" className="m-0 flex list-none gap-2 p-0">
      {VENUES.map((v) => {
        const open = now === null ? null : isVenueOpen(v, new Date(now));
        const state = open === null ? "…" : open ? "Open" : "Closed";
        return (
          <li
            key={v.code}
            title={`${v.name}: regular hours ${v.open.map((n) => String(n).padStart(2, "0")).join(":")}–${v.close
              .map((n) => String(n).padStart(2, "0"))
              .join(":")} local, weekdays. Holidays not modelled.`}
            className="flex h-7 items-center gap-[7px] rounded-[14px] border border-line-2 px-2.5 text-xs text-soft"
          >
            <span aria-hidden="true" className={cx("h-[7px] w-[7px] rounded-full", open ? "bg-up" : "bg-line-3")} />
            <span className="num text-[11px] text-text-2">{v.code}</span>
            <span>{state}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function Header() {
  const now = useNow(1000);
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line px-6">
      <CommandBar />
      <div className="ml-auto hidden lg:block">
        <Sessions now={now} />
      </div>
      <time className="num w-[104px] shrink-0 text-right text-xs text-muted" suppressHydrationWarning>
        {now === null ? "" : fmtWallClock(new Date(now))}
      </time>
    </header>
  );
}
