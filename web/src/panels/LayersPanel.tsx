// What is shown: layers (each with its CAD properties and character), existing / proposed classes (from the drawing's own
// evidence), and the overlay categories — dimensions, texts, hatches, construction lines, and what a value drives / moves / holds.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LayerRow, Statuses } from "../api/types";
import type { Overlays } from "../canvas/renderer";
import { useStore } from "../state/store";
import { setOverlay, store, toggleLayer, toggleStatus } from "../state/workspace";

const OVERLAYS: [keyof Overlays, string][] = [
  ["dims", "Dimensions"], ["text", "Texts"], ["hatch", "Hatch patterns"], ["hatchTint", "Tint under pattern hatches"], ["construction", "Construction / centre lines"],
  ["drives", "What a value drives"], ["follows", "What moves with it"], ["holds", "What holds still"], ["texts", "Notes that state it"], ["issues", "Validation issues"],
];
const STATUSES = ["existing", "proposed", "removed", "construction", "alternative", "unclassified"];

export function LayersPanel() {
  const { hidden, hiddenStatus, overlays, revision } = useStore(store, (s) => ({ hidden: s.hiddenLayers, hiddenStatus: s.hiddenStatus, overlays: s.overlays, revision: s.revision }));
  const [layers, setLayers] = useState<LayerRow[]>([]);
  const [status, setStatus] = useState<{ counts: Record<string, number>; learned_colours: Statuses["learned_colours"] } | null>(null);
  useEffect(() => {
    api.layers().then((r) => { setLayers(r.layers); setStatus(r.status); }).catch(() => setLayers([]));
  }, [revision]);
  return (
    <div className="p-2 text-[13px]" data-testid="layers-panel">
      <h3 className="px-1 mb-1 text-[11px] uppercase tracking-wide text-slate-400">Layers</h3>
      <table className="w-full text-[12px]">
        <tbody>
          {layers.filter((l) => l.entities || !l.on || l.frozen).map((l) => (
            <tr key={l.name} className="hover:bg-slate-50 dark:hover:bg-slate-800/60" title={`${l.character}; ${Object.entries(l.types).map(([k, v]) => `${v} ${k}`).join(", ")}`}>
              <td className="w-5"><input type="checkbox" checked={!hidden.has(l.name)} onChange={() => toggleLayer(l.name)} data-testid={`layer-${l.name}`} /></td>
              <td className="w-4"><span className="inline-block w-3 h-3 rounded-sm border border-slate-300" style={{ background: Object.keys(l.colours_used)[0]?.startsWith("#") ? Object.keys(l.colours_used)[0] : l.color }} /></td>
              <td className="truncate max-w-[9rem]">{l.name}{!l.on && <span className="text-slate-400"> (off)</span>}{l.frozen && <span className="text-slate-400"> (frozen)</span>}</td>
              <td className="text-slate-400">{Object.keys(l.linetypes_used)[0] ?? l.linetype}</td>
              <td className="text-right num text-slate-500">{l.entities}</td>
              <td className="text-[11px] text-slate-400 pl-1">{l.name_says ?? l.character}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 className="px-1 mt-3 mb-1 text-[11px] uppercase tracking-wide text-slate-400">Existing / proposed</h3>
      <div className="flex flex-wrap gap-1 px-1">
        {STATUSES.map((st) => (
          <label key={st} className="flex items-center gap-1 rounded border border-slate-200 dark:border-slate-700 px-1.5 py-0.5 text-[12px]">
            <input type="checkbox" checked={!hiddenStatus.has(st)} onChange={() => toggleStatus(st)} data-testid={`status-${st}`} />
            {st} <span className="num text-slate-400">{status?.counts[st] ?? 0}</span>
          </label>
        ))}
      </div>
      {status && Object.keys(status.learned_colours).length > 0 && (
        <p className="px-1 mt-1 text-[11px] text-slate-500">
          Learned from this drawing's own notes: {Object.entries(status.learned_colours).map(([c, v]) => (
            <span key={c} className="mr-2"><span className="inline-block w-2.5 h-2.5 rounded-sm mr-0.5 align-middle" style={{ background: c }} />{v.status} ({v.count} notes{v.contrary ? `, ${v.contrary} contrary` : ""})</span>
          ))}. A colour alone never decides.
        </p>
      )}
      <h3 className="px-1 mt-3 mb-1 text-[11px] uppercase tracking-wide text-slate-400">Show</h3>
      <div className="grid grid-cols-1 gap-0.5 px-1">
        {OVERLAYS.map(([k, label]) => (
          <label key={k} className="flex items-center gap-2 text-[12px]">
            <input type="checkbox" checked={overlays[k]} onChange={(e) => setOverlay(k, e.target.checked)} data-testid={`overlay-${k}`} /> {label}
          </label>
        ))}
      </div>
    </div>
  );
}
