// A view opened in its own tab: its own entities only, its coordinates said in its own frame (real mm from its own origin, RL where it states a
// level) — and the sheet untouched: a point goes to the sheet and back exactly.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LocalFrame, Prim, Summary } from "../src/api/types";
import { levelAt, sayLocal, toLocal, toSheet } from "../src/canvas/frames";
import { visibleFilter, DEFAULT_OVERLAYS } from "../src/canvas/renderer";
import { openView, store } from "../src/state/workspace";

const F: LocalFrame = { view: "V02", mm_per_unit: 0.5, origin: [52681, 124255.5], x_from: "the view's left-most structural line", y_from: "the level RoadLevel",
  level: { name: "RoadLevel", rl_m: 608.051, at_y: 124255.5 } };

describe("a view's own frame", () => {
  it("says a point in real mm from the view's origin, and its level", () => {
    expect(toLocal(F, 52681 + 600, 124255.5 - 300)).toEqual([300, -150]);
    expect(levelAt(F, 124255.5 + 2000)).toBeCloseTo(609.051, 9); // 2000 units at 0.5 mm each: a metre up
    expect(sayLocal(F, 52681 + 600, 124255.5 - 300)).toBe("x 300 · y -150 mm · RL 607.901");
  });
  it("goes back to the sheet exactly", () => {
    for (const [x, y] of [[52681, 124255.5], [61000.25, 120000.125], [-5, 7]]) {
      const [lx, ly] = toLocal(F, x, y);
      const [bx, by] = toSheet(F, lx, ly);
      expect(bx).toBeCloseTo(x, 9);
      expect(by).toBeCloseTo(y, 9);
    }
  });
  it("has no level where the view states none", () => {
    expect(levelAt({ ...F, level: null }, 0)).toBeNull();
    expect(sayLocal({ ...F, level: null }, 52681, 124255.5)).toBe("x 0 · y 0 mm");
  });
});

describe("a view in its own tab", () => {
  const P = (i: number, v: string): Prim => ({ i, k: "p", r: "structural", l: "0", v, p: [0, 0, 1, 1] });
  afterEach(() => vi.unstubAllGlobals());
  it("draws and picks only that view's entities, and the sheet again when closed", () => {
    const groups = [{ id: "V01", kind: "view", name: "SECTION", view_type: "section", bbox: [0, 0, 10, 10], entities: 1 },
                    { id: "V02", kind: "view", name: "DETAIL", view_type: "detail", bbox: [20, 0, 30, 10], entities: 1, local: F }];
    store.set({ summary: { groups } as unknown as Summary, W: 800, H: 600 });
    openView("V02");
    expect(store.get().viewTab).toBe("V02");
    expect(store.get().focusView).toBe("V02");
    const inp = { hiddenLayers: new Set<string>(), hiddenStatus: new Set<string>(), statusOf: null, overlays: { ...DEFAULT_OVERLAYS }, focusView: "V02", isolate: true };
    const ok = visibleFilter(inp as never);
    expect(ok(P(1, "V02"))).toBe(true);
    expect(ok(P(2, "V01"))).toBe(false);
    expect(visibleFilter({ ...inp, isolate: false } as never)(P(2, "V01"))).toBe(true); // a focused view on the sheet only dims the others
    openView(null);
    expect(store.get().viewTab).toBeNull();
    expect(store.get().focusView).toBeNull();
  });
});
