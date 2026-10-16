// One tool call: its real name, what the engine says it is doing, its status, and — when opened — the arguments it was given and what it
// returned. Failures say why without being opened. Large values are cut (and say so); nothing is dropped silently.
import { useState } from "react";
import { fmtMs, type ToolCall } from "./model";
import { STATE_LABEL, ToolMark } from "./StatusMark";

const LIMIT = 6000;

export function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null || (typeof value === "string" && !value)) return null;
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  const cut = text.length > LIMIT;
  return (
    <div className="mt-1.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <pre className="mt-0.5 max-h-56 overflow-auto rounded bg-slate-50 dark:bg-slate-900/70 p-2 text-[11px] leading-snug whitespace-pre-wrap break-words">{cut ? text.slice(0, LIMIT) : text}</pre>
      {cut && <div className="text-[10px] text-slate-400">… {(text.length - LIMIT).toLocaleString()} more characters not shown</div>}
    </div>
  );
}

export function ToolRow({ call, runId, open, onToggle }: { call: ToolCall; runId: string; open: boolean; onToggle: () => void }) {
  const [zoom, setZoom] = useState(false);
  const detail = call.args !== undefined || call.result !== undefined || !!call.image;
  const tone = call.state === "failed" ? "text-red-700 dark:text-red-300" : "";
  return (
    <div className="py-0.5" data-testid="tool-row" data-state={call.state} data-tool={call.name}>
      <button className="group flex w-full items-baseline gap-2 text-left" onClick={onToggle} aria-expanded={open} disabled={!detail}>
        <span className="self-center"><ToolMark state={call.state} /></span>
        <code className={`shrink-0 text-[12px] font-medium ${tone}`}>{call.name}</code>
        <span className={`min-w-0 flex-1 truncate text-[12px] text-slate-500 dark:text-slate-400 ${tone}`} title={call.doing}>{call.doing}</span>
        {call.unit && <span className="shrink-0 rounded bg-slate-100 dark:bg-slate-800 px-1 text-[10px] text-slate-500">{call.unit}</span>}
        <span className="shrink-0 text-[11px] text-slate-400 num">{call.state === "done" || call.state === "failed" ? fmtMs(call.ms) : STATE_LABEL[call.state]}</span>
        {detail && <span className={`shrink-0 text-[10px] text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}>›</span>}
      </button>
      {call.said && <div className="ml-[22px] text-[12px] italic text-slate-500 dark:text-slate-400">“{call.said}”</div>}
      {call.summary && <div className={`ml-[22px] text-[12px] ${call.state === "failed" ? tone : "text-slate-600 dark:text-slate-300"}`}>{call.summary}</div>}
      {call.state === "failed" && call.why && call.why !== call.summary && <div className="ml-[22px] text-[12px] text-red-700 dark:text-red-300 break-words">{call.why}</div>}
      {open && (
        <div className="ml-[22px]">
          <JsonBlock label="Input" value={call.args} />
          <JsonBlock label="Output" value={call.result} />
          {call.image?.id && (
            <div className="mt-1.5">
              <a href={`/api/sheet/ai/image?run=${encodeURIComponent(runId)}&id=${encodeURIComponent(call.image.id)}`} target="_blank" rel="noreferrer" onClick={(e) => { if (!zoom) { e.preventDefault(); setZoom(true); } }}>
                <img loading="lazy" alt={`picture ${call.image.id}`} className={`rounded border border-slate-200 dark:border-slate-700 bg-white ${zoom ? "max-w-full" : "max-h-24"}`} src={`/api/sheet/ai/image?run=${encodeURIComponent(runId)}&id=${encodeURIComponent(call.image.id)}`} />
              </a>
              <div className="text-[10px] text-slate-400">{call.image.id}{call.image.revision !== undefined ? ` · revision ${call.image.revision}` : ""} — click to enlarge, again to open</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
