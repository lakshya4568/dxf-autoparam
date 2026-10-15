import { describe, expect, it } from "vitest";
import type { Prim } from "../src/api/types";
import { GridIndex, primBox, textCorners } from "../src/canvas/spatial";

const line = (i: number, p: number[]): Prim => ({ i, k: "p", r: "structural", l: "0", v: "V1", p });

describe("text footprint", () => {
  it("hangs from its anchor as aligned", () => {
    const base: Prim = { i: 0, k: "t", r: "annotation", l: "T", v: "V1", at: [100, 100], t: "ABCD", h: 10 };
    const left = primBox(base);
    const centre = primBox({ ...base, ha: "c" });
    const right = primBox({ ...base, ha: "r" });
    expect(left[0]).toBeCloseTo(100);
    expect((centre[0] + centre[2]) / 2).toBeCloseTo(100);
    expect(right[2]).toBeCloseTo(100);
    const top = primBox({ ...base, va: "t" });
    expect(top[3]).toBeCloseTo(100);
  });

  it("turns with its rotation", () => {
    const c = textCorners({ i: 0, k: "t", r: "annotation", l: "T", v: "V1", at: [0, 0], t: "ABCDEFGH", h: 1, rot: 90 });
    const xs = c.map((q) => q[0]), ys = c.map((q) => q[1]);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan(Math.max(...xs) - Math.min(...xs));
  });

  it("an MTEXT column width caps the footprint", () => {
    const b = primBox({ i: 0, k: "t", r: "annotation", l: "T", v: "V1", at: [0, 0], t: "A VERY LONG NOTE THAT WRAPS", h: 1, width: 5 });
    expect(b[2] - b[0]).toBeCloseTo(5);
  });
});

describe("grid index", () => {
  it("returns what meets a box, each once, in drawing order", () => {
    const prims: Prim[] = [];
    for (let k = 0; k < 500; k++) prims.push(line(k, [k * 10, 0, k * 10 + 5, 5]));
    prims.push(line(999, [0, -1, 5000, -1])); // long: lives in the big list
    const g = new GridIndex(prims, [0, -1, 5000, 5]);
    const hits = g.query([100, 0, 130, 5]);
    expect(hits).toEqual([10, 11, 12, 13]);
    expect(g.query([2500, -2, 2501, 0])).toContain(500);
    const all = g.query([-10, -10, 6000, 10]);
    expect(new Set(all).size).toBe(all.length);
    expect(all.length).toBe(501);
  });

  it("works without an extent", () => {
    const g = new GridIndex([line(0, [0, 0, 1, 1]), line(1, [100, 100, 101, 101])]);
    expect(g.query([99, 99, 102, 102])).toEqual([1]);
  });
});
