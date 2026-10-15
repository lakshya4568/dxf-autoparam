// One frame of the drawing, in deliberate layers (bottom to top):
//   fills (solid hatches, arrowheads, wide polylines; a faint tint under pattern hatches when asked) → hatch pattern lines →
//   the drawing's lines in their own colour, lineweight and linetype → wipeouts → control overlays (what a value drives /
//   moves / holds — translucent, UNDER the text so they never hide a note) → texts → the proposal of a previewed change (the
//   original ghosted) → selection and hover → validation issues.
// Nothing here computes geometry: every point comes from the engine; this file only draws it.
import type { Prim, Style } from "../api/types";
import type { GridIndex } from "./spatial";
import { alphaOf, dashPx, fontFamily, lineWidthPx, strokeColor, strokeKey, type Theme } from "./styles";
import { type Camera, toScreen, visibleBox } from "./viewport";

export interface Overlays {
  dims: boolean;
  text: boolean;
  hatch: boolean;
  hatchTint: boolean;
  construction: boolean;
  drives: boolean;
  follows: boolean;
  holds: boolean;
  texts: boolean;
  issues: boolean;
}

export const DEFAULT_OVERLAYS: Overlays = {
  dims: true, text: true, hatch: true, hatchTint: false, construction: true, drives: true, follows: true, holds: true, texts: true, issues: true,
};

export interface HighlightSets {
  drives: Set<number>;
  follows: Set<number>;
  texts: Set<number>;
  holds: Set<number>;
}

export interface RenderInput {
  prims: Prim[];
  styles: Style[];
  index: GridIndex;
  cam: Camera;
  W: number;
  H: number;
  theme: Theme;
  hiddenLayers: Set<string>;
  hiddenStatus: Set<string>;
  statusOf: Record<string, string> | null;
  overlays: Overlays;
  selection: Set<number>;
  hover: number | null;
  highlight: HighlightSets | null;
  preview: { ents: Set<number>; prims: Prim[] } | null;
  issues: Set<number>;
  focusView: string | null;
}

export interface FrameStats {
  ms: number;
  drawn: number;
  texts: number;
}

const CAP = 0.72; // cap height per em of the canvas fonts: a CAD text height is a cap height

export function visibleFilter(inp: RenderInput): (p: Prim) => boolean {
  const { hiddenLayers, hiddenStatus, statusOf, overlays } = inp;
  return (p: Prim) => {
    if (hiddenLayers.has(p.l)) return false;
    if (statusOf && hiddenStatus.size && hiddenStatus.has(statusOf[String(p.i)] ?? "unclassified")) return false;
    if (p.k === "t" && !overlays.text && !p.d) return false;
    if (p.d && !overlays.dims) return false;
    if (p.k === "m" && !overlays.hatch) return false;
    if (p.r === "reference" && !overlays.construction) return false;
    return true;
  };
}

function path(ctx: CanvasRenderingContext2D, a: number[], closed: boolean, cam: Camera, W: number, H: number): void {
  const c = Math.cos(cam.rot), n = Math.sin(cam.rot), s = cam.s, cx = W / 2, cy = H / 2;
  const A = c * s, B = n * s;
  ctx.moveTo(cx + A * (a[0] - cam.cx) - B * (a[1] - cam.cy), cy - B * (a[0] - cam.cx) - A * (a[1] - cam.cy));
  for (let k = 2; k + 1 < a.length; k += 2) {
    const dx = a[k] - cam.cx, dy = a[k + 1] - cam.cy;
    ctx.lineTo(cx + A * dx - B * dy, cy - B * dx - A * dy);
  }
  if (closed) ctx.closePath();
}

function segments(ctx: CanvasRenderingContext2D, m: number[], cam: Camera, W: number, H: number): void {
  const c = Math.cos(cam.rot), n = Math.sin(cam.rot), s = cam.s, cx = W / 2, cy = H / 2;
  const A = c * s, B = n * s;
  for (let k = 0; k + 3 < m.length; k += 4) {
    const x0 = cx + A * (m[k] - cam.cx) - B * (m[k + 1] - cam.cy), y0 = cy - B * (m[k] - cam.cx) - A * (m[k + 1] - cam.cy);
    const x1 = cx + A * (m[k + 2] - cam.cx) - B * (m[k + 3] - cam.cy), y1 = cy - B * (m[k + 2] - cam.cx) - A * (m[k + 3] - cam.cy);
    if (Math.abs(x1 - x0) + Math.abs(y1 - y0) < 0.5) {
      ctx.rect(x0 - 0.5, y0 - 0.5, 1, 1); // a dot of the pattern
    } else {
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
    }
  }
}

/** Lines of a text, wrapped to an MTEXT's column width when it has one. */
export function textLines(p: Prim, ctx: CanvasRenderingContext2D | null, pxPerUnit: number): string[] {
  const raw = String(p.t ?? "").split("\n");
  if (!p.width || !ctx || p.width <= 0) return raw;
  const limit = p.width * pxPerUnit;
  const out: string[] = [];
  for (const line of raw) {
    const words = line.split(/\s+/);
    let cur = "";
    for (const w of words) {
      const next = cur ? `${cur} ${w}` : w;
      if (cur && ctx.measureText(next).width * (p.wf || 1) > limit * 1.02) {
        out.push(cur);
        cur = w;
      } else cur = next;
    }
    out.push(cur);
  }
  return out;
}

/** The first baseline's offset below the anchor, in text heights, for `n` lines hung as `va` says (y up, CAD's frame). */
export function firstBaseline(va: Prim["va"], n: number, ls = 1): number {
  const lh = 1.667 * ls;
  if (va === "t") return -1;
  if (va === "m") return (1 + (n - 1) * lh) / 2 - 1;
  if (va === "bt") return (n - 1) * lh + 0.2;
  return 0;
}

function drawText(ctx: CanvasRenderingContext2D, p: Prim, inp: RenderInput, color: string, family: string): boolean {
  const { cam, W, H } = inp;
  const h = p.h || 1;
  const hpx = h * cam.s;
  if (hpx < 2.5 || !p.at) return false;
  const fontPx = hpx / CAP;
  ctx.font = `${fontPx.toFixed(2)}px ${family}`;
  const lines = textLines(p, ctx, cam.s);
  const [sx, sy] = toScreen(cam, W, H, p.at[0], p.at[1]);
  const rot = ((p.rot || 0) * Math.PI) / 180 + cam.rot;
  ctx.save();
  ctx.translate(sx, sy);
  ctx.rotate(-rot);
  if (p.wf && Math.abs(p.wf - 1) > 1e-3) ctx.scale(p.wf, 1);
  if (p.oblique) ctx.transform(1, 0, -Math.tan((p.oblique * Math.PI) / 180), 1, 0, 0);
  ctx.fillStyle = color;
  ctx.textAlign = p.ha === "c" ? "center" : p.ha === "r" ? "right" : "left";
  ctx.textBaseline = "alphabetic";
  const lh = 1.667 * (p.ls || 1) * hpx;
  const b0 = firstBaseline(p.va, lines.length, p.ls || 1) * hpx;
  for (let k = 0; k < lines.length; k++) ctx.fillText(lines[k], 0, -b0 + k * lh);
  ctx.restore();
  return true;
}

export function render(ctx: CanvasRenderingContext2D, inp: RenderInput): FrameStats {
  const t0 = performance.now();
  const { prims, styles, index, cam, W, H, theme, overlays, preview } = inp;
  ctx.fillStyle = theme.bg;
  ctx.fillRect(0, 0, W, H);
  if (!prims.length) return { ms: 0, drawn: 0, texts: 0 };
  const box = visibleBox(cam, W, H);
  const ids = index.query(box);
  const ok = visibleFilter(inp);
  const tiny = 0.8 / cam.s;
  const shown: Prim[] = [];
  for (const n of ids) {
    const p = prims[n];
    if (preview && preview.ents.has(p.i)) continue;
    if (!ok(p)) continue;
    const b = index.boxes[n];
    if (p.k !== "t" && p.k !== "g" && b[2] - b[0] < tiny && b[3] - b[1] < tiny) continue; // smaller than a pixel
    shown.push(p);
  }
  if (preview) for (const p of preview.prims) if (ok(p)) shown.push(p);
  const dim = (p: Prim) => inp.focusView !== null && p.v !== inp.focusView;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  // 1. fills
  for (const p of shown) {
    if (p.k !== "g" || !p.p || p.mask) continue;
    const st = p.s !== undefined ? styles[p.s] : undefined;
    if (p.fill === "pattern" && !overlays.hatchTint) continue;
    ctx.globalAlpha = (p.fill === "pattern" ? 0.08 : alphaOf(st)) * (dim(p) ? 0.35 : 1);
    ctx.fillStyle = strokeColor(st, theme);
    ctx.beginPath();
    path(ctx, p.p, true, cam, W, H);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // 2. hatch pattern lines, thin
  for (const p of shown) {
    if (p.k !== "m" || !p.m) continue;
    const st = p.s !== undefined ? styles[p.s] : undefined;
    ctx.globalAlpha = 0.75 * (dim(p) ? 0.35 : 1);
    ctx.strokeStyle = ctx.fillStyle = strokeColor(st, theme);
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    segments(ctx, p.m, cam, W, H);
    ctx.stroke();
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // 3. the drawing's lines, one path per stroke (colour, width, dash)
  const groups = new Map<string, { color: string; width: number; dash: number[] | null; alpha: number; list: Prim[] }>();
  let drawn = 0;
  for (const p of shown) {
    if (p.k !== "p" || !p.p) continue;
    const st = p.s !== undefined ? styles[p.s] : undefined;
    const color = strokeColor(st, theme);
    const width = lineWidthPx(st, theme) + (p.r === "structural" ? 0.15 : 0);
    const dash = dashPx(st, cam.s);
    const alpha = alphaOf(st) * (dim(p) ? 0.35 : 1) * (p.r === "fixed" ? 0.7 : 1);
    const key = strokeKey(st, dash, color, width) + (dim(p) ? "|d" : "") + (p.r === "fixed" ? "|f" : "");
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { color, width, dash, alpha, list: [] }));
    g.list.push(p);
  }
  for (const g of groups.values()) {
    ctx.strokeStyle = g.color;
    ctx.lineWidth = g.width;
    ctx.globalAlpha = g.alpha;
    ctx.setLineDash(g.dash ?? []);
    ctx.beginPath();
    for (const p of g.list) path(ctx, p.p!, !!p.c, cam, W, H);
    ctx.stroke();
    drawn += g.list.length;
  }
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
  // 4. wipeouts mask what lies under them
  ctx.fillStyle = theme.bg;
  for (const p of shown) {
    if (!p.mask || !p.p) continue;
    ctx.beginPath();
    path(ctx, p.p, true, cam, W, H);
    ctx.fill();
  }
  // 5. control overlays: translucent, under the texts
  const hl = inp.highlight;
  if (hl) {
    const byEnt = (set: Set<number>) => shown.filter((p) => set.has(p.i) && p.k !== "t");
    const layer = (list: Prim[], color: string, width: number, alpha: number, dash: number[] = []) => {
      if (!list.length) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.globalAlpha = alpha;
      ctx.setLineDash(dash);
      ctx.beginPath();
      for (const p of list) {
        if (p.k === "m" && p.m) segments(ctx, p.m, cam, W, H);
        else if (p.p) path(ctx, p.p, !!p.c || p.k === "g", cam, W, H);
      }
      ctx.stroke();
    };
    if (overlays.holds) layer(byEnt(hl.holds), theme.dark ? "#9aa5b1" : "#7b8794", 3, 0.35, [6, 4]);
    if (overlays.follows) layer(byEnt(hl.follows), "#0ea5a4", 3, 0.32);
    if (overlays.drives) layer(byEnt(hl.drives), "#e0368c", 3.5, 0.42);
    // the notes that state the value are coloured in the text pass below (never boxed over the drawing)
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }
  // 6. texts
  let texts = 0;
  for (const p of shown) {
    if (p.k !== "t") continue;
    const st = p.s !== undefined ? styles[p.s] : undefined;
    ctx.globalAlpha = dim(p) ? 0.4 : alphaOf(st);
    const color = hl && overlays.texts && hl.texts.has(p.i) ? "#7c3aed" : strokeColor(st, theme);
    if (drawText(ctx, p, inp, color, fontFamily(st))) texts++;
  }
  ctx.globalAlpha = 1;
  // 7. a previewed change: the original ghosted, the proposal bright
  if (preview) {
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = theme.dark ? "#5f6b7a" : "#a3acb9";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const n of ids) {
      const p = prims[n];
      if (preview.ents.has(p.i) && p.k === "p" && p.p) path(ctx, p.p, !!p.c, cam, W, H);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "#f97316";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (const p of preview.prims) if (p.k === "p" && p.p && ok(p)) path(ctx, p.p, !!p.c, cam, W, H);
    ctx.stroke();
  }
  // 8. selection and hover
  const sel = shown.filter((p) => inp.selection.has(p.i));
  if (sel.length) {
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 2.6;
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    for (const p of sel) {
      if (p.k === "t" && p.at) {
        const [x, y] = toScreen(cam, W, H, p.at[0], p.at[1]);
        ctx.moveTo(x + 5, y);
        ctx.arc(x, y, 5, 0, Math.PI * 2);
      } else if (p.k === "m" && p.m) segments(ctx, p.m, cam, W, H);
      else if (p.p) path(ctx, p.p, !!p.c || p.k === "g", cam, W, H);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  if (inp.hover !== null && !inp.selection.has(inp.hover)) {
    ctx.strokeStyle = "#60a5fa";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (const p of shown) if (p.i === inp.hover && p.k !== "t" && p.p) path(ctx, p.p, !!p.c || p.k === "g", cam, W, H);
    ctx.stroke();
  }
  // 9. validation issues: a ring round each entity a check names
  if (overlays.issues && inp.issues.size) {
    ctx.strokeStyle = "#dc2626";
    ctx.lineWidth = 2;
    for (let n = 0; n < prims.length; n++) {
      const p = prims[n];
      if (!inp.issues.has(p.i)) continue;
      const b = index.boxes[n];
      const [x, y] = toScreen(cam, W, H, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2);
      const r = Math.max(8, (Math.max(b[2] - b[0], b[3] - b[1]) * cam.s) / 2 + 6);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  return { ms: performance.now() - t0, drawn, texts };
}
