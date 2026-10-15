import { describe, expect, it } from "vitest";
import type { Prim } from "../src/api/types";
import { distance, distToSegment, pick, pointInPoly } from "../src/canvas/hit";

const line = (i: number, p: number[], extra: Partial<Prim> = {}): Prim => ({ i, k: "p", r: "structural", l: "0", v: "V1", p, ...extra });

describe("distances", () => {
  it("to a segment, clamped at its ends", () => {
    expect(distToSegment(5, 3, 0, 0, 10, 0)).toBeCloseTo(3);
    expect(distToSegment(13, 4, 0, 0, 10, 0)).toBeCloseTo(5);
  });

  it("inside a polygon", () => {
    const sq = [0, 0, 10, 0, 10, 10, 0, 10];
    expect(pointInPoly(sq, 5, 5)).toBe(true);
    expect(pointInPoly(sq, 15, 5)).toBe(false);
  });

  it("a text is hit inside its box", () => {
    const t: Prim = { i: 1, k: "t", r: "annotation", l: "TXT", v: "V1", at: [0, 0], t: "TOP OF SLAB", h: 2.5 };
    expect(distance(t, 5, 1)).toBe(0);
    expect(distance(t, 5, 20)).toBeGreaterThan(10);
  });

  it("hatch pattern segments are measured segment by segment", () => {
    const m: Prim = { i: 2, k: "m", r: "annotation", l: "H", v: "V1", m: [0, 0, 10, 0, 0, 5, 10, 5] };
    expect(distance(m, 5, 4)).toBeCloseTo(1);
  });
});

describe("pick", () => {
  it("the nearest entity within tolerance, by its entity index", () => {
    const prims = [line(10, [0, 0, 100, 0]), line(11, [0, 3, 100, 3])];
    expect(pick(prims, [0, 1], 50, 2.2, 2)).toBe(1);
    expect(pick(prims, [0, 1], 50, 50, 2)).toBeNull();
  });

  it("a line through the point beats the fill it bounds", () => {
    const fill: Prim = { i: 20, k: "g", r: "annotation", l: "H", v: "V1", p: [0, 0, 10, 0, 10, 10, 0, 10] };
    const edge = line(21, [5, 0, 5, 10]);
    expect(pick([fill, edge], [0, 1], 5.1, 5, 1)).toBe(1);
  });

  it("respects the visibility filter", () => {
    const prims = [line(10, [0, 0, 100, 0], { l: "HIDDEN" }), line(11, [0, 1.5, 100, 1.5])];
    expect(pick(prims, [0, 1], 50, 0, 2, (p) => p.l !== "HIDDEN")).toBe(1);
  });
});
