// HTTP calls to the engine. Every function returns the engine's own JSON (types.ts); a refusal (HTTP 409 / ok: false) is
// raised as an Error carrying the engine's reason, so the page says it instead of guessing.
import type {
  AgentNotes,
  Annotation,
  BehaviourReport,
  Coverage,
  DeltaResult,
  EntityRecord,
  Geometry,
  LayerRow,
  ParamInfo,
  RunProgress,
  RunSummary,
  Statuses,
  Summary,
  UnitInfo,
} from "./types";

export class EngineError extends Error {
  constructor(message: string, readonly status: number, readonly body?: unknown) {
    super(message);
  }
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown, raw?: BodyInit): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: raw ? { "Content-Type": "application/octet-stream" } : body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });
  const text = await r.text();
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
  geometry: () => call<Geometry>("GET", "/api/sheet/geometry"),
  open: (name: string, bytes: ArrayBuffer) => call<Summary>("POST", `/api/sheet/open?${q({ name })}`, undefined, bytes),
  unit: (id: string) => call<UnitInfo>("GET", `/api/sheet/unit?${q({ id })}`),
  param: (name: string) => call<ParamInfo>("GET", `/api/sheet/param?${q({ name })}`),
  preview: (changes: Record<string, number>) => call<DeltaResult>("POST", "/api/sheet/preview", { changes }),
  apply: (changes: Record<string, number>) => call<DeltaResult>("POST", "/api/sheet/apply", { changes }),
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
  rename: (old: string, name: string) => call<{ ok: boolean; summary: Summary }>("POST", "/api/sheet/rename", { old, new: name }),
  resetValue: (name: string) => call<DeltaResult>("POST", "/api/sheet/reset_value", { name }),
  runs: () => call<{ runs: RunSummary[]; current: string | null }>("GET", "/api/sheet/ai/runs"),
  models: () => call<{ models: { id: string; label: string; thinking?: string }[]; default: string }>("GET", "/api/sheet/ai/models"),
  startRun: (instruction: string, scope: Record<string, unknown>, options: Record<string, unknown>, parent?: string) =>
    call<{ ok: boolean; run: string }>("POST", "/api/sheet/ai/run", { instruction, scope, options, ...(parent ? { parent } : {}) }),
  progress: (run: string | null, since: number) => call<RunProgress>("GET", `/api/sheet/ai/progress?${q({ run, since })}`),
  stopRun: (run: string) => call<Record<string, unknown>>("POST", "/api/sheet/ai/stop", { run }),
  continueRun: (run: string, body: { note?: string; answers?: Record<string, string>; more_turns?: number }) =>
    call<{ ok: boolean; run: string }>("POST", "/api/sheet/ai/continue", { run, ...body }),
  applyRun: (run: string) => call<DeltaResult>("POST", "/api/sheet/ai/apply", { run }),
  revertRun: (run: string) => call<DeltaResult>("POST", "/api/sheet/ai/revert", { run }),
  exportUrl: () => "/api/sheet/export",
};
