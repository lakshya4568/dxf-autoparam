// The conversation, built from what the engine actually emitted. Nothing here invents activity: a message is an instruction the
// person gave, a step is one model turn (what it said it was doing, its thinking summary, the tools it called — by name), a notice
// is a state change, a question or an error the run reported. Everything is a pure function of the run's events and progress, so
// it is tested without a browser. Tool inputs and outputs are not kept here: the page shows which tool, never what it returned.
import type { RunEvent, RunProgress, RunQuestion, RunSummary, RunVerdict } from "../api/types";

export const ACTIVE = new Set(["queued", "running", "stopping"]);

export type ToolState = "running" | "queued" | "done" | "failed" | "interrupted";

export interface ToolCall {
  id: string;
  name: string;
  /** what the engine says the tool is doing, in the present tense (the header while it runs) — never what it returned */
  doing: string;
  state: ToolState;
  stage: string | null;
  phase: string | null;
  turn: number;
  unit?: string | null;
}

export type Tone = "info" | "ok" | "warn" | "bad";

/** One model turn: what it said it was doing, its thinking summary, and the tools it called. */
export interface Step {
  turn: number;
  /** the agent's own short sentence about the turn (its `why`, or words it wrote beside its calls); empty when it gave none */
  progress: string;
  thought: string;
  calls: ToolCall[];
}

export type Item =
  | { type: "step"; step: Step }
  | { type: "notice"; tone: Tone; text: string; detail?: string }
  | { type: "applied"; text: string };

export interface UserMessage {
  type: "user";
  key: string;
  text: string;
  scope?: Record<string, unknown>;
  answers?: Record<string, string>;
  /** said while the agent worked (a note), not an instruction or an answer */
  note?: boolean;
  t?: number;
}

export interface AgentMessage {
  type: "agent";
  key: string;
  runId: string;
  items: Item[];
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

/** The line a step shows above its tools: what the agent said it was doing, else what the engine says its first tool is doing. */
export const stepLine = (st: Step): string => st.progress || st.calls[0]?.doing || "";

/** Events → messages. `active`: the run is still working (a call with no result is then in flight or queued, otherwise interrupted). */
export function buildRunMessages(run: RunData, isLastRun: boolean): Message[] {
  const status = run.progress?.status ?? "queued";
  const active = ACTIVE.has(status);
  const messages: Message[] = [];
  let seg: AgentMessage | null = null;
  let step: Step | null = null;
  let turn = 0;
  const calls = new Map<string, ToolCall>();
  const order: ToolCall[] = [];

  const open = (key: string): AgentMessage => {
    const m: AgentMessage = { type: "agent", key, runId: run.id, items: [], turns: 0, ended: null, last: false };
    messages.push(m);
    step = null;
    return m;
  };
  const stepOf = (m: AgentMessage): Step => {
    if (!step) {
      step = { turn, progress: "", thought: "", calls: [] };
      m.items.push({ type: "step", step });
    }
    return step;
  };
  const push = (m: AgentMessage, item: Item) => {
    m.items.push(item);
  };
  const user = (e: RunEvent, text: string): AgentMessage => {
    messages.push({ type: "user", key: `${run.id}/u${e.seq ?? messages.length}`, text, scope: e.scope, answers: e.answers, note: !!e.while_working, t: e.t });
    return open(`${run.id}/a${e.seq ?? messages.length}`);
  };
  const said = (e: RunEvent): string => {
    const a = e.args_full;
    const why = a && typeof a === "object" ? (a as Record<string, unknown>).why : undefined;
    return typeof why === "string" ? why.trim() : "";
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
        step = null;
        stepOf(m).turn = turn;
        break;
      case "call":
        if (e.model) m.model = e.model;
        break;
      case "thought":
        if (e.text) {
          const st = stepOf(m);
          st.thought = st.thought ? `${st.thought}\n\n${e.text}` : e.text;
        }
        break;
      case "say":
        if (e.text) stepOf(m).progress = str(e.text).trim();
        break;
      case "retry":
        push(m, { type: "notice", tone: "warn", text: `Retrying: ${str(e.why)}` });
        break;
      case "tool_start": {
        const call: ToolCall = { id: str(e.id), name: str(e.name), doing: e.doing || str(e.name), state: "running", stage: e.stage ?? null, phase: e.phase ?? null, turn, unit: e.unit };
        const st = stepOf(m);
        st.calls.push(call);
        if (!st.progress) st.progress = said(e);
        calls.set(call.id, call);
        order.push(call);
        break;
      }
      case "tool": {
        let call = calls.get(str(e.id));
        if (!call) {
          call = { id: str(e.id), name: str(e.name), doing: e.doing || str(e.name), state: "done", stage: e.stage ?? null, phase: e.phase ?? null, turn };
          stepOf(m).calls.push(call);
          calls.set(call.id, call);
        }
        call.state = e.ok === false ? "failed" : "done";
        call.unit = e.unit ?? call.unit;
        if (step && !(step as Step).progress && e.said) (step as Step).progress = e.said;
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
      default:
        break; // stage, image, budget, status, verdict: the header, the pictures button and the result say them
    }
  }

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

/** Every call of a message, in order. */
export const callsOf = (m: AgentMessage): ToolCall[] => m.items.flatMap((i) => (i.type === "step" ? i.step.calls : []));

/** The agent's thinking summaries of a message, turn by turn (only the turns that have one). */
export const thoughtsOf = (m: AgentMessage): { turn: number; text: string }[] =>
  m.items.flatMap((i) => (i.type === "step" && i.step.thought ? [{ turn: i.step.turn, text: i.step.thought }] : []));

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
  const live = msgs.flatMap((m) => (m.type === "agent" ? callsOf(m) : [])).find((c) => c.state === "running");
  if (live) {
    const k = live.phase ? PHASE_LIFE[live.phase] ?? "tool" : "tool";
    return mk(k, `${live.doing}${live.unit ? ` · ${live.unit}` : ""}`, true);
  }
  if (run.events.some((e) => e.kind === "turn")) return mk("thinking", "", true);
  const k = p.phase ? PHASE_LIFE[p.phase] ?? "planning" : "planning";
  return mk(k, "", true);
}

// ── summaries for the activity header ────────────────────────────────────────────

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
  for (const call of callsOf(m)) {
    c.calls += 1;
    c[call.state === "done" ? "done" : call.state === "failed" ? "failed" : call.state === "running" ? "running" : call.state === "queued" ? "queued" : "interrupted"] += 1;
  }
  return c;
}

export function currentCall(m: AgentMessage): ToolCall | null {
  return [...callsOf(m)].reverse().find((c) => c.state === "running") ?? null;
}

export function questionsOf(run: RunData | null): RunQuestion[] {
  return run?.progress?.status === "awaiting_user" ? (run.progress.questions ?? []) : [];
}

export function verdictOf(run: RunData | null): RunVerdict | null {
  return run?.progress?.verdict ?? null;
}
