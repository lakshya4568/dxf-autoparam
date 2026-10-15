// What the engine says about the sheet as it stands and about a change before it is applied: the preview's errors and
// warnings, the assembly check category by category (requested sizes, components, invariants, interfaces, held geometry,
// annotations, views, validity) and the unit's findings. A row that names entities zooms to them.
import { useState } from "react";
import type { CheckRow } from "../api/types";
import { useStore } from "../state/store";
import { fitEntities, rowEntities, store } from "../state/workspace";

const CATS: [string, string][] = [
  ["requested", "The value asked for"], ["components", "Components"], ["invariants", "Sizes nobody changed"], ["interfaces", "Parts that touch"],
  ["held", "Held / existing geometry"], ["annotations", "Annotations"], ["views", "Other views"], ["validity", "Valid outlines"],
];

const BADGE: Record<string, string> = {
  pass: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
  fail: "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200",
  "not checked": "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};

/** One line of a check, in words: what it is about, then what was found. */
export function describe(r: CheckRow): string {
  const g = (k: string) => r[k] as string | number | undefined;
  if (g("component")) return `${g("component")}: ${g("kind")}${r.thickness_kept === false ? " (thickness changed)" : ""}`;
  if (g("annotation")) return `${String(g("kind") ?? "").replace("_", " ")} "${g("text")}"${g("reads") ? ` now reads ${g("reads")}` : ""}${g("why") ? ` — ${g("why")}` : ""}`;
  if (g("expected_mm") !== undefined && g("value")) return `${g("value")}: ${g("measured_mm")} mm measured, ${g("expected_mm")} asked`;
  if (g("kept_mm") !== undefined) return `${g("value")} keeps ${g("kept_mm")} mm`;
  if (g("from_mm") !== undefined) return `${g("value")}: ${g("from_mm")} → ${g("to_mm")} mm${g("why") ? ` — ${g("why")}` : ""}`;
  if (Array.isArray(r.parts)) return `${(r.parts as string[]).join(" ↔ ")}: ${g("gap_mm") ?? "?"} mm apart`;
  if (g("held_lines") !== undefined) return `${g("held_lines")} held lines${Array.isArray(r.moved) && r.moved.length ? `, moved: ${(r.moved as string[]).join(", ")}` : ", none moved"}`;
  if (g("shared")) return `${g("shared")} in ${g("unit")}: ${g("measured_mm")} mm`;
  return String(g("issue") ?? g("why") ?? JSON.stringify(r));
}

function Category({ name, label, cat }: { name: string; label: string; cat: { status: string; items: CheckRow[]; basis?: string } }) {
  const fails = cat.items.filter((r) => r.status === "fail");
  const [open, setOpen] = useState(fails.length > 0);
  return (
    <section className="mb-1.5" data-testid={`cat-${name}`}>
      <button className="w-full flex items-center gap-2 text-left" onClick={() => setOpen(!open)}>
        <span className={`rounded px-1.5 text-[11px] ${BADGE[cat.status] ?? BADGE["not checked"]}`}>{cat.status}</span>
        <span className="flex-1">{label}</span>
        <span className="text-[11px] text-slate-400 num">{fails.length ? `${fails.length} of ${cat.items.length}` : cat.items.length}</span>
      </button>
      {open && (
        <ul className="mt-1 ml-1 border-l border-slate-200 dark:border-slate-700 pl-2">
          {cat.basis && <li className="text-[11px] text-slate-400">components from {cat.basis}</li>}
          {[...fails, ...cat.items.filter((r) => r.status !== "fail")].slice(0, 60).map((r, j) => {
            const ents = rowEntities(r);
            return (
              <li key={j} className={`text-[12px] ${r.status === "fail" ? "text-red-700 dark:text-red-300" : r.status === "pass" ? "" : "text-slate-500"}`}>
                {ents.length ? <button className="text-left hover:underline" onClick={() => fitEntities(new Set(ents))}>{describe(r)}</button> : describe(r)}
                {typeof r.unit === "string" && <span className="ml-1 text-[10px] text-slate-400">{r.unit}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function ValidationPanel() {
  const { preview, behaviour, unit } = useStore(store, (s) => ({ preview: s.preview, behaviour: s.behaviour, unit: s.unit }));
  return (
    <div className="p-2 text-[13px]" data-testid="validation-panel">
      {preview && (
        <section className="mb-3">
          <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Preview (not applied)</h3>
          <p>{Object.entries(preview.changes).map(([k, v]) => `${k} = ${v}`).join(", ")} → {preview.ents.size} entities change.</p>
          {preview.errors.map((e) => <p key={e} className="text-red-600">✗ {e}</p>)}
          {preview.warnings.slice(0, 8).map((w) => <p key={w} className="text-amber-700 dark:text-amber-300">! {w}</p>)}
          {preview.ok && !preview.errors.length && <p className="text-emerald-700 dark:text-emerald-300">Every check of the sheet holds.</p>}
        </section>
      )}
      {behaviour ? (
        <section className="mb-3" data-testid="behaviour">
          <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">Assembly check</h3>
          <p className={`mb-1 ${behaviour.ok ? "text-emerald-700 dark:text-emerald-300" : "text-red-600"}`}>
            {Object.entries(behaviour.changes).map(([k, v]) => `${k} = ${v}`).join(", ")}: {behaviour.changed_entities} entities change —{" "}
            {behaviour.ok ? "nothing fails." : `fails in ${behaviour.failed.join(", ")}.`}
          </p>
          <p className="mb-2 text-[11px] text-slate-500">Geometry that regenerates is not proof of engineering adequacy; the checks say what holds geometrically.</p>
          {CATS.map(([k, label]) => behaviour.categories[k] && <Category key={k} name={k} label={label} cat={behaviour.categories[k]} />)}
          <button className="mt-1 text-[12px] underline text-slate-500" onClick={() => store.set({ behaviour: null, issues: new Set() })}>Clear</button>
        </section>
      ) : (
        !preview && <p className="mb-3 text-slate-500">Pick a value in the Values panel, type a new value to preview it, then "Check the assembly" to see what holds.</p>
      )}
      {unit && unit.findings.length > 0 && (
        <section>
          <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">{unit.id} findings</h3>
          <ul>
            {unit.findings.slice(0, 40).map((f, j) => (
              <li key={j} className={`text-[12px] ${f.severity === "error" ? "text-red-600" : f.severity === "warning" ? "text-amber-700 dark:text-amber-300" : "text-slate-500"}`}>
                <span className="font-mono text-[10px] mr-1">{f.code}</span>{f.message}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
