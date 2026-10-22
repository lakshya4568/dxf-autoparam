// The agent's work, as a coding agent shows it: a line saying what it is doing, then the tools it used — by name, nothing they returned.
// Its thinking is a section of its own, shut until the person opens it. The activity is open while the agent works, waits for a decision
// or is paused, and folds into one line once the work has ended (the person's own opening or closing wins over both).
import { useStore } from "../state/store";
import { agent, toggleFold } from "../state/agent";
import { Prose } from "./Inline";
import { countCalls, stepLine, thoughtsOf, type AgentMessage, type Item, type Life, type Tone } from "./model";
import { Spinner } from "./StatusMark";
import { ToolRow } from "./ToolRow";

const TONE: Record<Tone, string> = {
  info: "text-slate-500 dark:text-slate-400",
  ok: "text-emerald-700 dark:text-emerald-400",
  warn: "text-amber-700 dark:text-amber-400",
  bad: "text-red-700 dark:text-red-400",
};

function useFold(key: string, dflt: boolean): [boolean, () => void] {
  const stored = useStore(agent, (s) => s.folds[key]);
  const open = stored ?? dflt;
  return [open, () => toggleFold(key, open)];
}

/** The agent's thinking summaries, turn by turn: hidden by default, opened on demand. */
export function Thinking({ m }: { m: AgentMessage }) {
  const thoughts = thoughtsOf(m);
  const [open, toggle] = useFold(`${m.key}/thinking`, false);
  if (!thoughts.length) return null;
  return (
    <div data-testid="thinking" data-open={open}>
      <button className="flex items-center gap-1 text-[12px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-200" onClick={toggle} aria-expanded={open}>
        <span className={`text-[10px] transition-transform ${open ? "rotate-90" : ""}`}>›</span>Thinking
        <span className="text-slate-400">· {thoughts.length} turn{thoughts.length === 1 ? "" : "s"}</span>
      </button>
      {open && (
        <div className="ml-3 mt-1 space-y-2 border-l border-slate-200 dark:border-slate-700 pl-2.5" data-testid="thinking-body">
          {thoughts.map((t) => (
            <div key={t.turn}>
              <div className="text-[10.5px] uppercase tracking-wide text-slate-400">Turn {t.turn}</div>
              <Prose text={t.text} className="text-[12px] text-slate-600 dark:text-slate-300" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ItemView({ item }: { item: Item }) {
  switch (item.type) {
    case "step": {
      const line = stepLine(item.step);
      return (
        <div className="py-1" data-testid="step">
          {line && <p className="break-words text-[13px] text-slate-700 dark:text-slate-200" data-testid="progress">{line}</p>}
          {item.step.calls.length > 0 && (
            <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
              {item.step.calls.map((c) => <ToolRow key={c.id} call={c} />)}
            </div>
          )}
        </div>
      );
    }
    case "notice":
      return <div className={`py-0.5 text-[12px] break-words ${TONE[item.tone]}`} data-testid="notice" data-tone={item.tone}>{item.text}</div>;
    case "applied":
      return <div className="py-0.5 text-[12px] text-emerald-700 dark:text-emerald-400" data-testid="applied">✓ {item.text}</div>;
  }
}

export function ActivityBlock({ m, life }: { m: AgentMessage; life: Life | null }) {
  const live = !!life?.active && m.last;
  const ended = ["completed", "partial", "failed", "stopped", "exhausted"].includes(m.ended?.to ?? "");
  const [open, toggle] = useFold(`${m.key}/activity`, m.last && !ended);
  const c = countCalls(m);
  const calls = `${c.calls} tool call${c.calls === 1 ? "" : "s"}`;
  let title: string;
  if (live) title = life!.label;
  else if (m.ended?.to === "stopped") title = c.calls ? `Stopped after ${calls}` : "Stopped before any tool call";
  else if (m.ended?.to === "failed") title = c.calls ? `Failed after ${calls}` : "Failed before any tool call";
  else if (m.ended?.to === "paused" || m.ended?.to === "exhausted") title = c.calls ? `Paused after ${calls}` : "Paused";
  else if (m.ended?.to === "awaiting_user") title = c.calls ? `Worked through ${calls}, then asked you` : "Asked you";
  else if (m.ended) title = c.calls ? `Worked through ${calls}` : "Finished without tool calls";
  else title = c.calls ? calls : "Activity";
  if (m.items.length === 0 && !live) return null;
  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-700/80" data-testid="activity" data-open={open} data-live={live}>
      <button className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left" onClick={toggle} aria-expanded={open}>
        {live ? <Spinner /> : <span className={`text-[10px] text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}>›</span>}
        <span className="text-[13px] font-medium">{title}</span>
        {live && life!.detail ? <span className="min-w-0 flex-1 truncate text-[12px] text-slate-500 dark:text-slate-400">{life!.detail}</span> : <span className="flex-1" />}
        <span className="shrink-0 text-[11px] text-slate-400 num">{c.calls ? `${c.calls} call${c.calls === 1 ? "" : "s"}` : ""}{c.failed ? ` · ${c.failed} failed` : ""}</span>
      </button>
      {open && (
        <div className="border-t border-slate-200 dark:border-slate-700/80 px-2.5 py-1.5" data-testid="activity-body">
          {m.items.map((it, i) => <ItemView key={`${m.key}/${i}`} item={it} />)}
          {live && m.items.length === 0 && <div className="text-[12px] text-slate-400">Waiting for the first event…</div>}
        </div>
      )}
    </div>
  );
}
