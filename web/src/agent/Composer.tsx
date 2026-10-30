// The persistent message composer. Enter sends, Shift+Enter is a new line. While the agent works the box stays open: Enter says it to the
// agent, which reads it on its next turn (Stop is its own button). Sending calls a paid model, so the first send for a model (per page
// session) asks, naming the model (a model listed as free does not ask); the model, the library, how often it pauses, the scope and the cost are always visible under the box.
// Pictures (a screenshot of the drawing, a photo, a page of a standard) go with the message: chosen, pasted or dropped onto the box.
import { useEffect, useRef, useState } from "react";
import { useStore } from "../state/store";
import { addPictures, agent, canNote, cancelCost, canSend, confirmCost, costAccepted, currentRun, DEFAULT_PAUSE, followedRun, isActive, libraryOn, modelIsFree, note, PICTURE_LIMITS, removePicture, requestResume, requestSend, setDraft, setModel, setPauseEvery, setScopeKind, setUseLibrary, stop } from "../state/agent";
import { store as workspace } from "../state/workspace";
import type { Life } from "./model";

export function Composer({ life }: { life: Life }) {
  const s = useStore(agent, (x) => ({ draft: x.draft, models: x.models, model: x.model, busy: x.busy, confirm: x.confirm, scopeKind: x.scopeKind, run: currentRun(x), ok: canSend(x), paid: costAccepted(x), free: modelIsFree(x),
    noteOk: canNote(x), library: x.library, libOn: libraryOn(x), pause: x.pauseEvery, follows: !!followedRun(x), pictures: x.pictures }));
  const ws = useStore(workspace, (x) => ({ sel: x.selection.size, view: x.focusView }));
  const box = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const imagesOf = (items: DataTransferItemList | null | undefined): File[] =>
    Array.from(items ?? []).filter((it) => it.kind === "file" && it.type.startsWith("image/")).map((it) => it.getAsFile()).filter((f): f is File => !!f);
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = imagesOf(e.clipboardData?.items);
    if (files.length) {
      e.preventDefault();
      void addPictures(files);
    }
  };
  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    setOver(false);
    const files = Array.from(e.dataTransfer?.files ?? []).filter((f) => f.type.startsWith("image/"));
    if (files.length) {
      e.preventDefault();
      void addPictures(files);
    }
  };
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

  const placeholder = active ? "Say something to the agent while it works — it reads it on its next turn"
    : awaiting ? "Answer above, or say in your own words what to do…"
    : resumable ? "Add a note and continue, or give a new instruction…"
    : "Tell the agent what to do with this drawing…";

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (s.busy) return;
      if (active) {
        void note();
        return;
      }
      if (awaiting) {
        if (s.draft.trim()) requestResume();
      } else requestSend();
    } else if (e.key === "Escape" && active) void stop();
  };

  const scopeLabel = s.scopeKind !== "auto" ? s.scopeKind : s.follows ? "as the last run" : ws.sel ? `selection (${ws.sel})` : ws.view ? `view ${ws.view}` : "whole drawing";

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
      <div className={`rounded-lg border bg-white dark:bg-slate-900 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/40 dark:focus-within:border-amber-400 dark:focus-within:ring-amber-400/40 ${over ? "border-blue-500 dark:border-amber-400" : "border-slate-300 dark:border-slate-600"}`}
        onDragOver={(e) => { if (Array.from(e.dataTransfer?.items ?? []).some((it) => it.kind === "file")) { e.preventDefault(); setOver(true); } }}
        onDragLeave={() => setOver(false)} onDrop={onDrop}>
        {s.pictures.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-2 pt-2" data-testid="composer-pictures">
            {s.pictures.map((p, i) => (
              <div key={`${p.name}-${i}`} className="relative">
                <img src={p.data} alt={p.name} title={`${p.name} · ${(p.bytes / 1e6).toFixed(1)} MB`} className="h-12 w-16 rounded border border-slate-300 dark:border-slate-600 object-cover" />
                <button className="absolute -right-1.5 -top-1.5 h-4 w-4 rounded-full bg-slate-700 text-[10px] leading-4 text-white hover:bg-red-600" onClick={() => removePicture(i)}
                  aria-label={`Remove ${p.name}`} data-testid="picture-remove">×</button>
              </div>
            ))}
          </div>
        )}
        <textarea ref={box} rows={1} value={s.draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} onPaste={onPaste} placeholder={placeholder} aria-label="Message to the agent" data-testid="composer-input"
          className="block w-full resize-none bg-transparent px-3 pt-2 pb-1 text-[13px] outline-none placeholder:text-slate-400" />
        <div className="flex items-center gap-2 px-2 pb-1.5">
          <input ref={picker} type="file" accept={PICTURE_LIMITS.types.join(",")} multiple hidden data-testid="picture-input"
            onChange={(e) => { void addPictures(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <button className="rounded p-0.5 text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 disabled:opacity-40" onClick={() => picker.current?.click()}
            disabled={s.pictures.length >= PICTURE_LIMITS.count} title={`Attach pictures of the drawing's context (PNG, JPEG, WebP; up to ${PICTURE_LIMITS.count}) — or paste or drop them here`}
            aria-label="Attach pictures" data-testid="attach">
            <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <rect x="2.5" y="4" width="15" height="12" rx="2" /><circle cx="7.5" cy="8.5" r="1.5" /><path d="M3 14l4.5-4 3.5 3 2.5-2 3.5 3" />
            </svg>
          </button>
          <select className="min-w-0 max-w-[9rem] truncate rounded bg-transparent text-[11px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-200" value={s.scopeKind} onChange={(e) => setScopeKind(e.target.value as typeof s.scopeKind)} title="Where the instruction applies" data-testid="scope">
            <option value="auto">Scope: {scopeLabel}</option>
            <option value="drawing">Whole drawing</option>
            <option value="view" disabled={!ws.view}>Focused view{ws.view ? ` (${ws.view})` : ""}</option>
            <option value="selection" disabled={!ws.sel}>Selection ({ws.sel})</option>
          </select>
          <span className="flex-1" />
          {active ? (
            <>
              {s.noteOk && <button className="rounded-md bg-blue-600 px-2.5 py-1 text-[12px] font-medium text-white dark:bg-amber-500 dark:text-slate-950" onClick={() => void note()} data-testid="note" title="Say it to the agent now (Enter): it reads it on its next turn">Send note</button>}
              <button className="rounded-md bg-red-600 px-2.5 py-1 text-[12px] font-medium text-white disabled:opacity-50" onClick={() => void stop()} disabled={s.busy === "stopping" || life.key === "stopping"} data-testid="stop" title="Stop the run (Esc)">
                {s.busy === "stopping" || life.key === "stopping" ? "Stopping…" : "Stop"}
              </button>
            </>
          ) : (
            <button className="rounded-md bg-blue-600 px-2.5 py-1 text-[12px] font-medium text-white dark:bg-amber-500 dark:text-slate-950 disabled:opacity-40" onClick={() => (awaiting ? requestResume() : requestSend())} disabled={!s.ok && !(awaiting && s.draft.trim()) || s.busy !== null} data-testid="send" title="Send (Enter)">
              {resumable && s.draft.trim() ? "Continue" : "Send"}
            </button>
          )}
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 px-1 text-[11px] text-slate-400">
        <select className="min-w-0 truncate rounded bg-transparent hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-60" value={s.model} onChange={(e) => setModel(e.target.value)} disabled={active} data-testid="model" title="The model that runs the agent">
          {s.models.length === 0 && <option value="">no model</option>}
          {s.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
        {s.library && s.library.domains.length > 0 && (
          <label className="flex items-center gap-1 whitespace-nowrap" title={s.library.suggested ? `Engineering library: ${s.library.domains[0].title}. Suggested because this drawing prints: ${s.library.suggested.because.slice(0, 6).join(", ")}` : `Engineering library: ${s.library.domains[0].title}`} data-testid="library-option">
            <input type="checkbox" checked={s.libOn} onChange={(e) => setUseLibrary(e.target.checked)} disabled={active} data-testid="library" />
            Library{s.library.suggested && s.libOn ? " · suggested" : ""}
          </label>
        )}
        <select className="min-w-0 truncate rounded bg-transparent hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-60" value={s.pause} onChange={(e) => setPauseEvery(Number(e.target.value))} disabled={active} data-testid="pause" title="How often the agent pauses so you can see what it cost and say go on">
          <option value={DEFAULT_PAUSE}>Pause: {DEFAULT_PAUSE} turns</option>
          <option value={60}>Pause: 60 turns</option>
          <option value={0}>Pause: never</option>
        </select>
        <span className="whitespace-nowrap" title="Enter sends, Shift+Enter starts a new line">{s.free ? "free model" : s.paid ? "cost accepted" : "paid · billed per turn"}</span>
      </div>
    </div>
  );
}
