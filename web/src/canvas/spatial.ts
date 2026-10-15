// Where every primitive is: boxes and a uniform grid, so a frame draws (and a click tests) only what is on screen.
import type { Box, Prim } from "../api/types";
import { unionBox } from "./viewport";

const TEXT_W = 0.62; // average glyph width per unit of text height (the engine estimates text footprints the same way)

/** A text's footprint as the four corners of its rotated box, hung from its anchor as CAD hangs it. */
export function textCorners(p: Prim): [number, number][] {
  const h = p.h || 1;
  const lines = String(p.t ?? "").split("\n");
  const n = lines.length;
  let w = TEXT_W * h * Math.max(1, ...lines.map((s) => s.length)) * (p.wf || 1);
  if (p.width && p.width > 0) w = Math.min(w, p.width);
  const H = h + (n - 1) * h * 1.667 * (p.ls || 1);
  const x0 = p.ha === "c" ? -w / 2 : p.ha === "r" ? -w : 0;
  let y0: number, y1: number;
  if (p.va === "t") [y0, y1] = [-H, 0];
  else if (p.va === "m") [y0, y1] = [-H / 2, H / 2];
  else if (p.va === "bt") [y0, y1] = [0, H];
  else [y0, y1] = [-(n - 1) * h * 1.667 * (p.ls || 1) - 0.2 * h, 1.1 * h];
  const a = ((p.rot || 0) * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  const [ox, oy] = p.at ?? [0, 0];
  return ([[x0, y0], [x0 + w, y0], [x0 + w, y1], [x0, y1]] as [number, number][]).map(([x, y]) => [ox + x * c - y * s, oy + x * s + y * c]);
}

export function primBox(p: Prim): Box {
  if (p.k === "t") {
    const c = textCorners(p);
    return [Math.min(...c.map((q) => q[0])), Math.min(...c.map((q) => q[1])), Math.max(...c.map((q) => q[0])), Math.max(...c.map((q) => q[1]))];
  }
  const a = p.k === "m" ? p.m : p.p;
  if (!a || a.length < 2) return [0, 0, 0, 0];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let k = 0; k + 1 < a.length; k += 2) {
    const x = a[k], y = a[k + 1];
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  return [x0, y0, x1, y1];
}

/** A uniform grid over the drawing's extent. Primitives bigger than many cells (a frame, a long axis) live in `big`. */
export class GridIndex {
  private cells = new Map<number, number[]>();
  private big: number[] = [];
  private x0 = 0;
  private y0 = 0;
  private cell = 1;
  private nx = 1;
  private ny = 1;
  readonly boxes: Box[];

  constructor(prims: Prim[], extent?: Box) {
    this.boxes = prims.map(primBox);
    const ext = extent && extent[2] > extent[0] ? extent : (unionBox(this.boxes.filter((b) => b[2] >= b[0])) ?? ([0, 0, 1, 1] as Box));
    const W = Math.max(ext[2] - ext[0], 1e-9), H = Math.max(ext[3] - ext[1], 1e-9);
    this.cell = Math.max(W, H) / 256;
    this.x0 = ext[0];
    this.y0 = ext[1];
    this.nx = Math.ceil(W / this.cell) + 1;
    this.ny = Math.ceil(H / this.cell) + 1;
    this.boxes.forEach((b, n) => this.insert(n, b));
  }

  private insert(n: number, b: Box): void {
    if (!isFinite(b[0])) return;
    const c0 = Math.floor((b[0] - this.x0) / this.cell), c1 = Math.floor((b[2] - this.x0) / this.cell);
    const r0 = Math.floor((b[1] - this.y0) / this.cell), r1 = Math.floor((b[3] - this.y0) / this.cell);
    if ((c1 - c0 + 1) * (r1 - r0 + 1) > 400 || c1 < 0 || r1 < 0 || c0 >= this.nx || r0 >= this.ny) {
      this.big.push(n);
      return;
    }
    for (let r = Math.max(0, r0); r <= Math.min(this.ny - 1, r1); r++)
      for (let c = Math.max(0, c0); c <= Math.min(this.nx - 1, c1); c++) {
        const key = r * this.nx + c;
        let a = this.cells.get(key);
        if (!a) this.cells.set(key, (a = []));
        a.push(n);
      }
  }

  /** Primitive indices whose boxes meet `box`, each once, in drawing order. */
  query(box: Box): number[] {
    const seen = new Set<number>(this.big.filter((n) => intersects(this.boxes[n], box)));
    const c0 = Math.max(0, Math.floor((box[0] - this.x0) / this.cell)), c1 = Math.min(this.nx - 1, Math.floor((box[2] - this.x0) / this.cell));
    const r0 = Math.max(0, Math.floor((box[1] - this.y0) / this.cell)), r1 = Math.min(this.ny - 1, Math.floor((box[3] - this.y0) / this.cell));
    for (let r = r0; r <= r1; r++)
      for (let c = c0; c <= c1; c++) {
        const a = this.cells.get(r * this.nx + c);
        if (a) for (const n of a) if (!seen.has(n) && intersects(this.boxes[n], box)) seen.add(n);
      }
    return [...seen].sort((a, b) => a - b);
  }
}

export function intersects(a: Box, b: Box): boolean {
  return !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);
}
