// A small status mark for a tool call or a run: a spinner while it works, a check, a cross, a hollow dot while it waits.
import type { ToolState } from "./model";

export function Spinner({ className = "" }: { className?: string }) {
  return <span aria-hidden className={`inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-[1.5px] border-blue-500 border-t-transparent dark:border-amber-400 dark:border-t-transparent ${className}`} />;
}

export function ToolMark({ state }: { state: ToolState }) {
  const base = "inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center text-[11px] leading-none";
  switch (state) {
    case "running":
      return <span className={base} role="img" aria-label="running"><Spinner /></span>;
    case "done":
      return <span className={`${base} text-emerald-600 dark:text-emerald-400`} role="img" aria-label="completed">✓</span>;
    case "failed":
      return <span className={`${base} text-red-600 dark:text-red-400`} role="img" aria-label="failed">✗</span>;
    case "queued":
      return <span className={`${base} text-slate-400`} role="img" aria-label="queued">○</span>;
    default:
      return <span className={`${base} text-amber-600`} role="img" aria-label="interrupted">–</span>;
  }
}

export const STATE_LABEL: Record<ToolState, string> = { running: "Running", queued: "Queued", done: "Completed", failed: "Failed", interrupted: "Not finished" };
