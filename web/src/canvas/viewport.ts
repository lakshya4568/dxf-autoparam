// The camera: one stable transform between drawing units and canvas pixels. It changes only when the person pans, zooms
// or asks to fit something — never because the geometry was regenerated.
import type { Box, XY } from "../api/types";

export interface Camera {
  cx: number; // world point at the canvas centre
  cy: number;
  s: number; // canvas pixels per drawing unit
  rot: number; // view rotation, radians (counter-clockwise)
}

export const DEFAULT_CAMERA: Camera = { cx: 0, cy: 0, s: 1, rot: 0 };

export function toScreen(cam: Camera, W: number, H: number, x: number, y: number): XY {
  const c = Math.cos(cam.rot), n = Math.sin(cam.rot);
  const dx = x - cam.cx, dy = y - cam.cy;
  return [W / 2 + cam.s * (c * dx - n * dy), H / 2 - cam.s * (n * dx + c * dy)];
}

export function toWorld(cam: Camera, W: number, H: number, sx: number, sy: number): XY {
  const c = Math.cos(cam.rot), n = Math.sin(cam.rot);
  const u = (sx - W / 2) / cam.s, v = -(sy - H / 2) / cam.s;
  return [cam.cx + c * u + n * v, cam.cy - n * u + c * v];
}

/** The camera that shows `box` whole, with a margin (a fraction of the box), at the current rotation. */
export function fitBox(box: Box, W: number, H: number, pad = 0.06, rot = 0): Camera {
  const w = Math.max(box[2] - box[0], 1e-9), h = Math.max(box[3] - box[1], 1e-9);
  const c = Math.abs(Math.cos(rot)), n = Math.abs(Math.sin(rot));
  const bw = w * c + h * n, bh = w * n + h * c; // the rotated box's extents
  const s = Math.min(W / (bw * (1 + 2 * pad)), H / (bh * (1 + 2 * pad)));
  return { cx: (box[0] + box[2]) / 2, cy: (box[1] + box[3]) / 2, s: Math.max(s, 1e-9), rot };
}

/** Zoom by `factor` keeping the world point under the cursor where it is on screen. */
export function zoomAt(cam: Camera, W: number, H: number, sx: number, sy: number, factor: number, minS = 1e-7, maxS = 1e5): Camera {
  const [wx, wy] = toWorld(cam, W, H, sx, sy);
  const s = Math.min(maxS, Math.max(minS, cam.s * factor));
  const moved = { ...cam, s };
  const [ax, ay] = toWorld(moved, W, H, sx, sy);
  return { ...moved, cx: cam.cx + (wx - ax), cy: cam.cy + (wy - ay) };
}

/** Pan by a drag of (dx, dy) pixels: the drawing follows the cursor. */
export function panBy(cam: Camera, dxPx: number, dyPx: number): Camera {
  const c = Math.cos(cam.rot), n = Math.sin(cam.rot);
  const u = -dxPx / cam.s, v = dyPx / cam.s;
  return { ...cam, cx: cam.cx + c * u + n * v, cy: cam.cy - n * u + c * v };
}

/** The world box the canvas shows (axis-aligned, enclosing a rotated view). */
export function visibleBox(cam: Camera, W: number, H: number): Box {
  const pts = [toWorld(cam, W, H, 0, 0), toWorld(cam, W, H, W, 0), toWorld(cam, W, H, 0, H), toWorld(cam, W, H, W, H)];
  return [Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[1]))];
}

export function sameCamera(a: Camera, b: Camera, eps = 1e-9): boolean {
  return Math.abs(a.cx - b.cx) <= eps * Math.max(1, Math.abs(a.cx)) && Math.abs(a.cy - b.cy) <= eps * Math.max(1, Math.abs(a.cy))
    && Math.abs(a.s - b.s) <= eps * Math.max(1, a.s) && Math.abs(a.rot - b.rot) <= eps;
}

/** "Back to the previous view": cameras the person was at before a fit or a zoom-to (consecutive duplicates collapse). */
export class ViewHistory {
  private stack: Camera[] = [];
  constructor(private readonly limit = 50) {}

  push(cam: Camera): void {
    const last = this.stack[this.stack.length - 1];
    if (last && sameCamera(last, cam)) return;
    this.stack.push({ ...cam });
    if (this.stack.length > this.limit) this.stack.shift();
  }

  back(): Camera | null {
    return this.stack.pop() ?? null;
  }

  get size(): number {
    return this.stack.length;
  }
}

/** Grow a box by a fraction of its size (at least `min` drawing units). */
export function padBox(b: Box, frac: number, min = 0): Box {
  const dx = Math.max((b[2] - b[0]) * frac, min), dy = Math.max((b[3] - b[1]) * frac, min);
  return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy];
}

/** The box enclosing every finite box (a loop, not Math.min(...): a large sheet has more boxes than a call takes arguments). */
export function unionBox(boxes: Box[]): Box | null {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const b of boxes) {
    if (!isFinite(b[0]) || !isFinite(b[1]) || !isFinite(b[2]) || !isFinite(b[3])) continue;
    if (b[0] < x0) x0 = b[0];
    if (b[1] < y0) y0 = b[1];
    if (b[2] > x1) x1 = b[2];
    if (b[3] > y1) y1 = b[3];
  }
  return x0 <= x1 && y0 <= y1 ? [x0, y0, x1, y1] : null;
}
