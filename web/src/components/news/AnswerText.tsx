/**
 * Renders a model answer as plain React elements. Handles the little markdown
 * the CLI tends to emit (**bold**, `code`, "- " / "1. " lists, "#" headings,
 * blank-line paragraphs) and drops any other markup characters. Never uses
 * dangerouslySetInnerHTML: the text is untrusted, and everything here is a text node.
 */
import type { ReactNode } from "react";

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // **bold** | `code`
  const re = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  const plain = (s: string) => s.replace(/(^|\s)[*_]{1,2}(?=\S)|(?<=\S)[*_]{1,2}(?=\s|$|[.,;:!?)])/g, "$1");
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(plain(text.slice(last, m.index)));
    if (m[1] !== undefined)
      out.push(
        <strong key={`${keyBase}-b${i++}`} className="font-semibold text-text">
          {m[1]}
        </strong>,
      );
    else
      out.push(
        <span key={`${keyBase}-c${i++}`} className="num text-[13px] text-text-2">
          {m[2]}
        </span>,
      );
    last = re.lastIndex;
  }
  if (last < text.length) out.push(plain(text.slice(last)));
  return out;
}

type Block = { kind: "p"; lines: string[] } | { kind: "h"; lines: string[] } | { kind: "ul" | "ol"; items: string[] };

function blocks(src: string): Block[] {
  const out: Block[] = [];
  let cur: Block | null = null;
  const flush = () => {
    if (cur) out.push(cur);
    cur = null;
  };
  for (const raw of src.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flush();
      continue;
    }
    const h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (h) {
      flush();
      out.push({ kind: "h", lines: [h[1]] });
      continue;
    }
    const ul = line.match(/^\s*[-*•]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const kind = ul ? "ul" : "ol";
      const text = (ul ?? ol)![1];
      if (!cur || cur.kind !== kind) {
        flush();
        cur = { kind, items: [] };
      }
      (cur as { items: string[] }).items.push(text);
      continue;
    }
    if (cur && (cur.kind === "ul" || cur.kind === "ol") && /^\s{2,}\S/.test(raw)) {
      const items = cur.items;
      items[items.length - 1] += ` ${line.trim()}`;
      continue;
    }
    if (!cur || cur.kind !== "p") {
      flush();
      cur = { kind: "p", lines: [] };
    }
    cur.lines.push(line.trim());
  }
  flush();
  return out;
}

export function AnswerText({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-3 text-sm leading-[1.55] text-[#D5DBE2]">
      {blocks(text).map((b, i) => {
        const k = `b${i}`;
        if (b.kind === "h")
          return (
            <p key={k} className="m-0 font-semibold text-text">
              {inline(b.lines.join(" "), k)}
            </p>
          );
        if (b.kind === "p")
          return (
            <p key={k} className="m-0">
              {b.lines.map((l, j) => (
                <span key={j}>
                  {j > 0 ? <br /> : null}
                  {inline(l, `${k}-${j}`)}
                </span>
              ))}
            </p>
          );
        const List = b.kind === "ul" ? "ul" : "ol";
        return (
          <List key={k} className={`m-0 flex flex-col gap-1.5 pl-5 ${b.kind === "ul" ? "list-disc" : "list-decimal"} marker:text-faint`}>
            {b.items.map((it, j) => (
              <li key={j}>{inline(it, `${k}-${j}`)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
