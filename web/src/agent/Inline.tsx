// Text from the model or from the drawing is data, never markup: it is rendered as React text. Only **bold** and `code` are
// recognised, and only to make a thought summary readable.
import type { ReactNode } from "react";

export function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
  return (
    <>
      {parts.map((p, i): ReactNode => {
        if (p.startsWith("**") && p.endsWith("**") && p.length > 4) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (p.startsWith("`") && p.endsWith("`") && p.length > 2) return <code key={i} className="rounded bg-slate-100 dark:bg-slate-800 px-1 text-[0.92em]">{p.slice(1, -1)}</code>;
        return p;
      })}
    </>
  );
}

export function Prose({ text, className = "" }: { text: string; className?: string }) {
  const paras = text.split(/\n{2,}/).filter((p) => p.trim());
  return (
    <div className={className}>
      {paras.map((p, i) => (
        <p key={i} className="whitespace-pre-wrap break-words [&:not(:first-child)]:mt-1.5">
          <Inline text={p} />
        </p>
      ))}
    </div>
  );
}
