// What the file held and what of it this workspace reads, draws, can edit and exports — per entity type, with every visible
// entity that is not read named by handle. Plus the properties the drawing uses (linetypes, hatch patterns, colours,
// lineweights, fonts, dimension styles) and how each is reproduced. Nothing is silently dropped: if it is not here, it was hidden.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Coverage } from "../api/types";
import { useStore } from "../state/store";
import { store } from "../state/workspace";

function Pairs({ title, data, fmt }: { title: string; data?: Record<string, number>; fmt?: (k: string) => React.ReactNode }) {
  if (!data || !Object.keys(data).length) return null;
  return (
    <section className="mt-3">
      <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">{title}</h3>
      <div className="flex flex-wrap gap-1">
        {Object.entries(data).map(([k, v]) => (
          <span key={k} className="rounded border border-slate-200 dark:border-slate-700 px-1.5 text-[11px]">{fmt ? fmt(k) : k} <span className="num text-slate-400">{v}</span></span>
        ))}
      </div>
    </section>
  );
}

export function FidelityPanel() {
  const { revision, file } = useStore(store, (s) => ({ revision: s.revision, file: s.summary?.file }));
  const [cov, setCov] = useState<Coverage | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return;
    api.coverage().then((c) => { setCov(c); setErr(null); }).catch((e: Error) => setErr(e.message));
  }, [file, revision]);
  if (!file) return <p className="p-3 text-sm text-slate-500">No drawing open.</p>;
  if (err) return <p className="p-3 text-sm text-red-600">{err}</p>;
  if (!cov) return <p className="p-3 text-sm text-slate-500">Reading the coverage…</p>;
  const e = cov.entities;
  return (
    <div className="p-2 text-[12px]" data-testid="fidelity-panel">
      <p className={`mb-2 rounded px-2 py-1 text-[13px] ${cov.faithful ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200" : "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-200"}`} data-testid="faithful">
        {cov.faithful ? "Faithful: every visible entity is read and drawn." : "Not faithful — see below."}
        <span className="block text-[11px] opacity-80">{e.visible_in_file} visible in the file · {e.read} read · {e.hidden} hidden (layer off / frozen) · {e.not_read} not read · {e.inserts_expanded} block inserts expanded</span>
      </p>
      {cov.problems.length > 0 && <ul className="mb-2 list-disc pl-4 text-red-700 dark:text-red-300">{cov.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <table className="w-full text-[11px]" data-testid="coverage-table">
        <thead>
          <tr className="text-slate-400 text-left"><th className="font-normal">type</th><th className="font-normal text-right">file</th><th className="font-normal text-right">read</th><th className="font-normal text-right">drawn</th><th className="font-normal text-right">edit</th><th className="font-normal pl-2">export</th></tr>
        </thead>
        <tbody>
          {cov.types.map((r) => (
            <tr key={r.type} className={r.not_read ? "text-red-700 dark:text-red-300" : ""} title={r.not_read_handles?.length ? `not read: ${r.not_read_handles.join(", ")}` : undefined}>
              <td>{r.type}</td>
              <td className="text-right num">{r.in_file}</td>
              <td className="text-right num">{r.read}</td>
              <td className="text-right num">{r.drawn}</td>
              <td className="text-right num">{r.editable}</td>
              <td className="pl-2 text-slate-500">{r.export}{r.hidden ? ` · ${r.hidden} hidden` : ""}{r.not_read ? ` · ${r.not_read} not read` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="mt-3">
        <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Linetypes</h3>
        {Object.entries(cov.linetypes).map(([k, v]) => (
          <div key={k} className="flex gap-2"><span className="flex-1 truncate">{k}</span><span className="text-slate-500">{v.drawn_as}{v.dash.length ? ` [${v.dash.map((d) => +d.toFixed(2)).join(", ")}]` : ""}</span><span className="num text-slate-400 w-10 text-right">{v.entities}</span></div>
        ))}
      </section>
      {Object.keys(cov.hatch_patterns).length > 0 && (
        <section className="mt-3">
          <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Hatch patterns</h3>
          {Object.entries(cov.hatch_patterns).map(([k, v]) => (
            <div key={k} className="flex gap-2"><span className="flex-1 truncate">{k}</span><span className="text-slate-500">{v.drawn_as.join(", ")}</span><span className="num text-slate-400 w-10 text-right">{v.count}</span></div>
          ))}
        </section>
      )}
      <Pairs title="Dimension / leader parts drawn" data={cov.compound_parts} />
      <Pairs title="Colours" data={cov.colors} fmt={(k) => <><span className="inline-block w-2.5 h-2.5 rounded-sm align-middle mr-0.5 border border-slate-300" style={{ background: k.startsWith("#") ? k : "currentColor" }} />{k}</>} />
      <Pairs title="Lineweights (mm)" data={cov.lineweights} fmt={(k) => (k === "null" || k === "None" ? "default" : k)} />
      <Pairs title="Fonts" data={cov.fonts} />
      <Pairs title="Dimension styles" data={cov.dimension_styles} />
      {cov.header && <p className="mt-3 text-[11px] text-slate-500">{Object.entries(cov.header).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>}
      {cov.layouts && cov.layouts.length > 1 && (
        <p className="mt-1 text-[11px] text-slate-500">Layouts: {cov.layouts.map((l) => `${l.name}${l.read ? " (read)" : ""} ${l.entities}${l.viewports.length ? `, ${l.viewports.length} viewports` : ""}`).join(" · ")}</p>
      )}
    </div>
  );
}
