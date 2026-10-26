"use client";
/**
 * Ask Kes: POST /api/ai/ask, which runs the local `claude` CLI with prices,
 * levels, strategy signals and news as context. It can take one to three minutes, so the panel
 * shows elapsed time and lets you cancel. The backend has no cancel route:
 * cancelling stops waiting and discards the answer; the CLI run finishes on its own.
 * The conversation lives in component state only.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { askKes, ApiError } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtClock } from "@/lib/format";
import { useNow } from "@/lib/useNow";
import { describeError } from "../StateView";
import { Button } from "../Button";
import { Kes } from "../Kes";
import { AnswerText } from "./AnswerText";

type Msg =
  | { id: number; role: "user"; text: string; symbols: string[]; at: string }
  | { id: number; role: "kes"; text: string; symbols: string[]; at: string; seconds: number }
  | { id: number; role: "error"; title: string; text: string; at: string };

const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-^=]{0,15}$/;

function suggestions(symbols: string[]): string[] {
  const s = symbols[0];
  if (s)
    return [
      `Why is ${s} moving today, and what explains it?`,
      `What do the levels and strategy signals say about ${s} right now?`,
      `What would a take-profit and stop-loss look like for ${s} at the leverage cap?`,
    ];
  return [
    "Which setups on the watchlist are closest to a zone right now?",
    "What moved the market today?",
    "Which watchlist names have earnings in the next week?",
  ];
}

export function AskKes({ initialSymbols = [], prefill = false }: { initialSymbols?: string[]; prefill?: boolean }) {
  const [symbols, setSymbols] = useState<string[]>(initialSymbols);
  const [draft, setDraft] = useState(() => (prefill && initialSymbols.length ? suggestions(initialSymbols)[0] : ""));
  const [adding, setAdding] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [pending, setPending] = useState<{ id: number; started: number; symbols: string[] } | null>(null);
  const seq = useRef(0);
  /** Id of the question being waited on; null after an answer or a cancel. */
  const waiting = useRef<number | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const now = useNow(1000);
  const hintId = useId();

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [msgs.length, pending]);

  const elapsed = pending && now !== null ? Math.max(0, Math.round((now - pending.started) / 1000)) : 0;

  async function send(question: string) {
    const q = question.trim();
    if (!q || pending) return;
    const id = ++seq.current;
    const at = new Date().toISOString();
    const started = Date.now();
    const syms = [...symbols];
    const history = msgs
      .filter((m): m is Extract<Msg, { role: "user" | "kes" }> => m.role === "user" || m.role === "kes")
      .slice(-6)
      .map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { id, role: "user", text: q, symbols: syms, at }]);
    setDraft("");
    setPending({ id, started, symbols: syms });
    const market = syms.length && syms.every((s) => s.endsWith(".ST")) ? "sweden" : "us";
    waiting.current = id;
    const settle = (msg: Msg) => {
      if (waiting.current !== id) return; // cancelled: drop the answer
      waiting.current = null;
      setPending(null);
      setMsgs((m) => [...m, msg]);
    };
    try {
      const res = await askKes({ question: q, symbols: syms.length ? syms : undefined, market, history });
      const seconds = Math.round((Date.now() - started) / 1000);
      const at2 = new Date().toISOString();
      settle(
        "answer" in res
          ? { id, role: "kes", text: res.answer, symbols: res.symbols, at: at2, seconds }
          : { id, role: "error", title: "Kes couldn't answer", text: res.error, at: at2 },
      );
    } catch (e) {
      const d = describeError(e);
      settle({
        id,
        role: "error",
        title: e instanceof ApiError && e.unreachable ? d.title : "Kes couldn't answer",
        text: d.message,
        at: new Date().toISOString(),
      });
    }
  }

  function cancel() {
    if (!pending) return;
    const id = pending.id;
    waiting.current = null;
    setPending(null);
    setMsgs((m) => [
      ...m,
      {
        id,
        role: "error",
        title: "Cancelled",
        text: "Stopped waiting. The local claude run may still finish in the background; its answer will be discarded.",
        at: new Date().toISOString(),
      },
    ]);
    inputRef.current?.focus();
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function addSymbol(e: FormEvent) {
    e.preventDefault();
    const s = adding.trim().toUpperCase();
    if (SYMBOL_RE.test(s) && !symbols.includes(s) && symbols.length < 8) setSymbols([...symbols, s]);
    setAdding("");
  }

  return (
    <section aria-labelledby="ask-h" className="flex min-h-0 w-[520px] shrink-0 flex-col overflow-hidden rounded-[16px] border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-raised px-5 pb-3 pt-4">
        <Kes mood={pending ? "thinking" : "watching"} size={32} perch="none" />
        <h2 id="ask-h" className="m-0 text-base font-semibold text-text">
          Ask Kes
        </h2>
        <span className="num text-[11px] text-muted">CONTEXT</span>
        <ul className="m-0 flex list-none flex-wrap items-center gap-1.5 p-0" aria-label="Context sent with each question">
          {symbols.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => setSymbols(symbols.filter((x) => x !== s))}
                disabled={!!pending}
                aria-label={`Remove ${s} from context`}
                className="num flex items-center gap-1 rounded-chip bg-raised px-2 py-0.5 text-[11px] text-text-2 hover:bg-seg-on disabled:opacity-60"
              >
                {s} <span aria-hidden="true" className="text-faint">×</span>
              </button>
            </li>
          ))}
          <li className="num rounded-chip bg-raised px-2 py-0.5 text-[11px] text-soft">Watchlist</li>
          <li className="num rounded-chip bg-raised px-2 py-0.5 text-[11px] text-soft">Market news</li>
        </ul>
        <form onSubmit={addSymbol} className="ml-auto">
          <label className="sr-only" htmlFor="ask-add">
            Add a ticker to the context
          </label>
          <input
            id="ask-add"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            placeholder="+ ticker"
            disabled={!!pending || symbols.length >= 8}
            autoComplete="off"
            spellCheck={false}
            className="num h-6 w-[72px] rounded-chip border border-line-2 bg-rail px-2 text-[11px] text-text-2 outline-none placeholder:text-placeholder focus:border-line-3"
          />
        </form>
      </div>

      <div ref={scroller} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-[18px]" aria-live="polite">
        {msgs.length === 0 && !pending ? (
          <div className="m-auto flex max-w-[400px] flex-col items-center gap-3 text-center">
            <Kes mood="watching" size={64} />
            <p className="m-0 text-[13px] leading-[1.5] text-muted">
              Ask about a ticker, a setup or the market. I read live prices, CPR levels, strategy signals and headlines
              {symbols.length ? ` for ${symbols.join(", ")}` : " for your watchlist"}, and say how old each number is.
            </p>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {suggestions(symbols).map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(q);
                      inputRef.current?.focus();
                    }}
                    className="rounded-control border border-line-2 px-3 py-1.5 text-left text-[13px] text-soft hover:border-line-3 hover:text-text"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={`u${m.id}`} className="flex max-w-[400px] flex-col items-end gap-1 self-end">
              <div className="whitespace-pre-wrap rounded-[12px_12px_4px_12px] bg-[#1F2630] px-3.5 py-3 text-sm leading-[1.45] text-text-2">
                {m.text}
              </div>
              <span className="num text-[10px] text-faint">
                {fmtClock(m.at)}
                {m.symbols.length ? ` · ${m.symbols.join(", ")}` : " · watchlist"}
              </span>
            </div>
          ) : m.role === "kes" ? (
            <div key={`k${m.id}`} className="flex gap-3">
              <Kes mood="watching" size={34} perch="none" className="shrink-0" />
              <div className="flex min-w-0 flex-col gap-2">
                <AnswerText text={m.text} />
                <span className="num text-[11px] text-faint">
                  Answered {fmtClock(m.at)} · took {m.seconds}s
                  {m.symbols.length ? ` · context ${m.symbols.join(", ")}` : ""}
                </span>
              </div>
            </div>
          ) : (
            <div key={`e${m.id}-${m.at}`} role="alert" className="flex gap-3">
              <Kes mood={m.title === "Cancelled" ? "cautious" : "alert"} size={34} perch="none" className="shrink-0" />
              <div className="flex min-w-0 flex-col gap-1 text-[13px] leading-[1.5]">
                <span className={cx("font-semibold", m.title === "Cancelled" ? "text-soft" : "text-warn-text")}>{m.title}</span>
                <span className="break-words text-muted">{m.text}</span>
              </div>
            </div>
          ),
        )}

        {pending ? (
          <div className="flex items-start gap-3" role="status">
            <Kes mood="thinking" size={34} perch="none" className="shrink-0" />
            <div className="flex flex-col gap-1.5">
              <span className="text-[13px] text-soft">
                Thinking… <span className="num text-text-2">{elapsed}s</span>
              </span>
              <span className="text-xs leading-[1.45] text-faint">
                Reading prices, levels and news{pending.symbols.length ? ` for ${pending.symbols.join(", ")}` : ""}. This usually takes one to
                three minutes.
              </span>
              <Button variant="outline" size="sm" className="self-start" onClick={cancel}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      <form onSubmit={onSubmit} className="flex gap-2.5 border-t border-raised px-5 pb-2 pt-3.5">
        <label className="flex flex-1">
          <span className="sr-only">Ask Kes about markets, a ticker or a setup</span>
          <textarea
            ref={inputRef}
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(draft);
              }
            }}
            aria-describedby={hintId}
            placeholder="Ask Kes about markets, a ticker, or a setup"
            className="flex-1 resize-none rounded-control border border-line-2 bg-rail px-3 py-2.5 font-sans text-sm text-text-2 outline-none placeholder:text-placeholder focus:border-line-3"
          />
        </label>
        <button
          type="submit"
          disabled={!!pending || !draft.trim()}
          className="w-[88px] rounded-control bg-amber text-sm font-semibold text-on-amber transition-colors hover:bg-amber-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          Ask
        </button>
      </form>
      <p id={hintId} className="m-0 px-5 pb-3 text-[11px] text-faint">
        Answers cite their data and its age. Kes never places orders. Enter to send, Shift+Enter for a new line.
      </p>
    </section>
  );
}
