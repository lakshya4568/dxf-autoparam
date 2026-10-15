// The workspace's state and actions. The engine is the authority: every value, regeneration and check is asked of it; what is
// kept here is presentation — the camera, what is selected, what is hidden — and the primitives the engine last sent.
// The camera changes only when the person pans, zooms or asks to fit something: an edit, a preview, an undo never move it.
import { api, EngineError } from "../api/client";
import type { BehaviourReport, Box, DeltaResult, EntityRecord, Geometry, ParamInfo, Prim, Style, Summary, UnitInfo } from "../api/types";
import { DEFAULT_OVERLAYS, type HighlightSets, type Overlays } from "../canvas/renderer";
import { GridIndex, primBox } from "../canvas/spatial";
import { type Camera, DEFAULT_CAMERA, fitBox, padBox, unionBox, ViewHistory } from "../canvas/viewport";
import { Store } from "./store";

export type LeftTab = "views" | "layers" | "values" | "agent" | "fidelity";
export type RightTab = "inspect" | "validate";

export interface Preview {
  changes: Record<string, number>;
  ents: Set<number>;
  prims: Prim[];
  errors: string[];
  warnings: string[];
  ok: boolean;
}

export interface WorkspaceState {
  summary: Summary | null;
  prims: Prim[];
  styles: Style[];
  index: GridIndex | null;
  revision: number;
  cam: Camera;
  fitted: boolean;
  W: number;
  H: number;
  theme: "light" | "dark";
  hiddenLayers: Set<string>;
  hiddenStatus: Set<string>;
  statusOf: Record<string, string> | null;
  overlays: Overlays;
  selection: Set<number>;
  hover: number | null;
  focusView: string | null;
  highlight: HighlightSets | null;
  param: { key: string; info: ParamInfo | null } | null;
  unit: UnitInfo | null;
  preview: Preview | null;
  behaviour: BehaviourReport | null;
  issues: Set<number>;
  entity: EntityRecord | null;
  message: { text: string; kind: "ok" | "bad" | "info" } | null;
  busy: string | null;
  leftTab: LeftTab;
  rightTab: RightTab;
  leftWidth: number;
  rightWidth: number;
  leftOpen: boolean;
  rightOpen: boolean;
  frameMs: number;
}

export const store = new Store<WorkspaceState>({
  summary: null, prims: [], styles: [], index: null, revision: 0, cam: DEFAULT_CAMERA, fitted: false, W: 800, H: 600,
  theme: typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  hiddenLayers: new Set(), hiddenStatus: new Set(), statusOf: null, overlays: { ...DEFAULT_OVERLAYS }, selection: new Set(), hover: null,
  focusView: null, highlight: null, param: null, unit: null, preview: null, behaviour: null, issues: new Set(), entity: null, message: null,
  busy: null, leftTab: "views", rightTab: "inspect", leftWidth: 320, rightWidth: 360, leftOpen: true, rightOpen: true, frameMs: 0,
});

export const history = new ViewHistory();

function say(text: string, kind: "ok" | "bad" | "info" = "info"): void {
  store.set({ message: { text, kind } });
}

async function guard<T>(what: string, fn: () => Promise<T>): Promise<T | undefined> {
  store.set({ busy: what });
  try {
    return await fn();
  } catch (e) {
    say(e instanceof EngineError || e instanceof Error ? e.message : String(e), "bad");
    return undefined;
  } finally {
    store.set({ busy: null });
  }
}

// ── geometry ───────────────────────────────────────────────────────────────────────

export function setGeometry(g: Geometry): void {
  const s = store.get();
  store.set({ prims: g.prims, styles: g.styles, index: new GridIndex(g.prims, (s.summary?.frame ?? g.frame ?? g.extent) as Box) });
}

/** Entities in `delta` are replaced by the primitives the engine sent for them (as they now stand); nothing else changes. */
export function mergeDelta(prims: Prim[], delta: Prim[]): Prim[] {
  if (!delta.length) return prims;
  const ents = new Set(delta.map((p) => p.i));
  return prims.filter((p) => !ents.has(p.i)).concat(delta);
}

function afterCommit(res: DeltaResult): void {
  if (res.reload) {
    void loadAll(false);
    return;
  }
  const s = store.get();
  const prims = mergeDelta(s.prims, res.delta ?? []);
  const styles = res.styles ?? s.styles;
  store.set({
    prims, styles, index: new GridIndex(prims, (res.summary?.frame ?? s.summary?.frame ?? s.summary?.extent) as Box),
    summary: res.summary ?? s.summary, revision: res.summary?.revision ?? s.revision, preview: null,
  });
}

export async function loadAll(fit: boolean): Promise<void> {
  await guard("Loading the sheet…", async () => {
    const summary = await api.summary();
    if (summary.empty) {
      store.set({ summary: null, prims: [], index: null });
      return;
    }
    const g = await api.geometry();
    store.set({ summary, revision: summary.revision });
    setGeometry(g);
    if (fit || !store.get().fitted) fitSheet(false);
    void loadStatuses();
  });
}

export async function openFile(file: File): Promise<void> {
  await guard(`Reading ${file.name}…`, async () => {
    const bytes = await file.arrayBuffer();
    await api.open(file.name, bytes);
    store.set({ selection: new Set(), entity: null, preview: null, param: null, highlight: null, behaviour: null, issues: new Set(), fitted: false, focusView: null });
  });
  await loadAll(true);
}

async function loadStatuses(): Promise<void> {
  try {
    const st = await api.statuses();
    const statusOf: Record<string, string> = {};
    for (const [k, v] of Object.entries(st.entities)) statusOf[k] = v.status;
    store.set({ statusOf });
  } catch {
    store.set({ statusOf: null }); // no classification: nothing is filtered by status
  }
}

// ── the camera (only the person moves it) ───────────────────────────────────────────

export function setCamera(cam: Camera, remember = false): void {
  if (remember) history.push(store.get().cam);
  store.set({ cam });
}

export function fitBoxTo(box: Box, remember = true): void {
  const s = store.get();
  if (remember) history.push(s.cam);
  store.set({ cam: fitBox(box, s.W, s.H, 0.06, s.cam.rot), fitted: true });
}

export function fitSheet(remember = true): void {
  const s = store.get();
  const box = (s.summary?.frame ?? s.summary?.extent) as Box | undefined;
  if (box) fitBoxTo(box, remember);
}

export function fitView(gid: string): void {
  const g = store.get().summary?.groups.find((x) => x.id === gid);
  if (g) fitBoxTo(padBox(g.bbox, 0.04));
}

export function entitiesBox(ents: Set<number>): Box | null {
  const s = store.get();
  return unionBox(s.prims.filter((p) => ents.has(p.i)).map(primBox));
}

export function fitEntities(ents: Set<number>): void {
  const b = entitiesBox(ents);
  if (b) fitBoxTo(padBox(b, 0.35, 1e-6));
}

export function fitSelection(): void {
  fitEntities(store.get().selection);
}

export function back(): void {
  const c = history.back();
  if (c) store.set({ cam: c });
}

// ── selection and inspection ─────────────────────────────────────────────────────

export async function select(i: number | null, additive = false): Promise<void> {
  const s = store.get();
  if (i === null) {
    store.set({ selection: new Set(), entity: null });
    return;
  }
  const sel = new Set(additive ? s.selection : []);
  if (additive && sel.has(i)) sel.delete(i);
  else sel.add(i);
  store.set({ selection: sel, rightTab: "inspect", rightOpen: true });
  const rec = await guard("Asking the engine about it…", () => api.entity(i));
  if (rec) store.set({ entity: rec });
}

export function setHover(i: number | null): void {
  if (store.get().hover !== i) store.set({ hover: i });
}

// ── values ───────────────────────────────────────────────────────────────────────

export async function openUnit(uid: string): Promise<void> {
  const u = await guard("Reading the unit…", () => api.unit(uid));
  if (u) store.set({ unit: u });
}

export async function focusParam(key: string): Promise<void> {
  const info = await guard("Measuring what the value moves…", () => api.param(key));
  if (!info) return;
  const h = info.highlight;
  const holds = new Set<number>();
  for (const g of (h.holds as unknown[]) ?? []) {
    if (typeof g === "number") holds.add(g);
    else if (g && typeof g === "object" && "set" in (g as Record<string, unknown>)) for (const i of (g as { set: number[] }).set) holds.add(i);
  }
  store.set({ param: { key, info }, highlight: { drives: new Set(h.drives), follows: new Set(h.follows), texts: new Set(h.texts), holds } });
}

export function clearParam(): void {
  store.set({ param: null, highlight: null });
}

export async function previewChange(changes: Record<string, number>): Promise<void> {
  const res = await guard("Regenerating (nothing is applied)…", () => api.preview(changes));
  if (!res) return;
  const delta = res.delta ?? [];
  store.set({
    preview: { changes, ents: new Set(delta.map((p) => p.i)), prims: delta, errors: res.errors ?? [], warnings: res.warnings ?? [], ok: res.ok },
    styles: res.styles ?? store.get().styles,
  });
  if (!res.ok) say(`The change would break the sheet: ${(res.errors ?? [])[0] ?? ""}`, "bad");
}

export function cancelPreview(): void {
  store.set({ preview: null });
}

export async function applyChange(changes: Record<string, number>): Promise<boolean> {
  const res = await guard("Applying…", () => api.apply(changes));
  if (!res) return false;
  if (!res.ok) {
    say(`Refused, nothing changed: ${(res.errors ?? [])[0] ?? res.error ?? ""}`, "bad");
    return false;
  }
  afterCommit(res);
  const p = store.get().param;
  if (p) void focusParam(p.key);
  const u = store.get().unit;
  if (u) void openUnit(u.id);
  say("Applied — every check of the sheet holds.", "ok");
  return true;
}

export async function undo(): Promise<void> {
  const res = await guard("Undo…", () => api.undo());
  if (res) afterCommit(res);
}

export async function redo(): Promise<void> {
  const res = await guard("Redo…", () => api.redo());
  if (res) afterCommit(res);
}

/** The sheet entities a behaviour row is about: an annotation's entity, or a component's entities. */
export function rowEntities(r: Record<string, unknown>): number[] {
  if (typeof r.entity === "number") return [r.entity];
  return Array.isArray(r.entities) ? (r.entities as unknown[]).filter((x): x is number => typeof x === "number") : [];
}

export async function checkBehaviour(changes: Record<string, number>): Promise<void> {
  const rep = await guard("Checking the whole assembly…", () => api.behaviour(changes));
  if (!rep) return;
  const issues = new Set<number>();
  for (const c of Object.values(rep.categories))
    for (const r of c.items) if (r.status === "fail") for (const i of rowEntities(r)) issues.add(i);
  store.set({ behaviour: rep, issues, rightTab: "validate", rightOpen: true });
}

// ── what is shown ─────────────────────────────────────────────────────────────────

export function toggleLayer(name: string): void {
  const h = new Set(store.get().hiddenLayers);
  if (h.has(name)) h.delete(name);
  else h.add(name);
  store.set({ hiddenLayers: h });
}

export function toggleStatus(name: string): void {
  const h = new Set(store.get().hiddenStatus);
  if (h.has(name)) h.delete(name);
  else h.add(name);
  store.set({ hiddenStatus: h });
}

export function setOverlay<K extends keyof Overlays>(k: K, v: Overlays[K]): void {
  store.set({ overlays: { ...store.get().overlays, [k]: v } });
}

// for the end-to-end tests (web/e2e): the state and the actions, nothing more
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__ws = {
    state: () => store.get(),
    select, fitView, fitSheet, fitSelection, back, previewChange, applyChange, undo, redo, focusParam, toggleLayer, setOverlay, checkBehaviour, loadAll,
  };
}
