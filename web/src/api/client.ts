// HTTP calls to the engine. Every function returns the engine's own JSON (types.ts); a refusal (HTTP 409 / ok: false) is
// raised as an Error carrying the engine's reason, so the page says it instead of guessing.
import type {
  AgentNotes,
  AnchorOptions,
  Annotation,
  AutosaveInfo,
  BehaviourReport,
  Coverage,
  DeltaResult,
  EntityRecord,
  Geometry,
  LayerRow,
  LibraryInfo,
  ParamInfo,
  Prim,
  RunProgress,
  RunSummary,
  SettleOptions,
  Statuses,
  Style,
  Summary,
  UnitInfo,
} from "./types";

/** What an edit answers: the changed entities (if any), the sheet's summary, and the engine's own account of what it did. */
export type EditResult = DeltaResult & { result: Record<string, unknown> };

export class EngineError extends Error {
  constructor(message: string, readonly status: number, readonly body?: unknown) {
    super(message);
  }
}

/** How long a request may take before the page says the engine did not answer (instead of showing "working…" for ever). Reading a big drawing is the long one. */
const ANSWER_WITHIN_MS = 5 * 60_000;
const READ_WITHIN_MS = 15 * 60_000;

async function call<T>(method: "GET" | "POST", path: string, body?: unknown, raw?: BodyInit, within = ANSWER_WITHIN_MS): Promise<T> {
  const limit = new AbortController();
  const timer = setTimeout(() => limit.abort(), within);
  let r: Response;
  let text: string;
  try {
    r = await fetch(path, {
      method,
      headers: raw ? { "Content-Type": "application/octet-stream" } : body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal: limit.signal,
    });
    text = await r.text();
  } catch (e) {
    if (limit.signal.aborted) throw new EngineError(`The engine did not answer ${method} ${path.split("?")[0]} within ${Math.round(within / 60_000)} minutes. It may still be working: the page asks again when you do.`, 0);
    throw e;
  } finally {
    clearTimeout(timer);
  }
  let j: unknown = null;
  try {
    j = text ? JSON.parse(text) : null;
  } catch {
    throw new EngineError(`HTTP ${r.status}: ${text.slice(0, 200)}`, r.status);
  }
  const obj = j as { ok?: boolean; error?: string } | null;
  if (!r.ok || (obj && obj.ok === false && obj.error)) throw new EngineError(obj?.error || `HTTP ${r.status}`, r.status, j);
  return j as T;
}

const q = (o: Record<string, string | number | undefined | null>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");

export const api = {
  summary: () => call<Summary>("GET", "/api/sheet"),
  autosave: () => call<AutosaveInfo | null>("GET", "/api/sheet/autosave"),
  geometry: () => call<Geometry>("GET", "/api/sheet/geometry"),
  open: (name: string, bytes: ArrayBuffer) => call<Summary>("POST", `/api/sheet/open?${q({ name })}`, undefined, bytes, READ_WITHIN_MS),
  loading: () => call<{ loading: boolean; name?: string; elapsed_s?: number; busy?: { what: string; elapsed_s: number } }>("GET", "/api/sheet/loading"),
  reopen: (fresh: boolean) => call<Summary>("POST", "/api/sheet/reopen", { fresh }, undefined, READ_WITHIN_MS),
  unit: (id: string) => call<UnitInfo>("GET", `/api/sheet/unit?${q({ id })}`),
  param: (name: string) => call<ParamInfo>("GET", `/api/sheet/param?${q({ name })}`),
  preview: (changes: Record<string, number>) => call<DeltaResult>("POST", "/api/sheet/preview", { changes }),
  apply: (changes: Record<string, number>, live = false) => call<DeltaResult>("POST", "/api/sheet/apply", { changes, ...(live ? { live } : {}) }),
  original: () => call<{ prims: Prim[]; styles: Style[] }>("GET", "/api/sheet/original"),
  undo: () => call<DeltaResult>("POST", "/api/sheet/undo", {}),
  redo: () => call<DeltaResult>("POST", "/api/sheet/redo", {}),
  delta: () => call<DeltaResult>("GET", "/api/sheet/delta"),
  entity: (i: number) => call<EntityRecord>("GET", `/api/sheet/entity?${q({ i })}`),
  coverage: () => call<Coverage>("GET", "/api/sheet/coverage"),
  annotations: (view?: string) => call<{ annotations: Annotation[]; kinds: Record<string, number>; revision: number }>("GET", `/api/sheet/annotations?${q({ view })}`),
  layers: () => call<{ layers: LayerRow[]; status: { counts: Record<string, number>; learned_colours: Statuses["learned_colours"] } }>("GET", "/api/sheet/layers"),
  statuses: () => call<Statuses>("GET", "/api/sheet/statuses"),
  behaviour: (changes: Record<string, number>) => call<BehaviourReport>("POST", "/api/sheet/behaviour", { changes }),
  impact: (name: string, step?: number) => call<Record<string, unknown>>("GET", `/api/sheet/impact?${q({ name, step })}`),
  decide: (body: Record<string, unknown>) => call<{ ok: boolean; summary: Summary }>("POST", "/api/sheet/decide", body),
  notes: () => call<AgentNotes>("GET", "/api/sheet/agent_notes"),
  purgeGeneric: (unit?: string, dry_run = false) => call<EditResult>("POST", "/api/sheet/purge_generic", { unit, dry_run }),
  releaseFrozen: (unit: string, names?: string[]) => call<EditResult>("POST", "/api/sheet/release_frozen", { unit, names }),
  unlockPart: (unit: string, part: string) => call<EditResult>("POST", "/api/sheet/unlock_part", { unit, part }),
  anchor: (name: string, unit: string, mode: "start" | "end" | "centre", answer?: { decisions?: Record<string, string>; keep_as_drawn?: string[] }) =>
    call<EditResult>("POST", "/api/sheet/anchor", { name, unit, mode, ...(answer ?? {}) }),
  anchorOptions: (name: string, unit: string, mode: string) => call<AnchorOptions>("GET", `/api/sheet/anchor_options?${q({ name, unit, mode })}`),
  settleOptions: (name: string, unit: string) => call<SettleOptions>("GET", `/api/sheet/settle?${q({ name, unit })}`),
  settle: (name: string, unit: string, choice: string, discard_values = false) =>
    call<EditResult>("POST", "/api/sheet/settle", { name, unit, choice, ...(discard_values ? { discard_values } : {}) }),
  unsettle: (unit: string, choice: string) => call<EditResult>("POST", "/api/sheet/unsettle", { unit, choice }),
  intent: (unit?: string) => call<EditResult>("POST", "/api/sheet/intent", unit ? { unit } : {}),
  rename: (old: string, name: string) => call<{ ok: boolean; summary: Summary }>("POST", "/api/sheet/rename", { old, new: name }),
  resetValue: (name: string) => call<DeltaResult>("POST", "/api/sheet/reset_value", { name }),
  runs: () => call<{ runs: RunSummary[]; current: string | null }>("GET", "/api/sheet/ai/runs"),
  models: () => call<{ models: { id: string; label: string; thinking?: string; free?: boolean }[]; default: string }>("GET", "/api/sheet/ai/models"),
  startRun: (instruction: string, scope: Record<string, unknown>, options: Record<string, unknown>, parent?: string) =>
    call<{ ok: boolean; run: string }>("POST", "/api/sheet/ai/run", { instruction, scope, options, ...(parent ? { parent } : {}) }),
  progress: (run: string | null, since: number) => call<RunProgress>("GET", `/api/sheet/ai/progress?${q({ run, since })}`),
  stopRun: (run: string) => call<Record<string, unknown>>("POST", "/api/sheet/ai/stop", { run }),
  noteRun: (run: string, note: string) => call<{ ok: boolean; run: string }>("POST", "/api/sheet/ai/note", { run, note }),
  library: () => call<LibraryInfo>("GET", "/api/sheet/ai/library"),
  continueRun: (run: string, body: { note?: string; answers?: Record<string, string>; more_turns?: number }) =>
    call<{ ok: boolean; run: string }>("POST", "/api/sheet/ai/continue", { run, ...body }),
  applyRun: (run: string) => call<DeltaResult>("POST", "/api/sheet/ai/apply", { run }),
  revertRun: (run: string) => call<DeltaResult>("POST", "/api/sheet/ai/revert", { run }),
  exportUrl: () => "/api/sheet/export",
};
