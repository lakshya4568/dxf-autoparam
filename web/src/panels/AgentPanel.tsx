// The agent beside the drawing: its checklist and the facts it recorded about this sheet (stale ones marked), the runs of
// this session, and one instruction to start a run. A run calls a paid model, so it starts only after an explicit
// confirmation that names the model; reading the checklist, the runs and their progress costs nothing.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AgentNotes, RunProgress, RunSummary } from "../api/types";
import { useStore } from "../state/store";
import { loadAll, store } from "../state/workspace";

const ACTIVE = new Set(["queued", "running", "stopping"]);
const MARK: Record<string, string> = { todo: "○", doing: "◐", done: "●", blocked: "✗" };

function eventLine(e: RunProgress["events"][number]): string {
  if (e.kind === "tool") return `${e.ok === false ? "✗" : "·"} ${e.name ?? "tool"}${e.summary ? ` — ${String(e.summary).slice(0, 140)}` : ""}`;
  return String(e.said ?? e.text ?? e.summary ?? e.why ?? e.kind).slice(0, 200);
}

export function AgentPanel() {
  const { summary, selection, focus, revision } = useStore(store, (s) => ({ summary: s.summary, selection: s.selection, focus: s.focusView, revision: s.revision }));
  const [notes, setNotes] = useState<AgentNotes | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [model, setModel] = useState("");
  const [text, setText] = useState("");
  const [where, setWhere] = useState<"drawing" | "view" | "selection">("drawing");
  const [confirm, setConfirm] = useState<null | "start" | "continue">(null);
  const [prog, setProg] = useState<RunProgress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const events = useRef<RunProgress["events"]>([]);
  const since = useRef(0);

  const refresh = useCallback(() => {
    api.notes().then(setNotes).catch(() => setNotes(null));
    api.runs().then((r) => setRuns(r.runs)).catch(() => setRuns([]));
  }, []);

  useEffect(() => {
    if (!summary) return;
    refresh();
  }, [summary?.file, revision, refresh]);

  useEffect(() => {
    api.models().then((m) => { setModels(m.models); setModel((x) => x || m.default); }).catch(() => setModels([]));
  }, []);

  // follow the current run while it works (progress is read incrementally: only the new events)
  const runId = prog?.run ?? summary?.current_run ?? null;
  const active = prog ? ACTIVE.has(prog.status) : !!summary?.ai_running;
  useEffect(() => {
    if (!runId) return;
    let stop = false;
    const tick = async () => {
      try {
        const p = await api.progress(runId, since.current);
        events.current = events.current.concat(p.events).slice(-200);
        since.current = p.next;
        if (stop) return;
        setProg({ ...p, events: events.current });
        if (ACTIVE.has(p.status)) window.setTimeout(tick, 2000);
        else { refresh(); void loadAll(false); } // the run's results: the camera stays where it is
      } catch (e) {
        if (!stop) setErr((e as Error).message);
      }
    };
    void tick();
    return () => { stop = true; };
  }, [runId, active, refresh]);

  if (!summary) return <p className="p-3 text-sm text-slate-500">No drawing open.</p>;
  const scope = where === "selection" ? { entities: [...selection] } : where === "view" && focus ? { views: [focus] } : { kind: "drawing" };
  const modelLabel = models.find((m) => m.id === model)?.label ?? model;
  const start = async () => {
    setConfirm(null);
    setErr(null);
    try {
      const r = await api.startRun(text.trim(), scope, { model });
      events.current = [];
      since.current = 0;
      setProg({ run: r.run, status: "queued", events: [], next: 0 });
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const cont = async () => {
    setConfirm(null);
    if (!runId) return;
    try {
      await api.continueRun(runId, text.trim());
      setProg((p) => (p ? { ...p, status: "running" } : p));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const btn = "rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-[12px] hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40";

  return (
    <div className="p-2 text-[12px]" data-testid="agent-panel">
      <section className="mb-3">
        <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Checklist</h3>
        {notes?.checklist.length ? (
          <ul data-testid="checklist">
            {notes.checklist.map((c) => (
              <li key={c.id} className={c.status === "done" ? "text-slate-500" : c.status === "blocked" ? "text-red-600" : ""} title={c.evidence}>
                <span className="mr-1">{MARK[c.status] ?? "○"}</span>{c.text}
              </li>
            ))}
          </ul>
        ) : <p className="text-slate-500">No checklist yet: the agent writes one when it plans a task.</p>}
      </section>
      {notes && notes.learned.length > 0 && (
        <section className="mb-3">
          <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">What it learned about this sheet</h3>
          <ul>
            {notes.learned.map((f, j) => (
              <li key={j} className={f.stale ? "text-slate-400 line-through" : ""} title={f.evidence}>
                {f.about && <span className="mr-1 rounded bg-slate-100 dark:bg-slate-800 px-1">{f.about}</span>}{f.fact}{f.stale && <span className="ml-1 no-underline text-[10px]">(the drawing changed since)</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="mb-3 rounded border border-slate-200 dark:border-slate-700 p-2">
        <textarea className="w-full h-20 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 p-1.5" placeholder="What should the agent do? e.g. make this view parametric, name the values by what they are" value={text} onChange={(e) => setText(e.target.value)} data-testid="agent-instruction" />
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <select className="rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1 py-0.5" value={where} onChange={(e) => setWhere(e.target.value as typeof where)}>
            <option value="drawing">whole drawing</option>
            <option value="view" disabled={!focus}>focused view{focus ? ` (${focus})` : ""}</option>
            <option value="selection" disabled={!selection.size}>selection ({selection.size})</option>
          </select>
          <select className="min-w-0 flex-1 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1 py-0.5" value={model} onChange={(e) => setModel(e.target.value)} data-testid="agent-model">
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <button className={btn} disabled={!text.trim() || active} onClick={() => setConfirm("start")} data-testid="agent-start">Start…</button>
        </div>
        {confirm && (
          <div className="mt-2 rounded bg-amber-50 dark:bg-amber-950/40 p-2 text-amber-900 dark:text-amber-200" data-testid="agent-confirm">
            This {confirm === "start" ? "starts a run" : "continues the run"} on <b>{modelLabel}</b>, a paid model: every turn is billed. Go ahead?
            <div className="mt-1 flex gap-2">
              <button className="rounded bg-amber-600 px-2 py-0.5 text-white" onClick={() => void (confirm === "start" ? start() : cont())}>Yes, {confirm === "start" ? "start" : "continue"}</button>
              <button className={btn} onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        )}
        {err && <p className="mt-1 text-red-600">{err}</p>}
      </section>
      {prog && prog.run && (
        <section className="mb-3" data-testid="agent-run">
          <div className="flex items-center gap-2">
            <strong>{prog.run}</strong><span className="text-slate-500">{prog.label ?? prog.status}</span>
            <span className="ml-auto flex gap-1">
              {prog.can?.stop && <button className={btn} onClick={() => void api.stopRun(prog.run!)}>Stop</button>}
              {prog.can?.continue && <button className={btn} onClick={() => setConfirm("continue")}>Continue…</button>}
              {prog.can?.apply && <button className={btn} onClick={() => void api.applyRun(prog.run!).then(() => loadAll(false))}>Apply what holds</button>}
              {prog.can?.revert && <button className={btn} onClick={() => void api.revertRun(prog.run!).then(() => loadAll(false))}>Revert</button>}
            </span>
          </div>
          {prog.reason && <p className="text-slate-500">{prog.reason}</p>}
          <ol className="mt-1 max-h-72 overflow-auto font-mono text-[11px] leading-snug">
            {prog.events.slice(-60).map((e, j) => <li key={j} className={e.ok === false ? "text-red-600" : ""}>{eventLine(e)}</li>)}
          </ol>
        </section>
      )}
      {runs.length > 0 && (
        <section>
          <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Runs</h3>
          <ul>
            {runs.slice(0, 12).map((r) => (
              <li key={r.id} className="mb-0.5" title={r.instruction}>
                <span className="font-mono mr-1">{r.id}</span>
                <span className="text-slate-500">{r.label}</span>
                {r.verdict?.headline && <span className="block text-slate-500 truncate">{r.verdict.headline}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
