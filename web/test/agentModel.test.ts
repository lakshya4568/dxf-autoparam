import { describe, expect, it } from "vitest";
import type { RunEvent, RunProgress } from "../src/api/types";
import {
  buildConversation, buildRunMessages, countCalls, currentCall, latestFinding, lifecycle, plainError, type AgentMessage, type RunData, type ToolCall,
} from "../src/agent/model";

let seq = 0;
const ev = (kind: string, rest: Partial<RunEvent> = {}): RunEvent => ({ kind, seq: seq++, t: seq / 10, ...rest });
const start = (instruction = "Reduce the span") => ev("run_start", { instruction, scope: { kind: "drawing" } });
const turn = (n: number) => ev("turn", { turn: n });
const ts = (id: string, name: string, stage: string, phase: string) => ev("tool_start", { id, name, doing: `doing ${name}`, stage, phase, args_full: { a: 1 } });
const tr = (id: string, name: string, stage: string, phase: string, extra: Partial<RunEvent> = {}) =>
  ev("tool", { id, name, doing: `doing ${name}`, stage, phase, ok: true, summary: `did ${name}`, ms: 12, result: { ok: true }, ...extra });

function run(events: RunEvent[], status = "running", extra: Partial<RunProgress> = {}): RunData {
  return { id: "R1", events, since: events.length, progress: { run: "R1", status, events: [], next: events.length, ...extra } };
}
const agentOf = (r: RunData) => buildRunMessages(r, true).filter((m): m is AgentMessage => m.type === "agent");
const tools = (m: AgentMessage): ToolCall[] => m.groups.flatMap((g) => g.items).flatMap((i) => (i.type === "tool" ? [i.call] : []));

describe("a run becomes a conversation", () => {
  it("starts with the instruction the person gave and the scope it applied to", () => {
    const msgs = buildRunMessages(run([start("Name the values")]), true);
    expect(msgs[0]).toMatchObject({ type: "user", text: "Name the values", scope: { kind: "drawing" } });
    expect(msgs[1].type).toBe("agent");
  });

  it("pairs a call with its result: the engine's words, status, time, input and output", () => {
    const m = agentOf(run([start(), turn(1), ts("c1", "inspect_view", "looking", "inspecting"), tr("c1", "inspect_view", "looking", "inspecting", { said: "look first" })]))[0];
    const [c] = tools(m);
    expect(c).toMatchObject({ name: "inspect_view", state: "done", summary: "did inspect_view", said: "look first", ms: 12, doing: "doing inspect_view", args: { a: 1 }, result: { ok: true } });
  });

  it("a failed call stays failed, with the reason", () => {
    const m = agentOf(run([start(), turn(1), ts("c1", "define_parts", "naming the parts", "applying"), tr("c1", "define_parts", "naming the parts", "applying", { ok: false, why: "no such region" })]))[0];
    expect(tools(m)[0]).toMatchObject({ state: "failed", why: "no such region" });
    expect(countCalls(m)).toMatchObject({ calls: 1, failed: 1, done: 0 });
  });

  it("calls announced together run in order: the first is running, the rest wait behind it", () => {
    const m = agentOf(run([start(), turn(1), ts("c1", "a", "inspecting", "inspecting"), ts("c2", "b", "inspecting", "inspecting"), ts("c3", "c", "inspecting", "inspecting")]))[0];
    expect(tools(m).map((c) => c.state)).toEqual(["running", "queued", "queued"]);
    expect(currentCall(m)?.name).toBe("a");
  });

  it("once the first result is in, the next one is the running call", () => {
    const m = agentOf(run([start(), turn(1), ts("c1", "a", "inspecting", "inspecting"), ts("c2", "b", "inspecting", "inspecting"), tr("c1", "a", "inspecting", "inspecting")]))[0];
    expect(tools(m).map((c) => c.state)).toEqual(["done", "running"]);
  });

  it("a call that never finished is not shown as running when the run is no longer active", () => {
    for (const status of ["stopped", "failed", "completed", "paused"]) {
      const m = agentOf(run([start(), turn(1), ts("c1", "a", "inspecting", "inspecting")], status))[0];
      expect(tools(m)[0].state).toBe("interrupted");
      expect(currentCall(m)).toBeNull();
    }
  });

  it("groups consecutive calls by the engine's stage and attaches the turn's thinking summary to the first call after it", () => {
    const m = agentOf(run([
      start(), turn(1), ev("thought", { text: "**Plan** read first" }), ev("thought", { text: "then the views" }),
      ts("c1", "inspect_sheet", "inspecting", "inspecting"), tr("c1", "inspect_sheet", "inspecting", "inspecting"),
      turn(2), ts("c2", "inspect_view", "inspecting", "inspecting"), tr("c2", "inspect_view", "inspecting", "inspecting"),
      turn(3), ts("c3", "define_parts", "naming the parts", "applying"), tr("c3", "define_parts", "naming the parts", "applying"),
    ], "completed"))[0];
    expect(m.groups.map((g) => g.stage)).toEqual(["Inspecting", "Naming the parts"]);
    expect(m.groups[0].items[0]).toMatchObject({ type: "thought", text: "**Plan** read first\n\nthen the views" });
    expect(m.groups[0].items.filter((i) => i.type === "tool")).toHaveLength(2);
    expect(m.turns).toBe(3);
  });

  it("records what the engine applied, a state change, a question and an error as notices", () => {
    const m = agentOf(run([
      start(), turn(1), ev("applied", { unit: "U01", revision: 3, values: ["ClearSpan"] }),
      ev("error", { text: "429 RESOURCE_EXHAUSTED" }), ev("state", { from: "running", to: "awaiting_user", reason: "a decision is needed" }),
    ], "awaiting_user"))[0];
    const items = m.groups.flatMap((g) => g.items);
    expect(items.find((i) => i.type === "applied")).toMatchObject({ text: "Applied values ClearSpan to U01 — sheet revision 3" });
    expect(items.find((i) => i.type === "notice" && i.tone === "bad")).toMatchObject({ detail: "429 RESOURCE_EXHAUSTED" });
    expect(m.ended).toEqual({ to: "awaiting_user", reason: "a decision is needed" });
  });

  it("where a stretch of work ended is said once (as `ended`), not again inside the timeline; a non-final state change stays in it", () => {
    const m = agentOf(run([start(), turn(1), ev("state", { from: "running", to: "stopping", reason: "stop requested" }), ev("state", { from: "stopping", to: "stopped", reason: "stopped by you" })], "stopped"))[0];
    const notices = m.groups.flatMap((g) => g.items).filter((i) => i.type === "notice");
    expect(notices).toHaveLength(1);
    expect(notices[0]).toMatchObject({ text: "Stopping — stop requested" });
    expect(m.ended).toEqual({ to: "stopped", reason: "stopped by you" });
  });

  it("a long question is cut in the timeline (the decision card holds it whole) and a unit already named in the values is not repeated", () => {
    const q = "x".repeat(400);
    const m = agentOf(run([start(), turn(1), ev("question", { text: q }), ev("applied", { unit: "U01", revision: 2, values: ["U01.Span"] })], "awaiting_user"))[0];
    const items = m.groups.flatMap((g) => g.items);
    expect((items.find((i) => i.type === "notice") as { text: string }).text).toHaveLength(148);
    expect(items.find((i) => i.type === "applied")).toMatchObject({ text: "Applied values U01.Span — sheet revision 2" });
  });

  it("a follow-up the person sent (a `user` event) opens a new exchange", () => {
    const msgs = buildRunMessages(run([start("one"), turn(1), ev("state", { from: "running", to: "paused" }), ev("user", { text: "carry on", answers: { q1: "centered" } }), turn(2)]), true);
    expect(msgs.map((m) => m.type)).toEqual(["user", "agent", "user", "agent"]);
    expect(msgs[2]).toMatchObject({ text: "carry on", answers: { q1: "centered" } });
    expect(msgs[1]).toMatchObject({ last: false, ended: { to: "paused" } });
    expect(msgs[3]).toMatchObject({ last: true, ended: null });
  });

  it("text from the drawing or the model is kept as plain text, never interpreted", () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const m = agentOf(run([start(hostile), turn(1), ts("c1", "inspect_view", "looking", "inspecting"), tr("c1", "inspect_view", "looking", "inspecting", { summary: hostile })]))[0];
    expect(tools(m)[0].summary).toBe(hostile);
    expect(latestFinding(m)).toBe(hostile);
  });

  it("earlier runs known only by their summary are shown as such", () => {
    const saved: RunData = { id: "R0", events: [], since: 0, progress: null, saved: { id: "R0", instruction: "old", status: "completed", label: "Complete", verdict: { headline: "done" } } };
    const msgs = buildConversation([saved, run([start("new")])], "R1");
    expect(msgs.map((m) => m.type)).toEqual(["earlier", "user", "agent"]);
  });
});

describe("the lifecycle comes from the run's state and the call in flight", () => {
  const life = (events: RunEvent[], status: string, extra: Partial<RunProgress> = {}) => lifecycle(run(events, status, extra));

  it("idle without a run, starting while the request is in flight", () => {
    expect(lifecycle(null).key).toBe("idle");
    expect(lifecycle(null, true)).toMatchObject({ key: "starting", active: true });
  });

  it("terminal and waiting states are the engine's", () => {
    expect(life([start()], "completed")).toMatchObject({ key: "completed", active: false, tone: "ok" });
    expect(life([start()], "failed", { error: "boom" })).toMatchObject({ key: "failed", detail: "boom", tone: "bad" });
    expect(life([start()], "stopped").key).toBe("cancelled");
    expect(life([start()], "awaiting_user")).toMatchObject({ key: "awaiting", active: false });
    expect(life([start()], "paused").key).toBe("paused");
    expect(life([start()], "exhausted").key).toBe("exhausted");
    expect(life([start()], "partial").key).toBe("partial");
    expect(life([start()], "stopping")).toMatchObject({ key: "stopping", active: true });
  });

  it("running: the phase of the call in flight, with what it is doing", () => {
    expect(life([start(), turn(1), ts("c1", "define_parts", "naming the parts", "applying")], "running")).toMatchObject({ key: "applying", detail: "doing define_parts", active: true });
    expect(life([start(), turn(1), ts("c1", "inspect_view", "looking", "inspecting")], "running").key).toBe("inspecting");
    expect(life([start(), turn(1), ts("c1", "finish", "validating", "validating")], "running").key).toBe("validating");
    expect(life([start(), turn(1), ts("c1", "mystery", "x", "unknown-phase")], "running").key).toBe("tool");
  });

  it("running with no call in flight: thinking once a turn began, otherwise the engine's phase", () => {
    expect(life([start(), turn(1), tr("c1", "a", "inspecting", "inspecting")], "running").key).toBe("thinking");
    expect(life([start()], "running", { phase: "inspecting" }).key).toBe("inspecting");
    expect(life([start()], "running").key).toBe("planning");
  });
});

describe("errors", () => {
  it("are explained when the cause is known, otherwise shown as they came", () => {
    expect(plainError("DEADLINE exceeded")).toMatch(/stopped answering/);
    expect(plainError("429 RESOURCE_EXHAUSTED")).toMatch(/out of capacity/);
    expect(plainError("403 permission denied")).toMatch(/credentials/);
    expect(plainError("ValueError: x")).toBeNull();
  });
});
