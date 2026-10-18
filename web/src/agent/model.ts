// The conversation, built from what the engine actually emitted. Nothing here invents activity: a message is an instruction the
// person gave, a tool call is a call the agent made (its stage, words and result are the engine's), a notice is a state change,
// a question or an error the run reported. Everything is a pure function of the run's events and progress, so the same data
// serves the compact and the verbose view and is tested without a browser.
import type { RunEvent, RunProgress, RunQuestion, RunSummary, RunVerdict } from "../api/types";

export const ACTIVE = new Set(["queued", "running", "stopping"]);

export type ToolState = "running" | "queued" | "done" | "failed" | "interrupted";

export interface ToolCall {
  id: string;
  name: string;
  doing: string;
  state: ToolState;
  stage: string | null;
  phase: string | null;
  turn: number;
  summary?: string;
  said?: string;
  why?: string;
  ms?: number;
  unit?: string | null;
  args?: unknown;
  result?: unknown;
  image?: { id?: string; revision?: number; state?: string };
}

export type Tone = "info" | "ok" | "warn" | "bad";

export type Item =
  | { type: "tool"; call: ToolCall }
  | { type: "thought"; turn: number; text: string }
  | { type: "notice"; tone: Tone; text: string; detail?: string }
  | { type: "applied"; text: string }
  | { type: "picture"; ids: string[]; text: string } // consecutive pictures given together (an overview and its tiles) are one line
  | { type: "budget"; text: string };

/** Consecutive items that belong to one stage of the work (inspecting, binding values, validating …). */
export interface Group {
  key: string;
  stage: string;
  phase: string | null;
  items: Item[];
}

export interface UserMessage {
  type: "user";
  key: string;
  text: string;
  scope?: Record<string, unknown>;
  answers?: Record<string, string>;
  t?: number;
}

export interface AgentMessage {
  type: "agent";
  key: string;
  runId: string;
  groups: Group[];
  turns: number;
  model?: string;
  /** the state this stretch of work ended in (a `state` event), or null while it is still going */
  ended: { to: string; reason: string } | null;
  last: boolean; // the latest stretch of the latest run: the one that owns the live status, questions and verdict
}

export interface EarlierRun {
  type: "earlier";
  key: string;
  runId: string;
  instruction: string;
  status: string;
  label: string;
  headline?: string;
}

export type Message = UserMessage | AgentMessage | EarlierRun;

export interface RunData {
  id: string;
  events: RunEvent[];
  since: number;
  progress: RunProgress | null;
  /** a run this page cannot replay (saved with the project, not live in this session): only its summary exists */
  saved?: RunSummary;
}

const str = (v: unknown): string => (typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v));

/** The engine's plain-language reading of an error text, when it knows the cause (the same wording the previous page used). */
export function plainError(text: string): string | null {
  if (/timed out|no reply|Stalled|DEADLINE|504|did not answer/i.test(text))
    return "The model stopped answering (its shared capacity was busy) and the retries did not get through. What was checked stays: continue picks it up from there.";
  if (/429|RESOURCE_EXHAUSTED|capacity/i.test(text)) return "The model is out of capacity right now. Try again in a few minutes.";
  if (/credential|auth|permission|403/i.test(text)) return "The model refused the credentials. Run `gcloud auth application-default login`.";
  return null;
}

const STATE_TONE: Record<string, Tone> = { completed: "ok", failed: "bad", partial: "warn", exhausted: "warn", stopped: "warn", paused: "warn", awaiting_user: "warn" };

export const STATE_WORDS: Record<string, string> = {
  queued: "Waiting to start", running: "Working", stopping: "Stopping", paused: "Paused", awaiting_user: "Waiting for your decision", stopped: "Stopped",
  exhausted: "Out of budget", completed: "Complete", partial: "Partly done", failed: "Failed",
};

function stageLabel(stage: string | null | undefined): string {
  const s = (stage ?? "working").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function pictureLine(ids: string[], e: RunEvent): string {
  if (ids.length === 1) return `Picture ${ids[0]} given to the model — ${str(e.state)}, revision ${str(e.revision)}`;
  return `${ids.length} pictures given to the model — ${ids.length <= 3 ? ids.join(", ") : `${ids[0]} … ${ids[ids.length - 1]}`}`;
}

/** One picture the agent was given, as the person's gallery shows it: read off the run's `image` events, never invented. */
export interface PictureInfo {
  id: string;
  runId: string;
  seq: number;
  turn: number;
  unit: string | null;
  kind: string; // overview · tile · zoom · sheet
  caption: string;
  revision: number; // the sheet revision the picture shows
  state: string; // drawn · current
  why: string;
  mmPerPx: number | null;
  textPx: number | null;
  legible: boolean | null;
  boxMm: number[];
  size: [number, number] | null;
  tiles: string[];
}

/** Every picture a run gave the model, in the order given (an id the engine reported twice is listed once). */
export function picturesOf(run: RunData | null): PictureInfo[] {
  if (!run) return [];
  const seen = new Set<string>();
  const out: PictureInfo[] = [];
  for (const e of run.events) {
    if (e.kind !== "image" || !e.id || seen.has(e.id)) continue;
    seen.add(e.id);
    const p = e.pic;
    out.push({
      id: e.id, runId: run.id, seq: e.seq ?? out.length, turn: p?.turn ?? 0, unit: typeof e.unit === "string" ? e.unit : null, kind: p?.kind || "picture",
      caption: p?.caption ?? "", revision: Number(e.revision ?? 0), state: str(e.state), why: str(e.why), mmPerPx: p?.mm_per_px ?? null, textPx: p?.text_px ?? null,
      legible: p?.legible ?? null, boxMm: p?.box_mm ?? [], size: p?.size ?? null, tiles: p?.tiles ?? [],
    });
  }
  return out;
}

/** A picture shows an older sheet than the one now open: the person is told, the picture stays viewable. */
export const pictureStale = (p: PictureInfo, revision: number | null | undefined): boolean => revision !== null && revision !== undefined && p.revision < revision;

/** What the picture is of, in words: the engine's caption (e.g. "U01 · TILE_2"), else its kind. */
export const pictureTitle = (p: PictureInfo): string => p.caption || p.kind;

/** Events → messages. `active`: the run is still working (a call with no result is then in flight or queued, otherwise interrupted). */
export function buildRunMessages(run: RunData, isLastRun: boolean): Message[] {
  const status = run.progress?.status ?? "queued";
  const active = ACTIVE.has(status);
  const messages: Message[] = [];
  let seg: AgentMessage | null = null;
  let group: Group | null = null;
  let turn = 0;
  let thoughts: string[] = [];
  const calls = new Map<string, ToolCall>();
  const order: ToolCall[] = [];

  const open = (key: string): AgentMessage => {
    const m: AgentMessage = { type: "agent", key, runId: run.id, groups: [], turns: 0, ended: null, last: false };
    messages.push(m);
    group = null;
    thoughts = [];
    return m;
  };
  const ensureGroup = (m: AgentMessage, stage: string | null | undefined, phase: string | null | undefined): Group => {
    const label = stageLabel(stage);
    if (!group || group.stage !== label) {
      group = { key: `${m.key}/g${m.groups.length}`, stage: label, phase: phase ?? null, items: [] };
      m.groups.push(group);
    }
    return group;
  };
  const push = (m: AgentMessage, item: Item, stage?: string | null, phase?: string | null) => {
    const g = stage !== undefined || !group ? ensureGroup(m, stage ?? group?.stage ?? null, phase) : group;
    g.items.push(item);
  };
  const flushThoughts = (m: AgentMessage, stage?: string | null, phase?: string | null) => {
    if (!thoughts.length) return;
    push(m, { type: "thought", turn, text: thoughts.join("\n\n") }, stage, phase);
    thoughts = [];
  };
  const user = (e: RunEvent, text: string): AgentMessage => {
    messages.push({ type: "user", key: `${run.id}/u${e.seq ?? messages.length}`, text, scope: e.scope, answers: e.answers, t: e.t });
    return open(`${run.id}/a${e.seq ?? messages.length}`);
  };

  for (const e of run.events) {
    switch (e.kind) {
      case "run_start":
        seg = user(e, str(e.instruction));
        continue;
      case "user":
        seg = user(e, str(e.text));
        continue;
      default:
        break;
    }
    seg ??= open(`${run.id}/a0`); // events without a start (a run replayed from the middle): still shown
    const m: AgentMessage = seg;
    switch (e.kind) {
      case "turn":
        turn = e.turn ?? turn + 1;
        m.turns += 1;
        thoughts = [];
        break;
      case "call":
        if (e.model) m.model = e.model;
        break;
      case "thought":
        if (e.text) thoughts.push(e.text);
        break;
      case "retry":
        push(m, { type: "notice", tone: "warn", text: `Retrying: ${str(e.why)}` });
        break;
      case "stage":
        if (e.stage !== "validating" && e.text) push(m, { type: "notice", tone: "info", text: e.text }, e.stage, e.phase);
        break;
      case "tool_start": {
        const call: ToolCall = {
          id: str(e.id), name: str(e.name), doing: e.doing || str(e.name), state: "running", stage: e.stage ?? null, phase: e.phase ?? null, turn,
          unit: e.unit, args: e.args_full ?? e.args,
        };
        flushThoughts(m, call.stage, call.phase);
        push(m, { type: "tool", call }, call.stage, call.phase);
        calls.set(call.id, call);
        order.push(call);
        break;
      }
      case "tool": {
        let call = calls.get(str(e.id));
        if (!call) {
          call = { id: str(e.id), name: str(e.name), doing: e.doing || str(e.name), state: "done", stage: e.stage ?? null, phase: e.phase ?? null, turn };
          flushThoughts(m, call.stage, call.phase);
          push(m, { type: "tool", call }, call.stage, call.phase);
          calls.set(call.id, call);
        }
        call.state = e.ok === false ? "failed" : "done";
        call.summary = e.summary || undefined;
        call.said = e.said || undefined;
        call.why = e.why || undefined;
        call.ms = e.ms;
        call.unit = e.unit ?? call.unit;
        call.args = e.args_full ?? call.args;
        call.result = e.result;
        call.image = e.image;
        break;
      }
      case "image": {
        const id = str(e.id);
        const lastGroup = m.groups[m.groups.length - 1];
        const prev = lastGroup?.items[lastGroup.items.length - 1];
        if (prev?.type === "picture") {
          prev.ids.push(id);
          prev.text = pictureLine(prev.ids, e);
        } else push(m, { type: "picture", ids: [id], text: pictureLine([id], e) });
        break;
      }
      case "applied": {
        const what = e.feature ? `feature ${str(e.feature)}` : Array.isArray(e.values) && e.values.length ? `values ${(e.values as string[]).join(", ")}` : e.views ? `${str(e.views)} view(s)` : e.shared ? `${str(e.shared)} shared value(s)` : "changes";
        const unit = e.unit ? str(e.unit) : "";
        push(m, { type: "applied", text: `Applied ${what}${unit && !what.includes(unit) ? ` to ${unit}` : ""} — sheet revision ${str(e.revision)}` });
        break;
      }
      case "state": {
        const to = str(e.to);
        if (to === "running" && str(e.from) === "queued") break; // the start is the instruction itself
        // where this stretch of work ended is said once, at its foot (its result, or a closing line) — not also inside the timeline
        if (["completed", "partial", "failed", "exhausted", "stopped", "paused", "awaiting_user"].includes(to)) m.ended = { to, reason: str(e.reason) };
        else {
          if (to === "running") m.ended = null;
          push(m, { type: "notice", tone: STATE_TONE[to] ?? "info", text: `${STATE_WORDS[to] ?? to}${e.reason ? ` — ${str(e.reason)}` : ""}` });
        }
        break;
      }
      case "question": {
        const q = str(e.text);
        push(m, { type: "notice", tone: "warn", text: q.length > 150 ? `${q.slice(0, 147)}…` : q }); // the whole question is in the decision card
        break;
      }
      case "error": {
        const plain = plainError(str(e.text));
        push(m, { type: "notice", tone: "bad", text: plain ?? str(e.text), detail: plain ? str(e.text) : undefined });
        break;
      }
      case "note":
        push(m, { type: "notice", tone: "info", text: str(e.text) });
        break;
      case "budget":
        push(m, { type: "budget", text: `${str(e.turns)} turns · ${str(e.tool_calls)} tool calls · ${Number(e.tokens ?? 0).toLocaleString()} tokens` });
        break;
      default:
        break;
    }
  }
  if (seg) flushThoughts(seg);

  // a call with no result: the first is in flight, the rest wait behind it (one turn's calls run in order after all are announced);
  // when the run is no longer active none of them is running — they were cut short
  const pending = order.filter((c) => c.state === "running");
  pending.forEach((c, i) => {
    c.state = !active ? "interrupted" : i === 0 || c.turn !== pending[0].turn ? "running" : "queued";
  });
  const lastSeg = [...messages].reverse().find((x): x is AgentMessage => x.type === "agent");
  if (lastSeg && isLastRun) lastSeg.last = true;
  return messages;
}

/** The whole conversation: earlier runs (summaries only), then every run this page has the events of, oldest first. */
export function buildConversation(runs: RunData[], currentId: string | null): Message[] {
  const out: Message[] = [];
  runs.forEach((r, i) => {
    if (r.saved && !r.events.length) {
      out.push({ type: "earlier", key: `${r.id}/earlier`, runId: r.id, instruction: r.saved.instruction, status: r.saved.status, label: r.saved.label, headline: r.saved.verdict?.headline });
      return;
    }
    out.push(...buildRunMessages(r, r.id === currentId || i === runs.length - 1));
  });
  return out;
}

// ── lifecycle ───────────────────────────────────────────────────────────────────

export type LifeKey =
  | "idle" | "starting" | "thinking" | "planning" | "inspecting" | "tool" | "applying" | "validating" | "awaiting"
  | "paused" | "stopping" | "completed" | "partial" | "failed" | "cancelled" | "exhausted";

export interface Life {
  key: LifeKey;
  label: string;
  detail: string;
  active: boolean;
  tone: Tone;
}

const LIFE_LABEL: Record<LifeKey, string> = {
  idle: "Ready", starting: "Starting…", thinking: "Thinking…", planning: "Planning…", inspecting: "Inspecting the drawing…", tool: "Using tools…",
  applying: "Applying changes…", validating: "Validating…", awaiting: "Waiting for your answer", paused: "Paused", stopping: "Stopping…",
  completed: "Completed", partial: "Partly done", failed: "Failed", cancelled: "Stopped", exhausted: "Out of budget",
};

const PHASE_LIFE: Record<string, LifeKey> = { planning: "planning", inspecting: "inspecting", applying: "applying", validating: "validating", asking: "awaiting" };

/** What the run is doing now, from its status and the call in flight — never from a timer. */
export function lifecycle(run: RunData | null, starting = false): Life {
  const mk = (key: LifeKey, detail = "", active = false, tone: Tone = "info"): Life => ({ key, label: LIFE_LABEL[key], detail, active, tone });
  if (!run || !run.progress) return starting ? mk("starting", "", true) : mk("idle");
  const p = run.progress;
  switch (p.status) {
    case "queued":
      return mk("starting", "", true);
    case "stopping":
      return mk("stopping", p.reason ?? "", true, "warn");
    case "awaiting_user":
      return mk("awaiting", "the agent needs a decision", false, "warn");
    case "paused":
      return mk("paused", p.reason ?? "", false, "warn");
    case "stopped":
      return mk("cancelled", p.reason ?? "", false, "warn");
    case "exhausted":
      return mk("exhausted", p.reason ?? "", false, "warn");
    case "completed":
      return mk("completed", "", false, "ok");
    case "partial":
      return mk("partial", "", false, "warn");
    case "failed":
      return mk("failed", p.error ?? "", false, "bad");
    default:
      break;
  }
  // running
  const msgs = buildRunMessages(run, true);
  const calls = msgs.flatMap((m) => (m.type === "agent" ? m.groups.flatMap((g) => g.items) : [])).filter((i): i is Extract<Item, { type: "tool" }> => i.type === "tool");
  const live = calls.find((c) => c.call.state === "running");
  if (live) {
    const k = live.call.phase ? PHASE_LIFE[live.call.phase] ?? "tool" : "tool";
    return mk(k, `${live.call.doing}${live.call.unit ? ` · ${live.call.unit}` : ""}`, true);
  }
  if (run.events.some((e) => e.kind === "turn")) return mk("thinking", "", true);
  const k = p.phase ? PHASE_LIFE[p.phase] ?? "planning" : "planning";
  return mk(k, "", true);
}

// ── summaries for the collapsed view ──────────────────────────────────────────────

export interface Counts {
  calls: number;
  done: number;
  failed: number;
  running: number;
  queued: number;
  interrupted: number;
}

export function countCalls(m: AgentMessage): Counts {
  const c: Counts = { calls: 0, done: 0, failed: 0, running: 0, queued: 0, interrupted: 0 };
  for (const g of m.groups)
    for (const i of g.items)
      if (i.type === "tool") {
        c.calls += 1;
        c[i.call.state === "done" ? "done" : i.call.state === "failed" ? "failed" : i.call.state === "running" ? "running" : i.call.state === "queued" ? "queued" : "interrupted"] += 1;
      }
  return c;
}

export function currentCall(m: AgentMessage): ToolCall | null {
  for (const g of [...m.groups].reverse())
    for (const i of [...g.items].reverse()) if (i.type === "tool" && i.call.state === "running") return i.call;
  return null;
}

/** The engine's own sentence about the latest finished call: what the agent just learned or did. */
export function latestFinding(m: AgentMessage): string {
  for (const g of [...m.groups].reverse())
    for (const i of [...g.items].reverse()) if (i.type === "tool" && (i.call.state === "done" || i.call.state === "failed") && i.call.summary) return i.call.summary;
  return "";
}

export function questionsOf(run: RunData | null): RunQuestion[] {
  return run?.progress?.status === "awaiting_user" ? (run.progress.questions ?? []) : [];
}

export function verdictOf(run: RunData | null): RunVerdict | null {
  return run?.progress?.verdict ?? null;
}

export function fmtMs(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}
