import { describe, expect, it } from "vitest";
import type { Prim } from "../src/api/types";
import { DEFAULT_OVERLAYS, firstBaseline, type RenderInput, visibleFilter } from "../src/canvas/renderer";
import { GridIndex } from "../src/canvas/spatial";
import { LIGHT } from "../src/canvas/styles";

function input(patch: Partial<RenderInput> = {}): RenderInput {
  return {
    prims: [], styles: [], index: new GridIndex([]), cam: { cx: 0, cy: 0, s: 1, rot: 0 }, W: 100, H: 100, theme: LIGHT,
    hiddenLayers: new Set(), hiddenStatus: new Set(), statusOf: null, overlays: { ...DEFAULT_OVERLAYS }, selection: new Set(), hover: null,
    highlight: null, preview: null, issues: new Set(), focusView: null, ...patch,
  };
}

const P = (patch: Partial<Prim>): Prim => ({ i: 1, k: "p", r: "structural", l: "0", v: "V1", p: [0, 0, 1, 1], ...patch });

describe("what is shown", () => {
  it("hidden layers are hidden", () => {
    const f = visibleFilter(input({ hiddenLayers: new Set(["DIM"]) }));
    expect(f(P({ l: "DIM" }))).toBe(false);
    expect(f(P({ l: "0" }))).toBe(true);
  });

  it("an existing / proposed class can be hidden; unknown entities count as unclassified", () => {
    const f = visibleFilter(input({ statusOf: { "1": "proposed" }, hiddenStatus: new Set(["proposed", "unclassified"]) }));
    expect(f(P({ i: 1 }))).toBe(false);
    expect(f(P({ i: 2 }))).toBe(false);
    const g = visibleFilter(input({ statusOf: { "1": "proposed" }, hiddenStatus: new Set(["existing"]) }));
    expect(g(P({ i: 1 }))).toBe(true);
  });

  it("overlay switches: dimensions, texts, hatch patterns, construction lines", () => {
    const f = visibleFilter(input({ overlays: { ...DEFAULT_OVERLAYS, dims: false, text: false, hatch: false, construction: false } }));
    expect(f(P({ d: 1 }))).toBe(false);
    expect(f(P({ k: "t", t: "NOTE", at: [0, 0] }))).toBe(false);
    expect(f(P({ k: "m", m: [0, 0, 1, 1] }))).toBe(false);
    expect(f(P({ r: "reference" }))).toBe(false);
    expect(f(P({}))).toBe(true);
  });
});

describe("text baselines", () => {
  it("hang multi-line text as CAD hangs it", () => {
    expect(firstBaseline(undefined, 3)).toBe(0);
    expect(firstBaseline("t", 1)).toBe(-1);
    expect(firstBaseline("m", 1)).toBeCloseTo(-0.5);
    expect(firstBaseline("bt", 2)).toBeCloseTo(1.667 + 0.2);
  });
});
