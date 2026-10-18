// The pictures the agent was given — so the person can see exactly what the model saw. A gallery of thumbnails over the thread, and one
// picture shown large with what the engine says about it: what it is of, its scale, whether the drawing's own text could be read in it,
// which sheet revision it shows and on which turn the model got it. The list is the run's own `image` events (model.ts `picturesOf`);
// the picture files are the engine's (/api/sheet/ai/image) — nothing here is drawn or guessed by the page.
import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../state/store";
import { agent, closeGallery, showPicture, toggleGallery } from "../state/agent";
import { store as workspace } from "../state/workspace";
import { pictureStale, picturesOf, pictureTitle, type PictureInfo } from "./model";

/** Turn 0 is before the model's first turn: the pictures it begins with. */
const turnWords = (turn: number): string => (turn > 0 ? `turn ${turn}` : "at the start");

export const imageUrl = (runId: string, id: string): string => `/api/sheet/ai/image?run=${encodeURIComponent(runId)}&id=${encodeURIComponent(id)}`;

function usePictures(): { pics: PictureInfo[]; revision: number | null } {
  const run = useStore(agent, (s) => (s.currentId ? s.runs[s.currentId] ?? null : null));
  const revision = useStore(workspace, (s) => s.summary?.revision ?? null);
  const pics = useMemo(() => picturesOf(run), [run?.events]);
  return { pics, revision };
}

/** The tone of "could the model read this picture's text": the engine's own number, said plainly. */
function Readability({ p }: { p: PictureInfo }) {
  if (p.textPx === null || p.legible === null) return null;
  return p.legible
    ? <span className="rounded bg-emerald-100 dark:bg-emerald-950/50 px-1 text-emerald-800 dark:text-emerald-300" title="the drawing's own text is tall enough to read in this picture">text {p.textPx} px</span>
    : <span className="rounded bg-amber-100 dark:bg-amber-950/50 px-1 text-amber-800 dark:text-amber-300" title="the drawing's own text is too small to read in this picture: it is for structure">text {p.textPx} px · blur</span>;
}

export function PicturesButton() {
  const { pics } = usePictures();
  const open = useStore(agent, (s) => s.gallery.open);
  if (pics.length === 0) return null;
  return (
    <button
      className={`rounded border border-slate-300 dark:border-slate-600 px-1.5 py-0.5 text-[11px] ${open ? "bg-slate-200 dark:bg-slate-700 font-medium" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}
      onClick={toggleGallery} aria-pressed={open} data-testid="pictures-toggle" title="The pictures the agent was given"
    >
      Pictures <span className="num">{pics.length}</span>
    </button>
  );
}

const KIND_WORDS: Record<string, string> = { overview: "overviews", tile: "tiles", zoom: "zooms", sheet: "sheet" };

function Card({ p, stale }: { p: PictureInfo; stale: boolean }) {
  return (
    <li>
      <button
        className="block w-full overflow-hidden rounded border border-slate-200 dark:border-slate-700 text-left hover:border-sky-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500"
        onClick={() => showPicture(p.id)} data-testid="gallery-item" data-id={p.id} data-kind={p.kind} aria-label={`${p.id}, ${pictureTitle(p)}`}
      >
        <div className="flex h-24 items-center justify-center bg-white">
          <img loading="lazy" alt="" className="max-h-24 max-w-full object-contain" src={imageUrl(p.runId, p.id)} />
        </div>
        <div className="space-y-0.5 border-t border-slate-200 dark:border-slate-700 px-1.5 py-1 text-[11px]">
          <div className="truncate font-medium" title={pictureTitle(p)}>{pictureTitle(p)}</div>
          <div className="flex flex-wrap items-center gap-1 text-slate-500">
            <span className="font-mono">{p.id}</span>
            <span>{turnWords(p.turn)}</span>
            <Readability p={p} />
            {stale && <span className="rounded bg-slate-200 dark:bg-slate-700 px-1" title={`it shows revision ${p.revision}; the sheet has changed since`}>older sheet</span>}
          </div>
        </div>
      </button>
    </li>
  );
}

const SELECT = "rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-1 py-0.5 text-[11px]";

/** The gallery: laid over the thread (which stays where it was), filtered by unit and by kind. */
export function Gallery() {
  const { pics, revision } = usePictures();
  const [unit, setUnit] = useState("");
  const [kind, setKind] = useState("");
  const units = [...new Set(pics.map((p) => p.unit).filter((u): u is string => !!u))];
  const kinds = [...new Set(pics.map((p) => p.kind))];
  const shown = pics.filter((p) => (!unit || p.unit === unit) && (!kind || p.kind === kind));
  return (
    <div className="absolute inset-0 z-10 flex flex-col bg-white dark:bg-slate-900" data-testid="gallery" role="region" aria-label="Pictures the agent was given">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 dark:border-slate-700 px-3 py-1.5 text-[12px]">
        <span className="font-medium">Pictures the agent was given</span>
        <span className="text-slate-400 num" data-testid="gallery-count">{shown.length === pics.length ? pics.length : `${shown.length} of ${pics.length}`}</span>
        <span className="flex-1" />
        {units.length > 1 && (
          <select className={SELECT} value={unit} onChange={(e) => setUnit(e.target.value)} aria-label="Show the pictures of one unit">
            <option value="">All units</option>
            {units.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        )}
        {kinds.length > 1 && (
          <select className={SELECT} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Show one kind of picture">
            <option value="">All kinds</option>
            {kinds.map((k) => <option key={k} value={k}>{KIND_WORDS[k] ?? k}</option>)}
          </select>
        )}
        <button className="rounded px-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={closeGallery} aria-label="Close the gallery" data-testid="gallery-close">✕</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {shown.length === 0
          ? <p className="px-2 py-6 text-center text-[12px] text-slate-500">{pics.length === 0 ? "The agent has not been given a picture yet. Each unit it opens, and each closer look, appears here." : "No picture matches that filter."}</p>
          : <ul className="grid grid-cols-2 gap-2">{shown.map((p) => <Card key={p.id} p={p} stale={pictureStale(p, revision)} />)}</ul>}
      </div>
    </div>
  );
}

/** A range in one unit: metres when either end is ten metres or more, else millimetres. */
const range = (a: number | undefined, b: number | undefined): string => {
  if (a === undefined || b === undefined) return "?";
  return Math.max(Math.abs(a), Math.abs(b)) >= 10000 ? `${(a / 1000).toFixed(1)} → ${(b / 1000).toFixed(1)} m` : `${Math.round(a)} → ${Math.round(b)} mm`;
};
const size = (a: number, b: number): string => (Math.abs(b - a) >= 10000 ? `${((b - a) / 1000).toFixed(1)} m` : `${Math.round(b - a)} mm`);

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-x-2 py-0.5">
      <dt className="text-slate-400">{k}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function LightboxView({ pics, index, revision }: { pics: PictureInfo[]; index: number; revision: number | null }) {
  const p = pics[index];
  const [actual, setActual] = useState(false);
  const [broken, setBroken] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const go = (d: number) => showPicture(pics[(index + d + pics.length) % pics.length].id);
  const stale = pictureStale(p, revision);

  useEffect(() => {
    setActual(false);
    setBroken(false);
  }, [p.id]);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.focus();
    return () => opener?.focus?.(); // the person goes back to where they were
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        showPicture(null);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        e.stopPropagation(); // the canvas does not pan behind the picture
        go(e.key === "ArrowLeft" ? -1 : 1);
      } else if (e.key === "Tab") {
        const items = [...(box.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? [])];
        if (!items.length) return;
        const at = items.indexOf(document.activeElement as HTMLElement);
        if (e.shiftKey && at <= 0) {
          e.preventDefault();
          items[items.length - 1].focus();
        } else if (!e.shiftKey && (at === -1 || at === items.length - 1)) {
          e.preventDefault();
          items[0].focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const [x0, y0, x1, y1] = p.boxMm;
  const title = pictureTitle(p);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3" onClick={() => showPicture(null)} data-testid="lightbox-backdrop">
      <div
        ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`Picture ${p.id}: ${title}`} data-testid="lightbox" data-id={p.id}
        className="flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-white dark:bg-slate-900 shadow-xl outline-none md:flex-row" onClick={(e) => e.stopPropagation()}
      >
        <div className="flex min-h-[40vh] min-w-0 flex-1 items-start justify-center overflow-auto bg-white p-2">
          {broken
            ? <p className="m-auto max-w-[32ch] text-center text-[13px] text-slate-600" role="alert" data-testid="lightbox-broken">This picture is no longer kept by the engine. Ask the agent to look again.</p>
            : (
              <img
                alt={`${p.id}: ${title}`} src={imageUrl(p.runId, p.id)} onError={() => setBroken(true)} onClick={() => setActual(!actual)} data-testid="lightbox-image"
                className={actual ? "max-w-none cursor-zoom-out" : "max-h-[82vh] max-w-full cursor-zoom-in object-contain"} style={actual && p.size ? { width: p.size[0] } : undefined}
              />
            )}
        </div>
        <aside className="w-full shrink-0 overflow-y-auto border-t border-slate-200 dark:border-slate-700 p-3 text-[12px] md:w-72 md:border-l md:border-t-0" data-testid="lightbox-info">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="font-medium break-words">{title}</div>
              <div className="font-mono text-[11px] text-slate-400">{p.id} · {index + 1} of {pics.length}</div>
            </div>
            <button className="rounded px-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => showPicture(null)} aria-label="Close the picture" data-testid="lightbox-close">✕</button>
          </div>
          <dl className="mt-2">
            {p.unit && <Row k="Unit">{p.unit}</Row>}
            <Row k="Given">{turnWords(p.turn)}{p.why ? ` — ${p.why}` : ""}</Row>
            <Row k="Shows">
              {p.state === "current" ? "the sheet with the person’s values" : "the drawing as imported"}, revision {p.revision}
              {stale && <span className="block text-amber-700 dark:text-amber-400" data-testid="lightbox-stale">The sheet is now at revision {revision}: this shows an older drawing.</span>}
            </Row>
            {p.mmPerPx !== null && <Row k="Scale">{p.mmPerPx} mm per pixel</Row>}
            {p.textPx !== null && (
              <Row k="Text">
                {p.textPx} px tall — {p.legible ? <span className="text-emerald-700 dark:text-emerald-400">readable</span> : <span className="text-amber-700 dark:text-amber-400">a blur: this picture is for structure, the agent reads text from a closer one</span>}
              </Row>
            )}
            {p.boxMm.length === 4 && <Row k="Area">{range(x0, x1)} across, {range(y0, y1)} up ({size(x0, x1)} × {size(y0, y1)})</Row>}
            {p.size && <Row k="Size">{p.size[0]} × {p.size[1]} px</Row>}
            {p.tiles.length > 0 && <Row k="Tiles marked">{p.tiles.join(", ")}</Row>}
          </dl>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40" onClick={() => go(-1)} disabled={pics.length < 2} aria-label="Previous picture" data-testid="lightbox-prev">← Previous</button>
            <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40" onClick={() => go(1)} disabled={pics.length < 2} aria-label="Next picture" data-testid="lightbox-next">Next →</button>
            <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => setActual(!actual)} aria-pressed={actual} data-testid="lightbox-actual">{actual ? "Fit to window" : "Actual size"}</button>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">← → move between pictures · Esc closes</p>
        </aside>
      </div>
    </div>
  );
}

/** The picture shown large, when one is chosen (from the gallery, or from the line in the activity that says it was given). */
export function Lightbox() {
  const shown = useStore(agent, (s) => s.gallery.shown);
  const { pics, revision } = usePictures();
  const index = shown ? pics.findIndex((p) => p.id === shown) : -1;
  if (index < 0) return null;
  return <LightboxView pics={pics} index={index} revision={revision} />;
}
