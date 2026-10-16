// The persistent message composer. Enter sends, Shift+Enter is a new line. While the agent works the send button becomes Stop. Sending
// calls a paid model, so the first send for a model (per page session) asks, naming the model; the model, the scope and the cost are
// always visible under the box.
import { useEffect, useRef } from "react";
import { useStore } from "../state/store";
import { agent, cancelCost, canSend, confirmCost, costAccepted, currentRun, isActive, requestResume, requestSend, setDraft, setModel, setScopeKind, stop } from "../state/agent";
import { store as workspace } from "../state/workspace";
import type { Life } from "./model";

export function Composer({ life }: { life: Life }) {
  const s = useStore(agent, (x) => ({ draft: x.draft, models: x.models, model: x.model, busy: x.busy, confirm: x.confirm, scopeKind: x.scopeKind, run: currentRun(x), ok: canSend(x), paid: costAccepted(x) }));
  const ws = useStore(workspace, (x) => ({ sel: x.selection.size, view: x.focusView }));
  const box = useRef<HTMLTextAreaElement>(null);
  const active = isActive(s.run);
  const can = s.run?.progress?.can;
  const awaiting = !!can?.answer;
  const resumable = !!can?.continue;
  const modelLabel = s.models.find((m) => m.id === s.model)?.label ?? s.model;

  // grow with the text, to a limit
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [s.draft]);

  const placeholder = active ? "The agent is working — Stop it to send something else"
    : awaiting ? "Answer above, or say in your own words what to do…"
    : resumable ? "Add a note and continue, or give a new instruction…"
    : "Tell the agent what to do with this drawing…";

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (active || s.busy) return;
      if (awaiting) {
        if (s.draft.trim()) requestResume();
      } else requestSend();
    } else if (e.key === "Escape" && active) void stop();
  };

  const scopeLabel = s.scopeKind === "auto" ? (ws.sel ? `selection (${ws.sel})` : ws.view ? `view ${ws.view}` : "whole drawing") : s.scopeKind;

  return (
    <div className="border-t border-slate-200 dark:border-slate-700 p-2" data-testid="composer">
      {s.confirm && (
        <div className="mb-2 rounded border border-amber-300 dark:border-amber-700/70 bg-amber-50 dark:bg-amber-950/30 p-2 text-[12px]" role="alertdialog" data-testid="cost-confirm">
          This calls <b>{modelLabel}</b>, a paid model: every turn is billed. Go ahead?
          <div className="mt-1.5 flex gap-2">
            <button className="rounded bg-amber-600 px-2 py-0.5 text-white" onClick={confirmCost} data-testid="cost-yes">Yes, use {modelLabel}</button>
            <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5" onClick={cancelCost}>Cancel</button>
          </div>
        </div>
      )}
      <div className="rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/40">
        <textarea ref={box} rows={1} value={s.draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} placeholder={placeholder} aria-label="Message to the agent" data-testid="composer-input"
          className="block w-full resize-none bg-transparent px-3 pt-2 pb-1 text-[13px] outline-none placeholder:text-slate-400" />
        <div className="flex items-center gap-2 px-2 pb-1.5">
          <select className="min-w-0 max-w-[9rem] truncate rounded bg-transparent text-[11px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-200" value={s.scopeKind} onChange={(e) => setScopeKind(e.target.value as typeof s.scopeKind)} title="Where the instruction applies" data-testid="scope">
            <option value="auto">Scope: {scopeLabel}</option>
            <option value="drawing">Whole drawing</option>
            <option value="view" disabled={!ws.view}>Focused view{ws.view ? ` (${ws.view})` : ""}</option>
            <option value="selection" disabled={!ws.sel}>Selection ({ws.sel})</option>
          </select>
          <span className="flex-1" />
          {active ? (
            <button className="rounded-md bg-red-600 px-2.5 py-1 text-[12px] font-medium text-white disabled:opacity-50" onClick={() => void stop()} disabled={s.busy === "stopping" || life.key === "stopping"} data-testid="stop" title="Stop the run (Esc)">
              {s.busy === "stopping" || life.key === "stopping" ? "Stopping…" : "Stop"}
            </button>
          ) : (
            <button className="rounded-md bg-blue-600 px-2.5 py-1 text-[12px] font-medium text-white disabled:opacity-40" onClick={() => (awaiting ? requestResume() : requestSend())} disabled={!s.ok && !(awaiting && s.draft.trim()) || s.busy !== null} data-testid="send" title="Send (Enter)">
              {resumable && s.draft.trim() ? "Continue" : "Send"}
            </button>
          )}
        </div>
      </div>
      <div className="mt-1 flex items-center gap-2 px-1 text-[11px] text-slate-400">
        <select className="min-w-0 truncate rounded bg-transparent hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-60" value={s.model} onChange={(e) => setModel(e.target.value)} disabled={active} data-testid="model" title="The model that runs the agent">
          {s.models.length === 0 && <option value="">no model</option>}
          {s.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
        <span className="whitespace-nowrap" title="Enter sends, Shift+Enter starts a new line">{s.paid ? "cost accepted" : "paid · billed per turn"}</span>
      </div>
    </div>
  );
}
