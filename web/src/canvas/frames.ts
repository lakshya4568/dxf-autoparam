// A view's own coordinate frame (the engine's frames.py): real millimetres from the view's own origin, and the reduced level where the view states
// one. A scale and a translation, nothing else — so a point goes to the sheet and back exactly, and the page keeps drawing, picking and editing the
// sheet's own entities; only what is SAID (the cursor, a point, a size) is in the view's frame.
import type { LocalFrame } from "../api/types";

export function toLocal(f: LocalFrame, x: number, y: number): [number, number] {
  return [(x - f.origin[0]) * f.mm_per_unit, (y - f.origin[1]) * f.mm_per_unit];
}

export function toSheet(f: LocalFrame, lx: number, ly: number): [number, number] {
  return [f.origin[0] + lx / f.mm_per_unit, f.origin[1] + ly / f.mm_per_unit];
}

/** The reduced level (metres) of a sheet y, where the view states a level; null where it does not. */
export function levelAt(f: LocalFrame, y: number): number | null {
  return f.level ? f.level.rl_m + ((y - f.level.at_y) * f.mm_per_unit) / 1000 : null;
}

const mm = (v: number) => `${Math.abs(v) < 0.05 ? "0" : v.toFixed(Math.abs(v) >= 100 ? 0 : 1)}`;

/** "x 1250 · y −300 mm · RL 607.751" — a point said in the view's own frame. */
export function sayLocal(f: LocalFrame, x: number, y: number): string {
  const [lx, ly] = toLocal(f, x, y);
  const rl = levelAt(f, y);
  return `x ${mm(lx)} · y ${mm(ly)} mm${rl !== null ? ` · RL ${rl.toFixed(3)}` : ""}`;
}
