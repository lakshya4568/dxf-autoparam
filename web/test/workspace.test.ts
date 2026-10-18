// The workspace state: an edit, a preview, an undo replace the engine's primitives for the entities that changed and never
// move the camera. fetch is faked: these tests exercise the state, not the server (that is web/e2e and tests/test_web_contract.py).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeltaResult, Prim, Summary } from "../src/api/types";
import { applyChange, cancelPreview, focusParam, keepUnnamedAsDrawn, liveChange, mergeDelta, previewChange, releaseKept, rowEntities, setOverlay, store, undo, unlockHeldPart } from "../src/state/workspace";

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
    f.release[0]({ ok: true, delta: [L(1, 55)], summary: { ...SUMMARY, revision: 5 } });
    expect(await p).toEqual({ ok: true });
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

  it("the original is not fetched, and not shown, while editing — only when switched on", async () => {
    const f = gated();
    const p = liveChange({ "U1.Width": 1200 });
    f.release[0]({ ok: true, delta: [L(1, 55)], summary: { ...SUMMARY, revision: 5 } });
    await p;
    expect(f.sent.map((x) => x.path)).toEqual(["/api/sheet/apply"]); // no request for the original
    expect(store.get().original).toBeNull();
    expect(store.get().overlays.original).toBe(false);
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
