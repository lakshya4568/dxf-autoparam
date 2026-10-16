// The agent store against a fake engine: what is sent, what is refused, and when polling stops. No model is ever involved.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunEvent, RunProgress } from "../src/api/types";
import { agent, answer, canSend, confirmCost, currentRun, follow, requestAnswer, requestResume, requestSend, resume, send, setDraft, setMode, stop, stopFollowing } from "../src/state/agent";

type Call = { method: string; path: string; body: unknown };

class FakeEngine {
  calls: Call[] = [];
  status = "running";
  events: RunEvent[] = [];
  can: RunProgress["can"] = { stop: true, continue: false, answer: false, apply: false, revert: false };
  runs = 0;
  fail: string | null = null;
  startDelay = 0;

  handle = async (url: string, init?: RequestInit): Promise<Response> => {
    const u = new URL(url, "http://x");
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    this.calls.push({ method: init?.method ?? "GET", path: u.pathname, body });
    const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), { status, headers: { "Content-Type": "application/json" } });
    if (this.fail && u.pathname.endsWith(this.fail)) return json({ ok: false, error: "refused by the engine" }, 409);
    switch (u.pathname) {
      case "/api/sheet/ai/run":
        if (this.startDelay) await new Promise((r) => setTimeout(r, this.startDelay));
        this.runs += 1;
        this.status = "queued";
        this.events = [{ kind: "run_start", seq: 0, instruction: body.instruction, scope: body.scope }];
        return json({ ok: true, run: `R${this.runs}` });
      case "/api/sheet/ai/continue":
        this.status = "running";
        return json({ ok: true, run: body.run });
      case "/api/sheet/ai/stop":
        this.status = "stopped";
        return json({ ok: true, status: "stopped" });
      case "/api/sheet/ai/progress": {
        const since = Number(u.searchParams.get("since") ?? 0);
        const p: RunProgress = { run: u.searchParams.get("run"), status: this.status, events: this.events.slice(since), next: this.events.length, can: this.can, phase: null };
        return json(p);
      }
      case "/api/sheet/ai/runs":
        return json({ runs: [], current: null });
      case "/api/sheet/agent_notes":
        return json({ checklist: [], learned: [] });
      case "/api/sheet":
        return json({ file: "a.dxf", revision: 0, entities: 1, extent: [0, 0, 1, 1], groups: [], units: [], shared: [], values: {}, can_undo: false, can_redo: false, units_mm: 1 });
      case "/api/sheet/geometry":
        return json({ prims: [], styles: [], extent: [0, 0, 1, 1], frame: null });
      default:
        return json({ ok: true });
    }
  };
  count(path: string): number {
    return this.calls.filter((c) => c.path === path).length;
  }
}

let eng: FakeEngine;
const reset = () =>
  agent.set({ runs: {}, order: [], currentId: null, draft: "", busy: null, confirm: null, error: null, paidFor: null, model: "m1", models: [{ id: "m1", label: "Model 1" }], loaded: true, folds: {} });

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", globalThis);
  eng = new FakeEngine();
  vi.stubGlobal("fetch", vi.fn(eng.handle));
  stopFollowing();
  reset();
});
afterEach(() => {
  stopFollowing();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const settle = async (ms = 700) => {
  await vi.advanceTimersByTimeAsync(ms);
};

describe("sending", () => {
  it("nothing can be sent without text or without a model", () => {
    expect(canSend()).toBe(false);
    setDraft("  ");
    expect(canSend()).toBe(false);
    setDraft("go");
    expect(canSend()).toBe(true);
    agent.set({ model: "" });
    expect(canSend()).toBe(false);
  });

  it("the first send for a model asks about the cost and starts nothing", async () => {
    setDraft("Name the values");
    requestSend();
    expect(agent.get().confirm).toEqual({ action: "send" });
    await settle();
    expect(eng.count("/api/sheet/ai/run")).toBe(0);
  });

  it("accepting the cost starts one run with the person's words, the scope and the model; later sends do not ask again", async () => {
    setDraft("Name the values");
    requestSend();
    confirmCost();
    await settle(50);
    const start = eng.calls.find((c) => c.path === "/api/sheet/ai/run")!;
    expect(start.body).toMatchObject({ instruction: "Name the values", options: { model: "m1" }, scope: { kind: "drawing" } });
    expect(agent.get()).toMatchObject({ currentId: "R1", draft: "", confirm: null, paidFor: "m1" });
    eng.status = "completed";
    await settle(1500);
    setDraft("and again");
    requestSend();
    expect(agent.get().confirm).toBeNull();
    await settle(50);
    expect(eng.count("/api/sheet/ai/run")).toBe(2);
  });

  it("a second send while the first is in flight starts nothing", async () => {
    eng.startDelay = 200;
    agent.set({ paidFor: "m1" });
    setDraft("one");
    const first = send();
    const second = send();
    await vi.advanceTimersByTimeAsync(300);
    await Promise.all([first, second]);
    expect(eng.count("/api/sheet/ai/run")).toBe(1);
  });

  it("nothing is sent while the agent is working", async () => {
    agent.set({ paidFor: "m1" });
    setDraft("one");
    await send();
    await settle(50);
    expect(currentRun()?.progress?.status).toBe("queued");
    setDraft("two");
    await send();
    expect(eng.count("/api/sheet/ai/run")).toBe(1);
    expect(canSend()).toBe(false);
  });

  it("the next instruction continues the conversation: the previous run is its parent", async () => {
    agent.set({ paidFor: "m1" });
    setDraft("one");
    await send();
    eng.status = "completed";
    await settle(1500);
    setDraft("two");
    await send();
    const second = eng.calls.filter((c) => c.path === "/api/sheet/ai/run")[1];
    expect(second.body).toMatchObject({ instruction: "two", parent: "R1" });
  });

  it("a run that can be continued takes the message as a note instead of starting another", async () => {
    agent.set({ paidFor: "m1" });
    setDraft("one");
    await send();
    eng.status = "paused";
    eng.can = { stop: false, continue: true, answer: false, apply: false, revert: false };
    await settle(1500);
    setDraft("go on, keep the foundation");
    await send();
    expect(eng.count("/api/sheet/ai/run")).toBe(1);
    expect(eng.calls.find((c) => c.path === "/api/sheet/ai/continue")?.body).toMatchObject({ run: "R1", note: "go on, keep the foundation" });
  });

  it("an engine refusal is shown, nothing stays busy, and the draft is kept", async () => {
    eng.fail = "/ai/run";
    agent.set({ paidFor: "m1" });
    setDraft("one");
    await send();
    expect(agent.get()).toMatchObject({ error: "refused by the engine", busy: null, draft: "one" });
  });
});

describe("following a run", () => {
  it("reads new events once and stops reading when the run is no longer active", async () => {
    agent.set({ paidFor: "m1" });
    setDraft("one");
    await send();
    eng.status = "running";
    eng.events.push({ kind: "turn", seq: 1, turn: 1 });
    await settle(700);
    eng.events.push({ kind: "tool_start", seq: 2, id: "c1", name: "inspect_view" });
    await settle(700);
    expect(currentRun()?.events.map((e) => e.seq)).toEqual([0, 1, 2]);
    eng.status = "completed";
    await settle(700);
    const reads = eng.count("/api/sheet/ai/progress");
    await settle(5000);
    expect(eng.count("/api/sheet/ai/progress")).toBe(reads);
    expect(currentRun()?.progress?.status).toBe("completed");
  });

  it("an old read that arrives late does not duplicate events", async () => {
    follow("R9");
    await settle(10);
    expect(agent.get().runs["R9"].events).toHaveLength(0);
    eng.events = [{ kind: "turn", seq: 0 }, { kind: "turn", seq: 1 }];
    await settle(700);
    await settle(700);
    expect(agent.get().runs["R9"].events).toHaveLength(2);
    stopFollowing();
  });

  it("a run just continued that still reads as paused for a moment is not given up on", async () => {
    agent.set({ paidFor: "m1" });
    eng.status = "paused";
    eng.can = { stop: false, continue: true, answer: false, apply: false, revert: false };
    agent.set({ runs: { R1: { id: "R1", events: [], since: 0, progress: { run: "R1", status: "paused", events: [], next: 0, can: eng.can } } }, order: ["R1"], currentId: "R1" });
    const base = eng.handle;
    eng.handle = (async (url: string, init?: RequestInit) => {
      const u = new URL(url, "http://x");
      if (u.pathname === "/api/sheet/ai/continue") {
        setTimeout(() => (eng.status = "running"), 1500);
        return new Response(JSON.stringify({ ok: true, run: "R1" }), { status: 200 });
      }
      return base(url, init);
    }) as typeof eng.handle;
    vi.stubGlobal("fetch", vi.fn(eng.handle));
    await resume("go on");
    await settle(1000);
    expect(currentRun()?.progress?.status).toBe("paused");
    await settle(1500);
    expect(currentRun()?.progress?.status).toBe("running");
  });
});

describe("stopping and answering", () => {
  it("Stop is sent once however often it is pressed, and the run ends as stopped", async () => {
    agent.set({ paidFor: "m1" });
    setDraft("one");
    await send();
    eng.status = "running";
    await settle(700);
    const a = stop();
    const b = stop();
    await Promise.all([a, b]);
    await settle(1500);
    expect(eng.count("/api/sheet/ai/stop")).toBe(1);
    expect(currentRun()?.progress?.status).toBe("stopped");
    expect(agent.get().busy).toBeNull();
  });

  it("answers and resumes call the model again, so each asks about the cost first", async () => {
    eng.status = "awaiting_user";
    agent.set({ runs: { R1: { id: "R1", events: [], since: 0, progress: { run: "R1", status: "awaiting_user", events: [], next: 0, can: { stop: true, continue: false, answer: true, apply: false, revert: false } } } }, order: ["R1"], currentId: "R1" });
    requestAnswer({ q1: "centered" }, "");
    expect(agent.get().confirm).toMatchObject({ action: "answer", answers: { q1: "centered" } });
    expect(eng.count("/api/sheet/ai/continue")).toBe(0);
    confirmCost();
    await settle(50);
    expect(eng.calls.find((c) => c.path === "/api/sheet/ai/continue")?.body).toMatchObject({ run: "R1", answers: { q1: "centered" } });
    agent.set({ confirm: null });
    requestResume();
    expect(agent.get().confirm).toBeNull(); // accepted for this model already
    await answer({}, "x");
  });
});

describe("the detail mode", () => {
  it("is compact or verbose and is remembered where the browser allows it", () => {
    const store: Record<string, string> = {};
    vi.stubGlobal("localStorage", { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => (store[k] = v) });
    setMode("verbose");
    expect(agent.get().mode).toBe("verbose");
    expect(Object.values(store)).toEqual(["verbose"]);
    setMode("compact");
    expect(agent.get().mode).toBe("compact");
  });

  it("still works when storage is blocked", () => {
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    expect(() => setMode("verbose")).not.toThrow();
    expect(agent.get().mode).toBe("verbose");
  });
});
