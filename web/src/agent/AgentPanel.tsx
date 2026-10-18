// The agent beside the drawing: a conversation. The header says what the run is doing (from the engine's own state), the thread
// holds the person's messages and the agent's folded activity, the composer is always at the foot. Compact and verbose are two
// levels of detail over the same data.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useStore } from "../state/store";
import { agent, currentRun, dismissError, initAgent, isActive, setDraft, setMode, stop } from "../state/agent";
import { AgentBubble, EarlierBubble, UserBubble } from "./Messages";
import { Composer } from "./Composer";
import { buildConversation, lifecycle, type Life } from "./model";
import { Gallery, Lightbox, PicturesButton } from "./Pictures";
import { Spinner } from "./StatusMark";
import { store as workspace } from "../state/workspace";

const DOT: Record<string, string> = { info: "bg-slate-400", ok: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500" };

export function StatusPill({ life }: { life: Life }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px]" data-testid="life" data-life={life.key} role="status">
      {life.active ? <Spinner /> : <span className={`h-2 w-2 rounded-full ${DOT[life.tone]}`} />}
      <span className="font-medium">{life.label}</span>
    </span>
  );
}

function Plan() {
  const notes = useStore(agent, (s) => s.notes);
  const [open, setOpen] = useState(false);
  if (!notes || (!notes.checklist.length && !notes.learned.length)) return null;
  const done = notes.checklist.filter((c) => c.status === "done").length;
  return (
    <div className="border-b border-slate-200 dark:border-slate-700 px-3 py-1.5 text-[12px]" data-testid="plan">
      <button className="flex w-full items-center gap-1.5 text-left text-slate-600 dark:text-slate-300" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={`text-[10px] transition-transform ${open ? "rotate-90" : ""}`}>›</span>
        Plan {notes.checklist.length ? `${done}/${notes.checklist.length}` : ""}{notes.learned.length ? ` · ${notes.learned.length} fact${notes.learned.length === 1 ? "" : "s"} learned` : ""}
      </button>
      {open && (
        <div className="mt-1">
          <ul>{notes.checklist.map((c) => <li key={c.id} className={c.status === "done" ? "text-slate-400 line-through" : c.status === "blocked" ? "text-red-600" : ""} title={c.evidence}>{c.status === "done" ? "●" : c.status === "doing" ? "◐" : c.status === "blocked" ? "✗" : "○"} {c.text}</li>)}</ul>
          {notes.learned.length > 0 && <ul className="mt-1 text-slate-500">{notes.learned.map((f, i) => <li key={i} className={f.stale ? "line-through opacity-60" : ""} title={f.evidence}>· {f.fact}{f.stale ? " (the drawing changed since)" : ""}</li>)}</ul>}
        </div>
      )}
    </div>
  );
}

const STARTERS = ["Name the values by what they are", "Make this view parametric", "What changes if the span grows by 5%?"];

function Empty() {
  return (
    <div className="px-4 py-8 text-center" data-testid="agent-empty">
      <div className="text-[14px] font-medium">Work with the agent on this drawing</div>
      <p className="mx-auto mt-1 max-w-[30ch] text-[12px] text-slate-500">Describe what you want. It reads the drawing, uses the engine’s tools and shows every step; the engine checks each change before it is kept.</p>
      <div className="mt-3 flex flex-wrap justify-center gap-1.5">
        {STARTERS.map((t) => <button key={t} className="rounded-full border border-slate-300 dark:border-slate-600 px-2.5 py-0.5 text-[12px] text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => setDraft(t)}>{t}</button>)}
      </div>
    </div>
  );
}

export function AgentPanel() {
  const s = useStore(agent, (x) => ({ mode: x.mode, runs: x.runs, order: x.order, currentId: x.currentId, busy: x.busy, error: x.error, model: x.model, gallery: x.gallery.open }));
  const hasSheet = useStore(workspace, (x) => !!x.summary);
  const run = currentRun({ ...agent.get(), runs: s.runs, currentId: s.currentId });
  const life = lifecycle(run, s.busy === "starting");
  const messages = buildConversation(s.order.map((id) => s.runs[id]).filter(Boolean), s.currentId);
  const scroller = useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = useState(true);
  const events = run?.events.length ?? 0;

  useEffect(() => { void initAgent(); }, []);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stuck) el.scrollTop = el.scrollHeight;
  }, [messages.length, events, stuck, life.key]);

  const usage = run?.progress?.usage;
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="agent-panel" data-mode={s.mode}>
      <header className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 px-3 py-2">
        <StatusPill life={life} />
        {run && <span className="font-mono text-[11px] text-slate-400" title={run.progress?.instruction}>{run.id}</span>}
        <span className="min-w-0 flex-1 truncate text-[12px] text-slate-500" title={life.detail}>{life.detail}</span>
        {isActive(run) && <button className="rounded border border-red-300 px-1.5 text-[11px] text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30" onClick={() => void stop()}>Stop</button>}
        <PicturesButton />
        <div className="flex overflow-hidden rounded border border-slate-300 dark:border-slate-600 text-[11px]" role="group" aria-label="Detail level">
          {(["compact", "verbose"] as const).map((m) => (
            <button key={m} className={`px-2 py-0.5 ${s.mode === m ? "bg-slate-200 dark:bg-slate-700 font-medium" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`} onClick={() => setMode(m)} aria-pressed={s.mode === m} data-testid={`mode-${m}`}>{m === "compact" ? "Compact" : "Verbose"}</button>
          ))}
        </div>
      </header>
      <Plan />
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto px-3 py-3" data-testid="thread" onScroll={(e) => { const el = e.currentTarget; setStuck(el.scrollHeight - el.scrollTop - el.clientHeight < 80); }}>
          {!hasSheet ? <p className="text-center text-[12px] text-slate-500">Open a DXF to work with the agent.</p>
            : messages.length === 0 ? <Empty />
            : (
              <div className="space-y-3">
                {messages.map((m) => m.type === "user" ? <UserBubble key={m.key} m={m} /> : m.type === "earlier" ? <EarlierBubble key={m.key} m={m} /> : <AgentBubble key={m.key} m={m} life={life} />)}
              </div>
            )}
        </div>
        {s.gallery && <Gallery />}
      </div>
      {!stuck && messages.length > 0 && (
        <button className="mx-auto -mt-8 mb-1 rounded-full border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-2.5 py-0.5 text-[11px] shadow" onClick={() => { setStuck(true); const el = scroller.current; if (el) el.scrollTop = el.scrollHeight; }}>Jump to latest ↓</button>
      )}
      {s.error && (
        <div className="mx-2 mb-1 flex items-start gap-2 rounded border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 px-2 py-1 text-[12px] text-red-700 dark:text-red-300" role="alert" data-testid="agent-error">
          <span className="min-w-0 flex-1 break-words">{s.error}</span>
          <button onClick={dismissError} aria-label="Dismiss">✕</button>
        </div>
      )}
      {usage && (
        <div className="px-3 pb-0.5 text-[10.5px] text-slate-400 num" data-testid="usage">
          turn {usage.turns ?? 0}{usage.limits?.max_turns ? ` of ${usage.limits.max_turns}` : ""} · {usage.tool_calls ?? 0} tool calls · {Number(usage.tokens ?? 0).toLocaleString()} tokens
        </div>
      )}
      <Composer life={life} />
      <Lightbox />
    </div>
  );
}
