// The workspace state: an edit, a preview, an undo replace the engine's primitives for the entities that changed and never
// move the camera. fetch is faked: these tests exercise the state, not the server (that is web/e2e and tests/test_web_contract.py).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeltaResult, Prim, Summary } from "../src/api/types";
import { applyChange, cancelPreview, mergeDelta, previewChange, rowEntities, store, undo } from "../src/state/workspace";

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

describe("behaviour rows", () => {
  it("name an annotation's entity or a component's entities", () => {
    expect(rowEntities({ entity: 7 })).toEqual([7]);
    expect(rowEntities({ entities: [1, 2, "x"] })).toEqual([1, 2]);
    expect(rowEntities({ value: "Width" })).toEqual([]);
  });
});
