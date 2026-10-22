import { describe, expect, it } from "vitest";
import type { Box } from "../src/api/types";
import { fitBox, keepOnScreen, padBox, panBy, toScreen, toWorld, unionBox, ViewHistory, visibleBox, zoomAt } from "../src/canvas/viewport";

const W = 1000, H = 600;

describe("camera", () => {
  it("screen and world are inverse, rotated or not", () => {
    for (const rot of [0, 0.3, Math.PI / 2, -1.1]) {
      const cam = { cx: 1234.5, cy: -77, s: 0.37, rot };
      const [sx, sy] = toScreen(cam, W, H, 1500, 20);
      const [x, y] = toWorld(cam, W, H, sx, sy);
      expect(x).toBeCloseTo(1500, 6);
      expect(y).toBeCloseTo(20, 6);
    }
  });

  it("y is up in the drawing and down on screen", () => {
    const cam = { cx: 0, cy: 0, s: 1, rot: 0 };
    expect(toScreen(cam, W, H, 0, 10)[1]).toBeLessThan(toScreen(cam, W, H, 0, 0)[1]);
  });

  it("fitBox shows the whole box with its margin", () => {
    const box: Box = [100, 200, 5100, 1200];
    const cam = fitBox(box, W, H, 0.06);
    const vb = visibleBox(cam, W, H);
    expect(vb[0]).toBeLessThanOrEqual(100);
    expect(vb[2]).toBeGreaterThanOrEqual(5100);
    expect(vb[1]).toBeLessThanOrEqual(200);
    expect(vb[3]).toBeGreaterThanOrEqual(1200);
    expect(cam.cx).toBe(2600);
  });

  it("zoomAt keeps the world point under the cursor where it is", () => {
    const cam = { cx: 50, cy: 50, s: 2, rot: 0.2 };
    const before = toWorld(cam, W, H, 700, 120);
    const z = zoomAt(cam, W, H, 700, 120, 1.8);
    const after = toWorld(z, W, H, 700, 120);
    expect(z.s).toBeCloseTo(3.6);
    expect(after[0]).toBeCloseTo(before[0], 6);
    expect(after[1]).toBeCloseTo(before[1], 6);
  });

  it("panBy moves the drawing with the cursor", () => {
    const cam = { cx: 0, cy: 0, s: 2, rot: 0 };
    const p0 = toScreen(cam, W, H, 10, 10);
    const moved = panBy(cam, 40, -30);
    const p1 = toScreen(moved, W, H, 10, 10);
    expect(p1[0] - p0[0]).toBeCloseTo(40);
    expect(p1[1] - p0[1]).toBeCloseTo(-30);
  });
});

describe("view history", () => {
  it("returns earlier cameras, collapsing consecutive duplicates", () => {
    const h = new ViewHistory(3);
    const a = { cx: 0, cy: 0, s: 1, rot: 0 }, b = { cx: 5, cy: 0, s: 1, rot: 0 };
    h.push(a);
    h.push({ ...a });
    h.push(b);
    expect(h.size).toBe(2);
    expect(h.back()).toEqual(b);
    expect(h.back()).toEqual(a);
    expect(h.back()).toBeNull();
  });

  it("keeps at most its limit", () => {
    const h = new ViewHistory(3);
    for (let k = 0; k < 10; k++) h.push({ cx: k, cy: 0, s: 1, rot: 0 });
    expect(h.size).toBe(3);
    expect(h.back()?.cx).toBe(9);
  });
});

describe("boxes", () => {
  it("unionBox handles more boxes than a call takes arguments, skipping non-finite ones", () => {
    const boxes: Box[] = [];
    for (let k = 0; k < 300_000; k++) boxes.push([k, -k, k + 1, -k + 1]);
    boxes.push([NaN, 0, 1, 1]);
    expect(unionBox(boxes)).toEqual([0, -299_999, 300_000, 1]);
    expect(unionBox([])).toBeNull();
  });

  it("padBox grows by a fraction, at least the minimum", () => {
    expect(padBox([0, 0, 10, 0], 0.1, 2)).toEqual([-2, -2, 12, 2]);
  });
});

describe("a panel opening beside the drawing", () => {
  // The inspector opening on a selection (or the agent) narrows the canvas: the drawing must not slide — every world point stays where it was IN
  // THE WINDOW (the camera keeps the world point at the canvas centre, and the centre itself moved).
  const windowX = (cam: ReturnType<typeof fitBox>, c: { left: number; top: number; W: number; H: number }, x: number, y: number) => {
    const [sx, sy] = toScreen(cam, c.W, c.H, x, y);
    return [c.left + sx, c.top + sy];
  };
  for (const rot of [0, 0.4]) {
    it(`keeps every point where it was on the screen (rotation ${rot})`, () => {
      const before = { left: 300, top: 40, W: 1200, H: 800 };
      const cam = { cx: 5000, cy: 2000, s: 0.08, rot };
      for (const after of [{ left: 300, top: 40, W: 820, H: 800 }, { left: 0, top: 40, W: 1500, H: 800 }, { left: 300, top: 90, W: 1200, H: 700 }]) {
        const moved = keepOnScreen(cam, before, after);
        expect(moved.s).toBe(cam.s);
        for (const [x, y] of [[5000, 2000], [0, 0], [9000, -3000]]) {
          const [a, b] = windowX(cam, before, x, y);
          const [c, d] = windowX(moved, after, x, y);
          expect(c).toBeCloseTo(a, 6);
          expect(d).toBeCloseTo(b, 6);
        }
      }
      expect(keepOnScreen(cam, before, { ...before })).toBe(cam);
    });
  }
});
