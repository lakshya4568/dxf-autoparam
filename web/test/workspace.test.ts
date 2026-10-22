// The workspace state: an edit, a preview, an undo replace the engine's primitives for the entities that changed and never
// move the camera. fetch is faked: these tests exercise the state, not the server (that is web/e2e and tests/test_web_contract.py).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeltaResult, Prim, Summary } from "../src/api/types";
import { DEFAULT_OVERLAYS } from "../src/canvas/renderer";
import { applyChange, cancelPreview, chooseGrowth, deriveIntent, focusParam, hideWays, settleGrowth, showWays, takeBackChoice, openFile, startClean, keepUnnamedAsDrawn, liveChange, mergeDelta, previewChange, releaseKept, rowEntities, setOverlay, store, undo, unlockHeldPart } from "../src/state/workspace";

const L = (i: number, x: number): Prim => ({ i, k: "p", r: "structural", l: "0", v: "V1", p: [x, 0, x + 1, 1] });

const SUMMARY = { file: "a.dxf", path: "/a.dxf", units_mm: 1, extent: [0, 0, 100, 100], frame: null, entities: 3, notes: [], groups: [], furniture: { frame: [], rules: [], stray: [], watermark: [] },
  units: [], shared: [], values: {}, can_undo: true, can_redo: false, ai_running: false, current_run: null, revision: 4 } as Summary;

function fakeFetch(body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
}

describe("mergeDelta", () => {
  it("replaces only the entities the engine sent", () => {
    const prims = [L(0, 0), L(1, 10), { ...L(1, 20), k: "t" as const }, L(2, 30)];
    const out = mergeDelta(prims, [L(1, 99)]);
    expect(out.filter((p) => p.i === 1)).toEqual([L(1, 99)]); // both primitives of entity 1 replaced by what it is now
    expect(out.filter((p) => p.i !== 1)).toEqual([L(0, 0), L(2, 30)]);
    expect(mergeDelta(prims, [])).toBe(prims);
  });
});

describe("the camera stays where the person left it", () => {
  const cam = { cx: 41.5, cy: -3, s: 7.25, rot: 0 };
  beforeEach(() => {
    store.set({ summary: SUMMARY, prims: [L(0, 0), L(1, 10), L(2, 20)], styles: [], revision: 4, cam, fitted: true, preview: null, param: null, unit: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("through a preview", async () => {
    vi.stubGlobal("fetch", fakeFetch({ ok: true, delta: [L(1, 55)], errors: [], warnings: [] } satisfies DeltaResult));
    await previewChange({ "U1.Width": 1200 });
    const s = store.get();
    expect(s.cam).toEqual(cam);
    expect(s.preview?.ents).toEqual(new Set([1]));
    expect(s.prims.find((p) => p.i === 1)?.p?.[0]).toBe(10); // a preview changes nothing committed
    cancelPreview();
    expect(store.get().preview).toBeNull();
  });

  it("through an apply, which merges the delta and takes the new revision", async () => {
    vi.stubGlobal("fetch", fakeFetch({ ok: true, delta: [L(1, 55)], summary: { ...SUMMARY, revision: 5 } } satisfies DeltaResult));
    expect(await applyChange({ "U1.Width": 1200 })).toBe(true);
    const s = store.get();
    expect(s.cam).toEqual(cam);
    expect(s.revision).toBe(5);
    expect(s.prims.find((p) => p.i === 1)?.p?.[0]).toBe(55);
    expect(s.prims.find((p) => p.i === 0)?.p?.[0]).toBe(0);
    expect(s.message?.kind).toBe("ok");
  });

  it("through a refused apply, which changes nothing", async () => {
    vi.stubGlobal("fetch", fakeFetch({ ok: false, errors: ["V3: the outline self-intersects"] }));
    expect(await applyChange({ "U1.Width": -5 })).toBe(false);
    const s = store.get();
    expect(s.cam).toEqual(cam);
    expect(s.revision).toBe(4);
    expect(s.message?.kind).toBe("bad");
  });

  it("through an undo", async () => {
    vi.stubGlobal("fetch", fakeFetch({ ok: true, delta: [L(2, 77)], summary: { ...SUMMARY, revision: 6 } } satisfies DeltaResult));
    await undo();
    const s = store.get();
    expect(s.cam).toEqual(cam);
    expect(s.revision).toBe(6);
    expect(s.prims.find((p) => p.i === 2)?.p?.[0]).toBe(77);
  });
});

describe("stepping a value: the drawing follows, nothing is applied by hand", () => {
  const cam = { cx: 1, cy: 2, s: 3, rot: 0 };
  beforeEach(() => {
    store.set({ summary: SUMMARY, prims: [L(0, 0), L(1, 10)], styles: [], revision: 4, cam, fitted: true, preview: null, original: null, message: null,
      overlays: { ...store.get().overlays, original: false } });
  });
  afterEach(() => vi.unstubAllGlobals());

  /** A server whose apply answers are released one by one, so the page can be seen while a request is out. */
  function gated() {
    const sent: { path: string; body: Record<string, unknown> }[] = [];
    const release: ((r: unknown) => void)[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      sent.push({ path: String(url).split("?")[0], body: init?.body ? JSON.parse(String(init.body)) : {} });
      return new Promise<Response>((resolve) => release.push((r) => resolve(new Response(JSON.stringify(r), { status: 200, headers: { "Content-Type": "application/json" } }))));
    }));
    return { sent, release };
  }

  it("commits a step at once, as a live step, and the drawing and revision follow", async () => {
    const f = gated();
    const p = liveChange({ "U1.Width": 1200 });
    expect(f.sent).toEqual([{ path: "/api/sheet/apply", body: { changes: { "U1.Width": 1200 }, live: true } }]);
    expect(store.get().stepping).toBe(true); // the page shows the engine is working while the step is out
    f.release[0]({ ok: true, delta: [L(1, 55)], summary: { ...SUMMARY, revision: 5 } });
    expect(await p).toEqual({ ok: true });
    expect(store.get().stepping).toBe(false);
    expect(store.get().revision).toBe(5);
    expect(store.get().prims.find((q) => q.i === 1)?.p?.[0]).toBe(55);
    expect(store.get().cam).toEqual(cam);
    expect(store.get().preview).toBeNull();
  });

  it("while one step is out only the latest following step is sent: one request at a time", async () => {
    const f = gated();
    const first = liveChange({ "U1.Width": 1100 });
    const second = liveChange({ "U1.Width": 1200 });
    const third = liveChange({ "U1.Width": 1300 });
    expect(f.sent.length).toBe(1);
    f.release[0]({ ok: true, delta: [L(1, 11)], summary: { ...SUMMARY, revision: 5 } });
    await vi.waitFor(() => expect(f.sent.length).toBe(2));
    expect(f.sent[1].body).toEqual({ changes: { "U1.Width": 1300 }, live: true }); // 1200 was never asked for
    f.release[1]({ ok: true, delta: [L(1, 13)], summary: { ...SUMMARY, revision: 6 } });
    expect(await Promise.all([first, second, third])).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(store.get().revision).toBe(6);
  });

  it("a refused step changes nothing and says why", async () => {
    const f = gated();
    const p = liveChange({ "U1.Width": -5 });
    f.release[0]({ ok: false, errors: ["V3: the outline self-intersects"] });
    expect(await p).toEqual({ ok: false, error: "V3: the outline self-intersects" });
    expect(store.get().revision).toBe(4);
    expect(store.get().prims.find((q) => q.i === 1)?.p?.[0]).toBe(10);
    expect(store.get().message).toEqual({ text: expect.stringContaining("self-intersects"), kind: "bad" });
    // the next step still goes out (the queue was not left stuck)
    const again = liveChange({ "U1.Width": 1200 });
    expect(f.sent.length).toBe(2);
    f.release[1]({ ok: true, delta: [], summary: { ...SUMMARY, revision: 5 } });
    expect(await again).toEqual({ ok: true });
  });

  it("an engine that cannot be reached is said in the banner, and the queue is not stuck", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("connection refused"); }));
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(await liveChange({ "U1.Width": 1200 })).toEqual({ ok: false, error: "connection refused" });
    expect(store.get().message?.kind).toBe("bad");
    quiet.mockRestore();
  });

  it("with the original switched off, nothing is read for it while editing", async () => {
    const f = gated();
    const p = liveChange({ "U1.Width": 1200 });
    f.release[0]({ ok: true, delta: [L(1, 55)], summary: { ...SUMMARY, revision: 5 } });
    await p;
    expect(f.sent.map((x) => x.path)).toEqual(["/api/sheet/apply"]); // no request for the original
    expect(store.get().original).toBeNull();
    expect(store.get().overlays.original).toBe(false);
  });

  it("the original is on unless switched off: an entity's original is read once, the first time it changes, and dropped when it is back as drawn", async () => {
    expect(DEFAULT_OVERLAYS.original).toBe(true);
    store.set({ overlays: { ...store.get().overlays, original: true }, original: null });
    const f = gated();
    const p = liveChange({ "U1.Width": 1200 });
    f.release[0]({ ok: true, delta: [L(1, 55)], differs: [1], summary: { ...SUMMARY, revision: 5 } });
    await p;
    await vi.waitFor(() => expect(f.sent.map((x) => x.path)).toEqual(["/api/sheet/apply", "/api/sheet/original"]));
    f.release[1]({ prims: [L(1, 10)], styles: [] });
    await vi.waitFor(() => expect(store.get().original?.prims.length).toBe(1));
    const q = liveChange({ "U1.Width": 1300 });
    f.release[2]({ ok: true, delta: [L(1, 66)], differs: [1], summary: { ...SUMMARY, revision: 6 } });
    await q;
    expect(f.sent.map((x) => x.path)).toEqual(["/api/sheet/apply", "/api/sheet/original", "/api/sheet/apply"]); // the same entity: nothing more read
    expect(store.get().prims.find((x) => x.i === 1)?.p?.[0]).toBe(66);
    const r = liveChange({ "U1.Width": 1000 });
    f.release[3]({ ok: true, delta: [L(1, 10)], differs: [], summary: { ...SUMMARY, revision: 7 } });
    await r;
    expect(store.get().original?.prims).toEqual([]); // back as drawn: its original is dropped, and nothing is read
    expect(f.sent.length).toBe(4);
  });

  it("switching the original on reads it; later steps keep it current; switching it off drops it", async () => {
    const f = gated();
    setOverlay("original", true);
    expect(f.sent).toEqual([{ path: "/api/sheet/original", body: {} }]);
    f.release[0]({ prims: [L(1, 10)], styles: [] });
    await vi.waitFor(() => expect(store.get().original?.prims.length).toBe(1));
    const p = liveChange({ "U1.Width": 1200 });
    f.release[1]({ ok: true, delta: [L(1, 55)], summary: { ...SUMMARY, revision: 5 } });
    await p;
    await vi.waitFor(() => expect(f.sent.map((x) => x.path)).toEqual(["/api/sheet/original", "/api/sheet/apply", "/api/sheet/original"]));
    f.release[2]({ prims: [L(1, 10), L(2, 20)], styles: [] });
    await vi.waitFor(() => expect(store.get().original?.prims.length).toBe(2));
    expect(store.get().prims.find((q) => q.i === 1)?.p?.[0]).toBe(55); // the drawing itself shows the new size, not the original
    setOverlay("original", false);
    expect(store.get().original).toBeNull();
  });
});

describe("behaviour rows", () => {
  it("name an annotation's entity or a component's entities", () => {
    expect(rowEntities({ entity: 7 })).toEqual([7]);
    expect(rowEntities({ entities: [1, 2, "x"] })).toEqual([1, 2]);
    expect(rowEntities({ value: "Width" })).toEqual([]);
  });
});

describe("picking a value (the click that did nothing)", () => {
  const info = (highlight: Record<string, unknown>) => ({
    impact: { name: "U01.ClearSpan", value: 3925, step: 196, views: ["V01"], entities: 12, per_view: { V01: 12 }, errors: [] },
    range: { name: "U01.ClearSpan", value: 3925, min: 1000, max: 9000 },
    highlight,
  });
  beforeEach(() => store.set({ summary: SUMMARY, param: null, highlight: null, message: null }));
  afterEach(() => vi.unstubAllGlobals());

  it("opens the editor when nothing is held and the engine sends {}", async () => {
    vi.stubGlobal("fetch", fakeFetch(info({ drives: [1, 2], follows: [3], texts: [4], holds: {}, open: {} })));
    await focusParam("U01.ClearSpan");
    const s = store.get();
    expect(s.param?.key).toBe("U01.ClearSpan");
    expect(s.highlight?.drives).toEqual(new Set([1, 2]));
    expect(s.highlight?.holds).toEqual(new Set());
    expect(s.message).toBeNull();
  });

  it("reads what is held when the engine sends label → entities", async () => {
    vi.stubGlobal("fetch", fakeFetch(info({ drives: [], follows: [], texts: [], holds: { "Foundation (keep_fixed)": [7, 8] } })));
    await focusParam("U01.ClearSpan");
    expect(store.get().highlight?.holds).toEqual(new Set([7, 8]));
  });

  it.each([["null", null], ["undefined", undefined], ["a list", [5, 6]], ["groups", [{ label: "x", set: [9] }]]])("holds as %s", async (_name, holds) => {
    vi.stubGlobal("fetch", fakeFetch(info({ drives: [], follows: [], texts: [], holds })));
    await focusParam("U01.ClearSpan");
    expect(store.get().param?.key).toBe("U01.ClearSpan");
    expect(store.get().highlight).not.toBeNull();
    expect(store.get().message).toBeNull();
  });

  it("opens the editor and says so in the banner when a field is missing or malformed", async () => {
    vi.stubGlobal("fetch", fakeFetch(info({ drives: "garbage", holds: 7 })));
    await focusParam("U01.ClearSpan");
    expect(store.get().param?.key).toBe("U01.ClearSpan"); // the value can still be changed
    expect(store.get().highlight?.drives).toEqual(new Set());
  });

  it("says it in the banner (and never rejects) when the engine cannot be asked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: false, error: "no value U01.Nope" }), { status: 400, headers: { "Content-Type": "application/json" } })));
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await expect(focusParam("U01.Nope")).resolves.toBeUndefined();
    expect(store.get().message).toEqual({ text: expect.stringContaining("no value U01.Nope"), kind: "bad" });
    expect(store.get().param).toBeNull();
    quiet.mockRestore();
  });
});

describe("values nobody named, and work kept as drawn", () => {
  const UNIT = { id: "U01", revision: 6, views: ["V01"], params: [], measured: [], frozen: [], findings: [], components: [] };
  /** A server that answers each path with its own body, and remembers what it was asked. */
  function routed(routes: Record<string, unknown>) {
    const asked: { path: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).split("?")[0];
      asked.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (!(path in routes)) return new Response(JSON.stringify({ ok: false, error: `no route ${path}` }), { status: 404, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify(routes[path]), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    return asked;
  }
  beforeEach(() => store.set({ summary: SUMMARY, prims: [L(0, 0)], styles: [], revision: 4, unit: null, message: null, busy: null }));
  afterEach(() => vi.unstubAllGlobals());

  it("keeping them as drawn asks the engine for the unit, takes the new revision, and says how many (and that the drawing is as it was)", async () => {
    const asked = routed({ "/api/sheet/purge_generic": { ok: true, result: { kept: 85, left_as_inputs: {} }, delta: [], summary: { ...SUMMARY, revision: 5 } }, "/api/sheet/unit": UNIT });
    await keepUnnamedAsDrawn("U01");
    expect(asked[0]).toEqual({ path: "/api/sheet/purge_generic", body: { unit: "U01", dry_run: false } });
    expect(store.get().revision).toBe(5);
    expect(store.get().message?.kind).toBe("ok");
    expect(store.get().message?.text).toContain("85 measured sizes");
    expect(store.get().message?.text).toContain("as it was");
    expect(asked.some((a) => a.path === "/api/sheet/unit")).toBe(true); // the unit is read again: the list is the engine's
  });

  it("says plainly when there was nothing to keep, and names a unit the engine left alone", async () => {
    routed({ "/api/sheet/purge_generic": { ok: true, result: { kept: 0, left_as_inputs: {} }, delta: [], summary: SUMMARY }, "/api/sheet/unit": UNIT });
    await keepUnnamedAsDrawn();
    expect(store.get().message).toEqual({ text: expect.stringContaining("Nothing to keep as drawn"), kind: "info" });
    routed({ "/api/sheet/purge_generic": { ok: true, result: { kept: 12, left_as_inputs: { U04: "2 entities would move" } }, delta: [], summary: SUMMARY }, "/api/sheet/unit": UNIT });
    await keepUnnamedAsDrawn();
    expect(store.get().message?.text).toContain("left as inputs in U04");
  });

  it("releasing gives them back, and unlocking says which sizes are inputs again and that nothing moved", async () => {
    const asked = routed({
      "/api/sheet/release_frozen": { ok: true, result: { released: ["GapX1", "GapX2"] }, delta: [], summary: { ...SUMMARY, revision: 6 } },
      "/api/sheet/unlock_part": { ok: true, result: { inputs_again: ["ExistingClearSpan"] }, delta: [], summary: { ...SUMMARY, revision: 7 } },
      "/api/sheet/unit": UNIT,
    });
    await releaseKept("U01", ["GapX1", "GapX2"]);
    expect(asked[0].body).toEqual({ unit: "U01", names: ["GapX1", "GapX2"] });
    expect(store.get().message?.text).toContain("2 size(s) are inputs again");
    await unlockHeldPart("U01", "ExistingStructure");
    expect(asked.find((a) => a.path === "/api/sheet/unlock_part")?.body).toEqual({ unit: "U01", part: "ExistingStructure" });
    expect(store.get().revision).toBe(7);
    expect(store.get().message?.text).toContain("ExistingClearSpan is an input again");
    expect(store.get().message?.text).toContain("Nothing moved");
  });

  it("shows the engine's refusal in the banner and changes nothing", async () => {
    routed({ "/api/sheet/purge_generic": { ok: false, error: "the agent is working on this sheet: stop it first" } });
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await keepUnnamedAsDrawn("U01");
    expect(store.get().message).toEqual({ text: expect.stringContaining("the agent is working"), kind: "bad" });
    expect(store.get().revision).toBe(4);
    quiet.mockRestore();
  });
});

describe("which side of a value stays when it changes (design intent)", () => {
  const UNIT = { id: "U01", revision: 6, views: ["V01"], params: [], measured: [], frozen: [], findings: [], components: [] };
  const PARAM = { impact: { name: "U01.ClearSpan", value: 6000, step: 10, views: ["V01"], entities: 3, per_view: {}, errors: [] }, range: { name: "U01.ClearSpan", value: 6000 },
    highlight: { drives: [], follows: [], texts: [], holds: null },
    growth: [{ unit: "U01", mode: "end", from: "x1", to: "x2", why: "x2 stays, x1 moves", intent: { policy: "end_fixed", centre: null, source: "person", status: "person", evidence: [] } }] };
  function routed(routes: Record<string, unknown>) {
    const asked: { path: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).split("?")[0];
      asked.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (!(path in routes)) return new Response(JSON.stringify({ ok: false, error: `no route ${path}` }), { status: 404, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify(routes[path]), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    return asked;
  }
  beforeEach(() => store.set({ summary: SUMMARY, prims: [L(0, 0)], styles: [], revision: 4, unit: null, param: null, highlight: null, message: null, busy: null }));
  afterEach(() => vi.unstubAllGlobals());

  it("choosing a side asks the engine for the person's plan, says it replaces the default, and reads the value again", async () => {
    const asked = routed({ "/api/sheet/anchor": { ok: true, result: { plan: "P1" }, delta: [], summary: { ...SUMMARY, revision: 5 } }, "/api/sheet/param": PARAM });
    await chooseGrowth("U01.ClearSpan", "U01", "end");
    expect(asked[0]).toEqual({ path: "/api/sheet/anchor", body: { name: "U01.ClearSpan", unit: "U01", mode: "end" } });
    expect(store.get().revision).toBe(5);
    expect(store.get().message).toEqual({ text: expect.stringContaining("your choice, in place of the engine's default. The drawing is as it was."), kind: "ok" });
    await vi.waitFor(() => expect(store.get().param?.info?.growth?.[0].intent?.source).toBe("person")); // the value is read again: the row shows who decided now
  });

  it("at a value already stepped the drawing follows the chosen side, and the banner says so", async () => {
    routed({ "/api/sheet/anchor": { ok: true, result: { plan: "P1" }, delta: [L(0, 3)], summary: { ...SUMMARY, revision: 5 } }, "/api/sheet/param": PARAM });
    await chooseGrowth("U01.ClearSpan", "U01", "start");
    expect(store.get().message?.text).toContain("The drawing follows it at the value it has now.");
    expect(store.get().prims.find((p) => p.i === 0)?.p?.[0]).toBe(3);
  });

  it("a refusal is said in the banner and nothing changes", async () => {
    routed({ "/api/sheet/anchor": { ok: false, error: "the plan does not hold: the right wall would cross the embankment" } });
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await chooseGrowth("U01.ClearSpan", "U01", "centre");
    expect(store.get().message).toEqual({ text: expect.stringContaining("does not hold"), kind: "bad" });
    expect(store.get().revision).toBe(4);
    quiet.mockRestore();
  });

  it("working it out again says what changed and how many directions rest on convention or could not be decided", async () => {
    const asked = routed({
      "/api/sheet/intent": { ok: true, result: { U01: { changed: true, axes: [{ status: "decided" }, { status: "provisional" }] }, U02: { changed: false, axes: [{ status: "undecided" }] } }, delta: [], summary: { ...SUMMARY, revision: 7 } },
      "/api/sheet/unit": UNIT,
    });
    await deriveIntent();
    expect(asked[0]).toEqual({ path: "/api/sheet/intent", body: {} });
    expect(store.get().revision).toBe(7);
    expect(store.get().message?.text).toContain("2 unit(s), 1 changed");
    expect(store.get().message?.text).toContain("2 direction(s) rest on convention or could not be decided");
    await deriveIntent("U01");
    expect(asked.filter((a) => a.path === "/api/sheet/intent")[1].body).toEqual({ unit: "U01" });
  });
});

describe("settling a direction the engine could not decide", () => {
  const OPTIONS = { unit: "U01", name: "U01.TopSlab", local: "TopSlab", revision: 4, axis: "y", assembly: "y3", status: "undecided", evidence: ["no side could stay"], blocked: [], drivers: ["TopSlab"],
    choices: [{ id: "level:BedLevel", title: "Let BedLevel follow the structure", kinds: ["level"], edits: [{ kind: "level", target: "BedLevel", lines: ["y4"] }], policy: "end_fixed", centre: null,
      status: "decided", stays: "the top side stays", evidence: [], driver: "TopSlab", moves: ["TopSlab grows toward the bottom"], left_out: [], stops_being_input: ["BedLevel"],
      become_inputs: ["ClearHeight"], collateral: [], asked_in_growth: true, discards: [] }],
    rejected: [{ id: "reading:TopSlab", why: "it does not settle it" }], notes: [] };
  function routed(routes: Record<string, unknown>) {
    const asked: { path: string; method?: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).split("?")[0];
      asked.push({ path, method: init?.method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      if (!(path in routes)) return new Response(JSON.stringify({ ok: false, error: `no route ${path}` }), { status: 404, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify(routes[path]), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    return asked;
  }
  beforeEach(() => store.set({ summary: SUMMARY, prims: [L(0, 0)], styles: [], revision: 4, unit: null, param: null, ways: null, highlight: null, message: null, busy: null }));
  afterEach(() => vi.unstubAllGlobals());

  it("asks the engine for the ways, changing nothing, and keeps them for the value that asked", async () => {
    const asked = routed({ "/api/sheet/settle": OPTIONS });
    await showWays("U01.TopSlab", "U01");
    expect(asked[0].method).toBe("GET");
    expect(store.get().ways).toEqual({ key: "U01.TopSlab", unit: "U01", loading: false, options: OPTIONS });
    expect(store.get().revision).toBe(4);
    hideWays();
    expect(store.get().ways).toBeNull();
  });

  it("choosing one asks for it by id, takes the new revision, says it is the person's choice and closes the list", async () => {
    const asked = routed({ "/api/sheet/settle": { ok: true, result: { title: "Let BedLevel follow the structure", intent: { evidence: ["only the top side can stay"] } }, delta: [], summary: { ...SUMMARY, revision: 5 } },
      "/api/sheet/unit": { id: "U01", views: [], params: [], findings: [], components: [] }, "/api/sheet/param": { impact: {}, range: {}, highlight: {}, growth: [] } });
    store.set({ ways: { key: "U01.TopSlab", unit: "U01", loading: false, options: OPTIONS } });
    await settleGrowth("U01.TopSlab", "U01", "level:BedLevel");
    expect(asked[0]).toEqual({ path: "/api/sheet/settle", method: "POST", body: { name: "U01.TopSlab", unit: "U01", choice: "level:BedLevel" } });
    expect(store.get().revision).toBe(5);
    expect(store.get().ways).toBeNull();
    expect(store.get().message).toEqual({ text: expect.stringContaining("your choice"), kind: "ok" });
  });

  it("confirms a discarded value only when asked to, and a refusal changes nothing", async () => {
    const asked = routed({ "/api/sheet/settle": { ok: false, error: "it would discard the value you set for BedLevel" } });
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await settleGrowth("U01.TopSlab", "U01", "level:BedLevel", true);
    expect((asked[0].body as Record<string, unknown>).discard_values).toBe(true);
    expect(store.get().message).toEqual({ text: expect.stringContaining("discard"), kind: "bad" });
    expect(store.get().revision).toBe(4);
    quiet.mockRestore();
  });

  it("taking a choice back asks the engine and reads the unit again", async () => {
    const asked = routed({ "/api/sheet/unsettle": { ok: true, result: {}, delta: [], summary: { ...SUMMARY, revision: 6 } }, "/api/sheet/unit": { id: "U01", views: [], params: [], findings: [], components: [] } });
    await takeBackChoice("U01", "level:BedLevel");
    expect(asked[0]).toEqual({ path: "/api/sheet/unsettle", method: "POST", body: { unit: "U01", choice: "level:BedLevel" } });
    expect(store.get().revision).toBe(6);
  });
});

describe("reading a drawing, and starting it over clean", () => {
  function routed(routes: Record<string, (() => unknown) | unknown>) {
    const asked: { path: string; method?: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).split("?")[0];
      asked.push({ path, method: init?.method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      if (!(path in routes)) return new Response(JSON.stringify({ ok: false, error: `no route ${path}` }), { status: 404, headers: { "Content-Type": "application/json" } });
      const r = routes[path];
      return new Response(JSON.stringify(typeof r === "function" ? await (r as () => unknown)() : r), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    return asked;
  }
  beforeEach(() => store.set({ summary: SUMMARY, prims: [L(0, 0)], styles: [], revision: 4, unit: null, param: null, message: null, busy: null }));
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("asks the engine what it is reading while the read is out, and says it in the banner", async () => {
    vi.useFakeTimers();
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => { release = r; });
    const asked = routed({
      "/api/sheet/open": async () => { await held; return SUMMARY; },
      "/api/sheet/loading": { loading: true, name: "20A.dxf", elapsed_s: 12.4 },
      "/api/sheet": SUMMARY,
      "/api/sheet/geometry": { prims: [], styles: [], frame: [0, 0, 1, 1] },
      "/api/sheet/statuses": { entities: {}, counts: {} },
    });
    const file = { name: "20A.dxf", arrayBuffer: async () => new ArrayBuffer(4) } as unknown as File;
    const reading = openFile(file);
    await vi.advanceTimersByTimeAsync(1100);
    expect(asked.some((a) => a.path === "/api/sheet/loading")).toBe(true);
    expect(store.get().busy).toBe("Reading 20A.dxf… 12 s");
    release();
    await vi.advanceTimersByTimeAsync(10);
    await reading.catch(() => undefined);
  });

  it("starting clean asks the engine for the drawing as drawn, forgets what was selected, and says the saved work is kept aside", async () => {
    const asked = routed({
      "/api/sheet/reopen": SUMMARY,
      "/api/sheet": SUMMARY,
      "/api/sheet/geometry": { prims: [], styles: [], frame: [0, 0, 1, 1] },
      "/api/sheet/statuses": { entities: {}, counts: {} },
    });
    store.set({ selection: new Set([3]), param: { key: "U1.X", info: undefined as never } });
    await startClean();
    expect(asked[0]).toEqual({ path: "/api/sheet/reopen", method: "POST", body: { fresh: true } });
    expect(store.get().selection.size).toBe(0);
    expect(store.get().param).toBeNull();
    expect(store.get().message).toEqual({ text: expect.stringContaining("kept aside under a dated name"), kind: "ok" });
  });

  it("a refusal (the agent is working) is said and nothing is forgotten", async () => {
    routed({ "/api/sheet/reopen": { ok: false, error: "the agent is working on this sheet: stop it first" } });
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    store.set({ selection: new Set([3]) });
    await startClean();
    expect(store.get().message).toEqual({ text: expect.stringContaining("the agent is working"), kind: "bad" });
    expect(store.get().selection.size).toBe(1);
    quiet.mockRestore();
  });
});
