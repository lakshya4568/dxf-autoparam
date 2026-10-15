// The values of a unit (and the values shared across views): pick one to see what it drives, type a value to preview the
// regenerated sheet (nothing is applied), check the whole assembly, apply. The camera never moves: you keep looking where you were.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ParamRow } from "../api/types";
import { useStore } from "../state/store";
import { applyChange, cancelPreview, checkBehaviour, clearParam, fitEntities, focusParam, openUnit, previewChange, store } from "../state/workspace";

function fmt(v: number, unit: string): string {
  return unit === "m" ? v.toFixed(3) : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
}

function ParamEditor({ row }: { row: { key: string; label: string; value: number; drawn: number; unit: string } }) {
  const { param, preview } = useStore(store, (s) => ({ param: s.param, preview: s.preview }));
  const [text, setText] = useState(fmt(row.value, row.unit));
  const timer = useRef<number | null>(null);
  const [impact, setImpact] = useState<Record<string, unknown> | null>(null);
  useEffect(() => setText(fmt(row.value, row.unit)), [row.value, row.unit]);
  const range = param?.key === row.key ? param.info?.range : undefined;
  const value = Number(text);
  const changed = isFinite(value) && Math.abs(value - row.value) > 1e-9;
  const schedule = (v: number) => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void previewChange({ [row.key]: v }), 350);
  };
  return (
    <div className="mt-2 rounded border border-blue-200 dark:border-blue-900 bg-blue-50/60 dark:bg-blue-950/30 p-2" data-testid="param-editor">
      <div className="flex items-center gap-2">
        <input className="w-28 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1.5 py-0.5 num text-right" value={text} data-testid="param-input"
          onChange={(e) => { setText(e.target.value); const v = Number(e.target.value); if (isFinite(v) && e.target.value.trim()) schedule(v); }} />
        <span className="text-slate-500">{row.unit}</span>
        <button className="ml-auto rounded bg-blue-600 px-2 py-0.5 text-white disabled:opacity-40" disabled={!changed || (preview !== null && !preview.ok)} data-testid="apply"
          onClick={() => void applyChange({ [row.key]: value })}>Apply</button>
        <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5" onClick={() => { setText(fmt(row.value, row.unit)); cancelPreview(); }}>Cancel</button>
      </div>
      {range && range.min !== undefined && range.max !== undefined && (
        <div className="mt-1">
          <input type="range" className="w-full" min={range.min} max={range.max} step={(range.max - range.min) / 400} value={isFinite(value) ? value : row.value}
            onChange={(e) => { setText(e.target.value); schedule(Number(e.target.value)); }} />
          <div className="flex justify-between text-[11px] text-slate-500 num"><span title={range.min_reason}>{fmt(range.min, row.unit)}</span><span>drawn {fmt(row.drawn, row.unit)}</span><span title={range.max_reason}>{fmt(range.max, row.unit)}</span></div>
        </div>
      )}
      {preview && (
        <p className={`mt-1 text-[12px] ${preview.ok ? "text-slate-600 dark:text-slate-300" : "text-red-600"}`} data-testid="preview-status">
          {preview.ok ? `Preview: ${preview.ents.size} entities change (orange); nothing is applied yet.` : `Would break: ${preview.errors[0] ?? ""}`}
        </p>
      )}
      <div className="mt-1 flex gap-2 text-[12px]">
        <button className="underline text-blue-700 dark:text-blue-300" onClick={() => void checkBehaviour({ [row.key]: isFinite(value) && changed ? value : row.value * 1.05 })}>Check the assembly</button>
        <button className="underline text-blue-700 dark:text-blue-300" onClick={() => void api.impact(row.key).then(setImpact)}>What would it change?</button>
        {param?.key === row.key && param.info && (
          <button className="underline text-blue-700 dark:text-blue-300" onClick={() => fitEntities(new Set([...param.info!.highlight.drives, ...param.info!.highlight.follows]))}>Zoom to it</button>
        )}
      </div>
      {impact && <ImpactSummary data={impact} />}
    </div>
  );
}

function ImpactSummary({ data }: { data: Record<string, unknown> }) {
  const comps = (data.components ?? {}) as Record<string, string[]>;
  const ann = (data.annotations ?? {}) as { updating?: { text: string; reads: string }[]; problems?: unknown[] };
  const q = (data.questions ?? []) as string[];
  return (
    <div className="mt-2 text-[12px] text-slate-700 dark:text-slate-300" data-testid="impact">
      {Object.entries(comps).map(([k, v]) => <div key={k}><b>{k}</b>: {v.slice(0, 8).join(", ")}{v.length > 8 ? ` +${v.length - 8}` : ""}</div>)}
      {ann.updating && ann.updating.length > 0 && <div>dimensions that update: {ann.updating.slice(0, 6).map((a) => a.reads).join("; ")}</div>}
      {Array.isArray(data.invariants_kept) && <div className="text-slate-500">kept: {(data.invariants_kept as string[]).slice(0, 10).join(", ")}</div>}
      {q.map((x) => <div key={x} className="text-amber-700 dark:text-amber-300">? {x}</div>)}
    </div>
  );
}

export function ValuesPanel() {
  const { summary, unit, param, focus } = useStore(store, (s) => ({ summary: s.summary, unit: s.unit, param: s.param, focus: s.focusView }));
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (!summary || unit) return;
    const g = focus ? summary.groups.find((x) => x.id === focus) : undefined;
    const uid = g?.unit ?? summary.units.find((u) => u.parametrized)?.id ?? summary.units[0]?.id;
    if (uid) void openUnit(uid);
  }, [summary, unit, focus]);
  const rows = useMemo(() => (unit?.params ?? []).filter((p) => !filter || `${p.name} ${p.label}`.toLowerCase().includes(filter.toLowerCase())), [unit, filter]);
  if (!summary) return <p className="p-3 text-sm text-slate-500">No drawing open.</p>;
  const pick = (key: string) => { if (param?.key === key) clearParam(); else void focusParam(key); };
  return (
    <div className="p-2 text-[13px]" data-testid="values-panel">
      <div className="flex items-center gap-2 mb-2">
        <select className="rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1 py-0.5" value={unit?.id ?? ""} onChange={(e) => void openUnit(e.target.value)} data-testid="unit-select">
          {summary.units.map((u) => <option key={u.id} value={u.id}>{u.id} · {u.views.join(" + ")}{u.parametrized ? " ✓" : ""}</option>)}
        </select>
        <input className="flex-1 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1.5 py-0.5" placeholder="filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {summary.shared.length > 0 && (
        <section className="mb-3">
          <h3 className="px-1 mb-1 text-[11px] uppercase tracking-wide text-slate-400">Shared across views</h3>
          {summary.shared.map((p) => (
            <div key={p.id}>
              <button className={`w-full flex justify-between rounded px-1.5 py-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${param?.key === p.name ? "bg-blue-50 dark:bg-blue-950/40" : ""}`} onClick={() => pick(p.name)}>
                <span className="font-medium">{p.name}</span><span className="num text-slate-500">{fmt(summary.values[p.name] ?? p.value, p.unit)} {p.unit}</span>
              </button>
              {param?.key === p.name && <ParamEditor row={{ key: p.name, label: p.label, value: summary.values[p.name] ?? p.value, drawn: p.value, unit: p.unit }} />}
            </div>
          ))}
        </section>
      )}
      <h3 className="px-1 mb-1 text-[11px] uppercase tracking-wide text-slate-400">{unit ? `${unit.id} — ${unit.params.length} values` : "values"}</h3>
      {rows.map((p: ParamRow) => (
        <div key={p.key}>
          <button data-testid={`param-${p.name}`} className={`w-full flex items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800 ${param?.key === p.key ? "bg-blue-50 dark:bg-blue-950/40" : ""}`} onClick={() => pick(p.key)}>
            <span className="min-w-0 flex-1">
              <span className={`block truncate ${/^(Gap|Thk|Off|Step|Leg|Pitch)[XYR]?\d+$/.test(p.name) ? "text-slate-500" : "font-medium"}`}>{p.name}{p.shared && <span className="ml-1 text-[10px] text-blue-600">shared</span>}</span>
              {p.label && p.label !== p.name && <span className="block truncate text-[11px] text-slate-400">{p.label}</span>}
            </span>
            <span className={`num ${p.changed ? "text-orange-600" : "text-slate-600 dark:text-slate-300"}`}>{fmt(p.value, p.unit)}</span>
            <span className="text-[11px] text-slate-400 w-6">{p.unit}</span>
          </button>
          {param?.key === p.key && <ParamEditor row={p} />}
        </div>
      ))}
    </div>
  );
}
