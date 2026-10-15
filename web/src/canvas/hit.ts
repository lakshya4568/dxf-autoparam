// What a click means: the primitive nearest the cursor (within a few pixels), measured on the primitive's own geometry —
// a line by its distance, a fill by being inside it, a text by its box. The answer is the ENTITY it draws (prim.i), which the
// inspector then asks the engine about: the canvas never keeps a geometry model of its own.
import type { Prim } from "../api/types";
import { textCorners } from "./spatial";

export function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay;
  const L2 = dx * dx + dy * dy;
  const t = L2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export function distToPolyline(a: number[], closed: boolean, x: number, y: number): number {
  let d = Infinity;
  const n = a.length;
  for (let k = 0; k + 3 < n; k += 2) d = Math.min(d, distToSegment(x, y, a[k], a[k + 1], a[k + 2], a[k + 3]));
  if (closed && n >= 4) d = Math.min(d, distToSegment(x, y, a[n - 2], a[n - 1], a[0], a[1]));
  if (n === 2) d = Math.hypot(x - a[0], y - a[1]);
  return d;
}

export function distToSegments(m: number[], x: number, y: number): number {
  let d = Infinity;
  for (let k = 0; k + 3 < m.length; k += 4) d = Math.min(d, distToSegment(x, y, m[k], m[k + 1], m[k + 2], m[k + 3]));
  return d;
}

export function pointInPoly(a: number[], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = a.length - 2; i < a.length; j = i, i += 2) {
    const xi = a[i], yi = a[i + 1], xj = a[j], yj = a[j + 1];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-30) + xi) inside = !inside;
  }
  return inside;
}

/** Distance from (x, y) to what the primitive draws (0 inside a fill or a text box). */
export function distance(p: Prim, x: number, y: number): number {
  if (p.k === "t") {
    const c = textCorners(p);
    const flat = c.flat();
    return pointInPoly(flat, x, y) ? 0 : distToPolyline(flat, true, x, y);
  }
  if (p.k === "m") return p.m ? distToSegments(p.m, x, y) : Infinity;
  if (!p.p) return Infinity;
  if (p.k === "g") return pointInPoly(p.p, x, y) ? 0 : distToPolyline(p.p, true, x, y);
  return distToPolyline(p.p, !!p.c, x, y);
}

/**
 * The nearest primitive to (x, y) within `tol` (drawing units) among `candidates` (indices into prims). Strokes win over fills
 * and texts at equal distance (a line on a hatch boundary is what a draftsman means). `accept` filters (hidden layers …).
 */
export function pick(prims: Prim[], candidates: number[], x: number, y: number, tol: number, accept: (p: Prim) => boolean = () => true): number | null {
  let best: number | null = null;
  let bestD = Infinity;
  for (const n of candidates) {
    const p = prims[n];
    if (!accept(p)) continue;
    let d = distance(p, x, y);
    if (p.k === "g" || (p.k === "t" && d === 0)) d += tol * 0.5; // a fill / a text box is a weaker hit than a line through the point
    if (p.fill === "pattern") d += tol * 0.25;
    if (d <= tol && d < bestD) {
      bestD = d;
      best = n;
    }
  }
  return best;
}
