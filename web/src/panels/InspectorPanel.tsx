// What the engine knows about the picked entity: where it came from in the file (handle, block path), its resolved CAD style,
// its geometry, how each point is set out (datum line + offset, the line's formula, the values that reach it), the annotations
// that refer to it and its existing / proposed class. Read-only: values are changed in the Values panel.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Annotation, EntityRecord, PointAxis } from "../api/types";
import { useStore } from "../state/store";
import { fitEntities, focusParam, select, store } from "../state/workspace";

// the sheet's annotations, fetched once per revision and shared by every inspection
let annCache: { revision: number; list: Annotation[] } | null = null;

async function annotationsAt(revision: number): Promise<Annotation[]> {
  if (annCache?.revision === revision) return annCache.list;
  const r = await api.annotations();
  annCache = { revision, list: r.annotations };
  return r.annotations;
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <tr className="align-top">
      <td className="pr-2 py-0.5 text-slate-400 whitespace-nowrap">{k}</td>
      <td className="py-0.5 break-words">{children}</td>
    </tr>
  );
}

function Axis({ a }: { a: PointAxis | null }) {
  if (!a) return <span className="text-slate-400">—</span>;
  return (
    <span title={a.formula ? `${a.line} = ${a.formula}` : a.line}>
      <span className="font-mono">{a.line}</span>
      {a.offset_mm ? <span className="num text-slate-500"> {a.offset_mm > 0 ? "+" : ""}{a.offset_mm.toFixed(1)}</span> : null}
      {a.origin !== "geometry" && <span className="ml-1 text-[10px] text-amber-700 dark:text-amber-300">{a.origin}</span>}
    </span>
  );
}

function Parametric({ rec }: { rec: EntityRecord }) {
  const p = rec.parametric;
  if (!p) return <p className="text-slate-500">{rec.unit ? "Not set out by the unit's model." : "Not in a parametrized view: it stays as drawn."}</p>;
  return (
    <div>
      <p className="mb-1">
        {p.fixed ? <span className="text-slate-500">No value reaches it: it stays where it is.</span>
          : <>Moved by {p.parameters.map((n) => (
            <button key={n} className="mr-1 rounded bg-blue-50 dark:bg-blue-950/50 px-1 font-mono text-blue-700 dark:text-blue-300" onClick={() => { store.set({ leftTab: "values" }); void focusParam(`${rec.unit}.${n}`); }}>{n}</button>
          ))}</>}
        {p.held && <span className="ml-1 rounded bg-amber-100 dark:bg-amber-900/50 px-1 text-[11px]">held (existing)</span>}
      </p>
      <table className="w-full text-[11px]">
        <thead><tr className="text-slate-400"><th className="text-left font-normal">#</th><th className="text-left font-normal">x</th><th className="text-left font-normal">y</th></tr></thead>
        <tbody>
          {p.points.slice(0, 12).map((pt, j) => (
            <tr key={j}><td className="pr-1 text-slate-400 num">{j}</td><td className="pr-2"><Axis a={pt.x} /></td><td><Axis a={pt.y} /></td></tr>
          ))}
        </tbody>
      </table>
      {p.points.length > 12 && <p className="text-[11px] text-slate-400">+{p.points.length - 12} more points</p>}
    </div>
  );
}

export function InspectorPanel() {
  const { rec, selection, revision, statusOf } = useStore(store, (s) => ({ rec: s.entity, selection: s.selection, revision: s.revision, statusOf: s.statusOf }));
  const [anns, setAnns] = useState<Annotation[]>([]);
  useEffect(() => {
    if (!rec) return setAnns([]);
    let live = true;
    annotationsAt(revision).then((list) => live && setAnns(list.filter((a) => a.items.includes(rec.index) || a.targets?.some((t) => t.index === rec.index)))).catch(() => setAnns([]));
    return () => { live = false; };
  }, [rec, revision]);
  if (!rec) return <p className="p-3 text-[13px] text-slate-500" data-testid="inspector-empty">Click an entity on the drawing to inspect it. Shift-click adds to the selection.</p>;
  const st = rec.style;
  const src = rec.source as { handle?: string; inserts?: string[]; owner?: string; dimstyle?: string; color?: number; linetype?: string; lineweight?: number };
  const status = statusOf?.[String(rec.index)];
  return (
    <div className="p-2 text-[12px]" data-testid="inspector">
      <div className="flex items-center gap-2 mb-2">
        <strong className="text-[13px]">{rec.type}</strong>
        <span className="font-mono text-slate-500">{rec.id}</span>
        {selection.size > 1 && <span className="text-slate-400">({selection.size} selected)</span>}
        <button className="ml-auto underline text-blue-700 dark:text-blue-300" onClick={() => fitEntities(new Set([rec.index]))} data-testid="zoom-entity">Zoom to it</button>
        <button className="underline text-slate-500" onClick={() => void select(null)}>Clear</button>
      </div>
      <table className="w-full mb-2"><tbody>
        <Row k="layer">{rec.layer}</Row>
        <Row k="role">{rec.role}{status && <span className="ml-2 rounded bg-slate-100 dark:bg-slate-800 px-1">{status}</span>}</Row>
        <Row k="view">{rec.view.id ? `${rec.view.id} · ${rec.view.name || rec.view.kind}` : "outside every view"}</Row>
        <Row k="unit">{rec.unit ?? "—"}</Row>
        <Row k="handle"><span className="font-mono">{src.handle ?? "—"}</span>{src.owner && <span className="text-slate-500"> in {src.owner}</span>}{src.inserts && src.inserts.length > 0 && <span className="text-slate-500"> via {src.inserts.join(" › ")}</span>}</Row>
        {src.linetype !== undefined && <Row k="as filed">colour {src.color === 256 ? "BYLAYER" : src.color === 0 ? "BYBLOCK" : src.color} · {src.linetype} · weight {src.lineweight === -1 ? "BYLAYER" : src.lineweight === -2 ? "BYBLOCK" : src.lineweight === -3 ? "default" : `${(src.lineweight ?? 0) / 100} mm`}</Row>}
        {src.dimstyle && <Row k="dim style">{src.dimstyle}</Row>}
        {st && (
          <Row k="style">
            <span className="inline-block w-3 h-3 rounded-sm border border-slate-300 align-middle mr-1" style={{ background: st.fg ? "currentColor" : st.color }} />
            {st.fg ? "foreground (ACI 7)" : st.color} · {st.lw ? `${st.lw} mm` : "default weight"} · {st.lt}{st.dash.length ? ` [${st.dash.map((d) => +d.toFixed(2)).join(", ")}]` : ""}
            {st.alpha < 1 && ` · ${Math.round((1 - st.alpha) * 100)}% transparent`}{st.font && ` · ${st.font}`}
          </Row>
        )}
        {rec.text !== undefined && <Row k="text"><span className="whitespace-pre-wrap">{rec.text}</span>{rec.text_height_mm ? <span className="text-slate-400"> · h {rec.text_height_mm} mm</span> : null}</Row>}
        {rec.dimension && <Row k="dimension">{rec.dimension.measurement_mm.toFixed(1)} mm{rec.dimension.override && rec.dimension.override !== "<>" ? ` · reads "${rec.dimension.override}"` : ""}</Row>}
        {rec.drawn_with && <Row k="drawn with">{Object.entries(rec.drawn_with).map(([k, v]) => `${v} ${k}`).join(", ")}</Row>}
        {rec.hatch && <Row k="hatch">{rec.hatch.fill} {rec.hatch.pattern} · {rec.hatch.pattern_lines} lines{rec.hatch.too_dense ? " (too dense: drawn as a tint)" : ""}</Row>}
        {rec.parts && rec.parts.length > 0 && <Row k="parts">{rec.parts.join(", ")}</Row>}
        <Row k="points">{rec.geometry.points_total ?? rec.geometry.points_mm.length}{rec.geometry.closed ? " · closed" : ""}{rec.geometry.radius_mm ? ` · r ${rec.geometry.radius_mm} mm` : ""}</Row>
      </tbody></table>
      <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">How it is set out</h3>
      <Parametric rec={rec} />
      {anns.length > 0 && (
        <>
          <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-wide text-slate-400">Annotations about it</h3>
          <ul data-testid="entity-annotations">
            {anns.slice(0, 10).map((a) => (
              <li key={a.id} className="mb-1">
                <button className="text-left hover:underline" onClick={() => fitEntities(new Set(a.items))}>
                  <span className="rounded bg-slate-100 dark:bg-slate-800 px-1 mr-1">{a.kind.replace("_", " ")}</span>"{a.text.slice(0, 60)}"
                </button>
                <span className={`ml-1 ${a.status === "resolved" ? "text-emerald-600" : "text-amber-600"}`}>{a.status}</span>
                <span className="text-slate-400"> · follows the {a.attachment}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
