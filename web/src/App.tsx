// The workspace: a top bar, the views / layers / values / agent / fidelity panel on the left, the drawing in the middle, the
// inspector and the validation on the right. Both side panels resize by their edge and collapse, so the drawing can take the
// whole window when a sheet needs it.
import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { AutosaveInfo } from "./api/types";
import { CanvasView } from "./canvas/CanvasView";
import { AgentPanel } from "./agent/AgentPanel";
import { lifecycle } from "./agent/model";
import { Spinner } from "./agent/StatusMark";
import { FidelityPanel } from "./panels/FidelityPanel";
import { InspectorPanel } from "./panels/InspectorPanel";
import { LayersPanel } from "./panels/LayersPanel";
import { ValidationPanel } from "./panels/ValidationPanel";
import { ValuesPanel } from "./panels/ValuesPanel";
import { ViewsPanel } from "./panels/ViewsPanel";
import { agent, currentRun } from "./state/agent";
import { useStore } from "./state/store";
import { back, fitSheet, loadAll, openFile, redo, setOverlay, store, toggleAgent, undo, type LeftTab, type RightTab } from "./state/workspace";

const LEFT: [LeftTab, string][] = [["views", "Views"], ["layers", "Layers"], ["values", "Values"], ["fidelity", "Fidelity"]];
const RIGHT: [RightTab, string][] = [["inspect", "Inspector"], ["validate", "Validation"]];

function Tabs<T extends string>({ items, value, onChange }: { items: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex border-b border-slate-200 dark:border-slate-700 text-[13px]">
      {items.map(([k, label]) => (
        <button key={k} data-testid={`tab-${k}`} onClick={() => onChange(k)}
          className={`px-3 py-2 -mb-px border-b-2 ${value === k ? "border-blue-600 text-blue-700 dark:text-blue-300 font-medium" : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Splitter({ side }: { side: "left" | "right" | "agent" }) {
  const start = useRef<{ x: number; w: number } | null>(null);
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      className="w-1.5 shrink-0 cursor-col-resize bg-slate-200/60 hover:bg-blue-400/60 dark:bg-slate-700/60"
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        const s = store.get();
        start.current = { x: e.clientX, w: side === "left" ? s.leftWidth : side === "agent" ? s.agentWidth : s.rightWidth };
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const d = e.clientX - start.current.x;
        const w = Math.max(side === "agent" ? 340 : 220, Math.min(side === "agent" ? 900 : 720, start.current.w + (side === "left" ? d : -d)));
        store.set(side === "left" ? { leftWidth: w } : side === "agent" ? { agentWidth: w } : { rightWidth: w });
      }}
      onPointerUp={() => (start.current = null)}
    />
  );
}

function AgentButton({ btn }: { btn: string }) {
  const open = useStore(store, (x) => x.agentOpen);
  const a = useStore(agent, (x) => ({ runs: x.runs, currentId: x.currentId, busy: x.busy }));
  const life = lifecycle(currentRun({ ...agent.get(), runs: a.runs, currentId: a.currentId }), a.busy === "starting");
  return (
    <button className={`${btn} flex items-center gap-1.5 ${open ? "bg-slate-100 dark:bg-slate-800" : ""}`} onClick={toggleAgent} aria-pressed={open} data-testid="agent-toggle" title={`Agent — ${life.label}`}>
      {life.active ? <Spinner /> : life.key === "awaiting" ? <span className="h-2 w-2 rounded-full bg-amber-500" /> : null}
      Agent
    </button>
  );
}

/** Where the work is kept: the page never owns it, the engine writes it to disk as it changes, so closing the server loses nothing. The badge asks
 * the engine every few seconds; a server that does not answer is a server that cannot save, and it says so. */
function AutosaveBadge({ initial }: { initial: AutosaveInfo }) {
  const [a, setA] = useState(initial);
  useEffect(() => setA(initial), [initial]);
  useEffect(() => {
    const t = window.setInterval(() => {
      api.autosave().then((x) => x && setA(x)).catch(() => setA((cur) => ({ ...cur, error: "the server did not answer" })));
    }, 4000);
    return () => window.clearInterval(t);
  }, []);
  const time = (sec: number) => new Date(sec * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const text = a.error ? "not saved" : a.saved_at ? `saved ${time(a.saved_at)}` : a.restored?.from ? "opened from saved work" : "autosave on";
  const tip = [a.path ? `kept in ${a.path}` : "kept on disk as it changes", a.restored?.from ? `opened from ${a.restored.from}, revision ${a.restored.revision ?? "?"}` : "", a.error ? `FAILED: ${a.error}` : ""].filter(Boolean).join(" · ");
  return <span className={`text-[12px] ${a.error ? "text-red-600" : "text-slate-400"}`} data-testid="autosave" title={tip}>· {text}</span>;
}

function TopBar() {
  const s = useStore(store, (x) => ({ summary: x.summary, busy: x.busy, message: x.message, theme: x.theme, revision: x.revision, leftOpen: x.leftOpen, rightOpen: x.rightOpen, original: x.overlays.original }));
  const file = useRef<HTMLInputElement>(null);
  const btn = "px-2.5 py-1 rounded border border-slate-300 dark:border-slate-600 text-[13px] hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40";
  return (
    <header className="flex items-center gap-2 px-3 h-11 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-[#11161d] shrink-0">
      <button className={btn} title="Show or hide the left panel" onClick={() => store.set({ leftOpen: !s.leftOpen })}>☰</button>
      <strong className="text-[14px] text-slate-800 dark:text-slate-100">Sheet Workspace</strong>
      <span className="text-[13px] text-slate-500 truncate max-w-[22ch]" title={s.summary?.path}>{s.summary?.file ?? "no drawing"}</span>
      <input ref={file} type="file" accept=".dxf" className="hidden" data-testid="file-input" onChange={(e) => e.target.files?.[0] && void openFile(e.target.files[0])} />
      <button className={btn} onClick={() => file.current?.click()}>Open DXF</button>
      <button className={btn} disabled={!s.summary?.can_undo} onClick={() => void undo()} title="Undo the last committed change">Undo</button>
      <button className={btn} disabled={!s.summary?.can_redo} onClick={() => void redo()}>Redo</button>
      <button className={btn} onClick={() => fitSheet()} title="Fit the sheet (F)">Fit</button>
      <button className={btn} onClick={() => back()} title="Back to the previous view (Backspace)">Back</button>
      <button className={`${btn} ${s.original ? "bg-slate-100 dark:bg-slate-800" : ""}`} aria-pressed={s.original} data-testid="show-original" disabled={!s.summary}
        title="Show the drawing as it was read, dotted, under what has changed (switch off to hide it)" onClick={() => setOverlay("original", !s.original)}>Original</button>
      {s.summary && <a className={btn} href="/api/sheet/export" data-testid="export">Export DXF</a>}
      <span className="ml-2 text-[12px] text-slate-400 num" data-testid="revision">rev {s.revision}</span>
      {s.summary?.autosave && <AutosaveBadge initial={s.summary.autosave} />}
      <div className="flex-1 min-w-0 px-2">
        {s.busy ? <span className="block truncate text-[13px] text-slate-500">{s.busy}</span>
          : s.message && <span data-testid="message" title={s.message.text} className={`block text-[13px] truncate ${s.message.kind === "bad" ? "text-red-600" : s.message.kind === "ok" ? "text-emerald-600" : "text-slate-600"}`}>{s.message.text}</span>}
      </div>
      <button className={btn} onClick={() => store.set({ theme: s.theme === "dark" ? "light" : "dark" })}>{s.theme === "dark" ? "Light" : "Dark"}</button>
      <AgentButton btn={btn} />
      <a className={btn} href="/legacy" title="The previous page">Legacy</a>
      <button className={btn} title="Show or hide the right panel" onClick={() => store.set({ rightOpen: !s.rightOpen })}>☷</button>
    </header>
  );
}

export function App() {
  const s = useStore(store, (x) => ({ theme: x.theme, leftTab: x.leftTab, rightTab: x.rightTab, leftWidth: x.leftWidth, rightWidth: x.rightWidth, leftOpen: x.leftOpen, rightOpen: x.rightOpen, agentOpen: x.agentOpen, agentWidth: x.agentWidth, has: !!x.summary }));
  useEffect(() => {
    void loadAll(true);
  }, []);
  return (
    <div className={`${s.theme === "dark" ? "dark" : ""} h-full`}>
      <div className="flex flex-col h-full bg-[#f6f7f9] dark:bg-[#0b0f14] text-slate-800 dark:text-slate-200">
        <TopBar />
        <div className="flex flex-1 min-h-0">
          {s.leftOpen && (
            <>
              <aside className="flex flex-col shrink-0 bg-white dark:bg-[#11161d] border-r border-slate-200 dark:border-slate-700" style={{ width: s.leftWidth }}>
                <Tabs items={LEFT} value={s.leftTab} onChange={(t) => store.set({ leftTab: t })} />
                <div className="flex-1 min-h-0 overflow-auto">
                  {s.leftTab === "views" && <ViewsPanel />}
                  {s.leftTab === "layers" && <LayersPanel />}
                  {s.leftTab === "values" && <ValuesPanel />}
                  {s.leftTab === "fidelity" && <FidelityPanel />}
                </div>
              </aside>
              <Splitter side="left" />
            </>
          )}
          <main className="flex-1 min-w-0 relative">
            {!s.has && (
              <div className="absolute inset-0 grid place-items-center text-slate-500 text-sm pointer-events-none">Open a DXF to begin.</div>
            )}
            <CanvasView />
          </main>
          {s.agentOpen && (
            <>
              <Splitter side="agent" />
              <aside className="flex flex-col shrink-0 bg-white dark:bg-[#11161d] border-l border-slate-200 dark:border-slate-700" style={{ width: s.agentWidth }} aria-label="Agent" data-testid="agent-dock">
                <AgentPanel />
              </aside>
            </>
          )}
          {s.rightOpen && (
            <>
              <Splitter side="right" />
              <aside className="flex flex-col shrink-0 bg-white dark:bg-[#11161d] border-l border-slate-200 dark:border-slate-700" style={{ width: s.rightWidth }}>
                <Tabs items={RIGHT} value={s.rightTab} onChange={(t) => store.set({ rightTab: t })} />
                <div className="flex-1 min-h-0 overflow-auto">
                  {s.rightTab === "inspect" ? <InspectorPanel /> : <ValidationPanel />}
                </div>
              </aside>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
