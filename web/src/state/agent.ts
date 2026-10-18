// The agent conversation's state and actions. There is ONE execution mechanism — the engine's run (src/dxf_autoparam/ai/run.py);
// this module only starts, stops, continues and watches it: events are read incrementally (a cursor, `since`) and kept as the engine
// sent them; the conversation is derived from them (agent/model.ts). A run is paid model time, so one is started only by the person's
// own send, and only after they accepted the cost for the chosen model.
import { api } from "../api/client";
import type { AgentNotes, RunProgress } from "../api/types";
import { ACTIVE, type RunData } from "../agent/model";
import { Store } from "./store";
import { refreshSheet, store as workspace } from "./workspace";

export type Mode = "compact" | "verbose";
export type ScopeKind = "auto" | "drawing" | "view" | "selection";

export interface AgentState {
  runs: Record<string, RunData>;
  order: string[]; // oldest first
  currentId: string | null;
  mode: Mode;
  models: { id: string; label: string }[];
  model: string;
  paidFor: string | null; // the model whose cost the person accepted in this page session
  draft: string;
  scopeKind: ScopeKind;
  busy: "starting" | "stopping" | "continuing" | null;
  /** an action that calls the paid model, waiting for the person to accept its cost */
  confirm: { action: "send" } | { action: "resume" } | { action: "answer"; answers: Record<string, string>; note: string } | null;
  error: string | null;
  notes: AgentNotes | null;
  loaded: boolean;
  /** group / tool keys the person opened or closed by hand (they win over the mode's default) */
  folds: Record<string, boolean>;
  /** the pictures the agent was given: the gallery open over the thread, and the picture shown large (independent of each other) */
  gallery: { open: boolean; shown: string | null };
}

const MODE_KEY = "dxf-autoparam.agent.mode";

function savedMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === "verbose" ? "verbose" : "compact";
  } catch {
    return "compact"; // storage blocked: the mode just does not persist
  }
}

export const agent = new Store<AgentState>({
  runs: {}, order: [], currentId: null, mode: savedMode(), models: [], model: "", paidFor: null, draft: "", scopeKind: "auto", busy: null, confirm: null, error: null, notes: null,
  loaded: false, folds: {}, gallery: { open: false, shown: null },
});

const POLL_MS = 600;
const polling = new Map<string, number>(); // run id → the token of the poll loop that owns it (a newer loop replaces an older one)
let nextToken = 1;

export function currentRun(s: AgentState = agent.get()): RunData | null {
  return s.currentId ? s.runs[s.currentId] ?? null : null;
}

export function isActive(r: RunData | null): boolean {
  return !!r?.progress && ACTIVE.has(r.progress.status);
}

function putRun(id: string, f: (r: RunData) => RunData): void {
  agent.set((s) => {
    const base = s.runs[id] ?? { id, events: [], since: 0, progress: null };
    return { runs: { ...s.runs, [id]: f(base) }, order: s.order.includes(id) ? s.order : [...s.order, id] };
  });
}

function fail(e: unknown): void {
  agent.set({ error: e instanceof Error ? e.message : String(e) });
}

export function setMode(mode: Mode): void {
  agent.set({ mode });
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* the mode is kept for this page only */
  }
}

export function setDraft(draft: string): void {
  agent.set({ draft });
}

export function setModel(model: string): void {
  agent.set({ model });
}

export function setScopeKind(scopeKind: ScopeKind): void {
  agent.set({ scopeKind });
}

export function toggleFold(key: string, now: boolean): void {
  agent.set((s) => ({ folds: { ...s.folds, [key]: !now } }));
}

export function toggleGallery(): void {
  agent.set((s) => ({ gallery: { ...s.gallery, open: !s.gallery.open } }));
}

export function closeGallery(): void {
  agent.set((s) => ({ gallery: { ...s.gallery, open: false } }));
}

/** Show one picture large (null closes it). The gallery behind it stays as it is. */
export function showPicture(id: string | null): void {
  agent.set((s) => ({ gallery: { ...s.gallery, shown: id } }));
}

export function acceptCost(model: string): void {
  agent.set({ paidFor: model });
}

export async function refreshNotes(): Promise<void> {
  try {
    agent.set({ notes: await api.notes() });
  } catch {
    agent.set({ notes: null });
  }
}

// ── reading a run ────────────────────────────────────────────────────────────────

/** One read of a run's progress: new events are appended once (the cursor moves), the rest replaces the previous status. */
async function readOnce(id: string): Promise<RunProgress | null> {
  const r = agent.get().runs[id];
  const p = await api.progress(id, r?.since ?? 0);
  const fresh = p.events ?? [];
  putRun(id, (cur) => {
    if ((cur.since ?? 0) > (p.next - fresh.length)) return cur; // an older read that arrived late: its events are already here
    return { ...cur, events: cur.events.concat(fresh), since: p.next, progress: { ...p, events: [] }, saved: undefined };
  });
  if (fresh.some((e) => e.kind === "applied" || (e.kind === "state" && ["completed", "partial", "stopped"].includes(String(e.to))))) void refreshSheet();
  return p;
}

/** Follow a run until it is no longer active. One loop per run; starting another replaces it. */
export function follow(id: string, resumed = false): void {
  const token = nextToken++;
  polling.set(id, token);
  let ticks = 0;
  let grace = resumed ? 10 : 0; // a run just continued may still read as paused for a moment before its worker marks it running
  const tick = async () => {
    if (polling.get(id) !== token) return;
    let p: RunProgress | null = null;
    try {
      p = await readOnce(id);
    } catch (e) {
      if (polling.get(id) === token) {
        polling.delete(id);
        fail(e);
      }
      return;
    }
    if (polling.get(id) !== token) return;
    if (++ticks % 8 === 0) void refreshNotes();
    if (p && ACTIVE.has(p.status)) {
      grace = 0;
      agent.set((s) => (s.busy === "starting" || s.busy === "continuing" ? { busy: null } : {})); // it is running: the run's own state says so now
      window.setTimeout(tick, POLL_MS);
      return;
    }
    if (grace-- > 0) {
      window.setTimeout(tick, POLL_MS);
      return;
    }
    polling.delete(id);
    agent.set((s) => (s.busy === "stopping" || s.busy === "continuing" || s.busy === "starting" ? { busy: null } : {}));
    void refreshNotes();
    void refreshSheet();
    void loadRuns();
  };
  void tick();
}

export function stopFollowing(): void {
  polling.clear();
}

/** Runs of this session, newest last. The latest few are replayed from the engine's events; older or saved ones are shown as summaries. */
export async function loadRuns(): Promise<void> {
  const list = await api.runs().catch(() => null);
  if (!list) return;
  const ordered = [...list.runs].reverse(); // the engine lists newest first
  const known = agent.get().runs;
  for (const r of ordered) {
    if (!known[r.id]) putRun(r.id, (cur) => ({ ...cur, saved: r }));
  }
  agent.set((s) => ({ order: ordered.map((r) => r.id).filter((id, i, a) => a.indexOf(id) === i), currentId: s.currentId ?? list.current ?? ordered[ordered.length - 1]?.id ?? null }));
  for (const r of ordered.slice(-4)) {
    const cur = agent.get().runs[r.id];
    if (cur && cur.events.length === 0 && cur.since === 0) {
      try {
        await readOnce(r.id);
      } catch {
        /* a run saved with the project, not live in this session: its summary is all there is */
      }
    }
  }
  const cur = currentRun();
  if (cur && isActive(cur) && !polling.has(cur.id)) follow(cur.id);
}

export async function initAgent(): Promise<void> {
  if (agent.get().loaded) return;
  agent.set({ loaded: true });
  api.models().then((m) => agent.set((s) => ({ models: m.models, model: s.model || m.default }))).catch(() => agent.set({ models: [] }));
  void refreshNotes();
  await loadRuns();
}

// ── acting ───────────────────────────────────────────────────────────────────────

export function scopePayload(): Record<string, unknown> {
  const a = agent.get(), w = workspace.get();
  const hasSel = w.selection.size > 0;
  const kind = a.scopeKind === "auto" ? (hasSel ? "selection" : w.focusView ? "view" : "drawing") : a.scopeKind;
  if (kind === "selection" && hasSel) return { kind, entities: [...w.selection] };
  if (kind === "view" && w.focusView) return { kind, views: [w.focusView] };
  return { kind: "drawing" };
}

export function costAccepted(s: AgentState = agent.get()): boolean {
  return !!s.model && s.paidFor === s.model;
}

/** Each of these calls the model again, so each asks first (once per model per page session) and then does the action. */
export function requestSend(): void {
  if (!canSend()) return;
  if (!costAccepted()) agent.set({ confirm: { action: "send" } });
  else void send();
}

export function requestResume(): void {
  if (!costAccepted()) agent.set({ confirm: { action: "resume" } });
  else void resume();
}

export function requestAnswer(answers: Record<string, string>, note: string): void {
  if (!costAccepted()) agent.set({ confirm: { action: "answer", answers, note } });
  else void answer(answers, note);
}

export function confirmCost(): void {
  const s = agent.get();
  const c = s.confirm;
  if (!c) return;
  agent.set({ paidFor: s.model, confirm: null });
  if (c.action === "send") void send();
  else if (c.action === "resume") void resume(s.draft.trim());
  else void answer(c.answers, c.note);
}

export function cancelCost(): void {
  agent.set({ confirm: null });
}

export function canSend(s: AgentState = agent.get()): boolean {
  const r = currentRun(s);
  return !s.busy && !isActive(r) && s.draft.trim().length > 0 && !!s.model;
}

/** The person's message. A run that can be continued takes it as a note and goes on; otherwise it starts a new run that follows the
 * conversation so far (the engine's parent link). Refused while anything is in flight, so a double send cannot start two runs. */
export async function send(): Promise<void> {
  const s = agent.get();
  const r = currentRun(s);
  const text = s.draft.trim();
  if (!text || s.busy || isActive(r)) return;
  agent.set({ busy: r?.progress?.can?.continue ? "continuing" : "starting", error: null });
  try {
    if (r?.progress?.can?.continue) {
      await api.continueRun(r.id, { note: text });
      agent.set({ draft: "" });
      follow(r.id, true);
    } else {
      const started = await api.startRun(text, scopePayload(), { model: s.model }, r && !r.saved ? r.id : undefined);
      putRun(started.run, (cur) => cur);
      agent.set({ draft: "", currentId: started.run });
      follow(started.run);
    }
  } catch (e) {
    agent.set({ busy: null });
    fail(e);
  }
}

export async function answer(answers: Record<string, string>, note: string): Promise<void> {
  const r = currentRun();
  if (!r || agent.get().busy) return;
  agent.set({ busy: "continuing", error: null });
  try {
    await api.continueRun(r.id, { answers, note });
    follow(r.id, true);
  } catch (e) {
    agent.set({ busy: null });
    fail(e);
  }
}

export async function resume(note = ""): Promise<void> {
  const r = currentRun();
  if (!r || agent.get().busy) return;
  agent.set({ busy: "continuing", error: null });
  try {
    await api.continueRun(r.id, { note });
    follow(r.id, true);
  } catch (e) {
    agent.set({ busy: null });
    fail(e);
  }
}

export async function stop(): Promise<void> {
  const r = currentRun();
  if (!r || agent.get().busy === "stopping" || !isActive(r)) return;
  agent.set({ busy: "stopping", error: null });
  try {
    await api.stopRun(r.id);
    if (!polling.has(r.id)) follow(r.id);
  } catch (e) {
    agent.set({ busy: null });
    fail(e);
  }
}

export async function applyHeld(): Promise<void> {
  const r = currentRun();
  if (!r) return;
  try {
    await api.applyRun(r.id);
    await readOnce(r.id);
    await refreshSheet();
  } catch (e) {
    fail(e);
  }
}

export async function revert(): Promise<void> {
  const r = currentRun();
  if (!r) return;
  try {
    await api.revertRun(r.id);
    await readOnce(r.id);
    await refreshSheet();
  } catch (e) {
    fail(e);
  }
}

export function dismissError(): void {
  agent.set({ error: null });
}

// for the end-to-end tests
if (typeof window !== "undefined") (window as unknown as Record<string, unknown>).__agent = { state: () => agent.get() };
