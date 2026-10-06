// ─────────────────────────────────────────────────────────────────────────────
// Ground-truth fixtures for the prototype, read from the Aagento kernel library.
//
// The kernel ships ~17 structure families as DATA (RCC box, box culvert, pipe
// culvert, pier, abutment, span, deck slab, girder deck, pile group, well
// foundation, retaining wall, bridge GAD, ...). Each is a parametric program
// written by people. Evaluated at its defaults and flattened to plain geometry,
// it is exactly what a delivered DXF is: lines, polylines, circles, hatches,
// texts and dimensions with no parametric information left.
//
// For every length parameter we also evaluate the family with that ONE value
// changed. That is the ground truth the prototype is scored against: after
// reverse-engineering the base drawing blind, is there a single inferred
// parameter whose change reproduces the library's change exactly?
//
// Read-only use of aagento-bridge: nothing there is modified.
//
//   ../aagento-bridge/node_modules/.bin/esbuild tools/export_library_oracle.ts \
//     --bundle --platform=node --format=esm --outfile=.cache/oracle.mjs \
//     --tsconfig=../aagento-bridge/tsconfig.json --log-level=warning
//   node .cache/oracle.mjs fixtures/library
// ─────────────────────────────────────────────────────────────────────────────

import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { COMPONENT_LIBRARY } from '@/lib/components/library';
import { applyCadAction } from '@/lib/state/cadActions';
import { emptyCadDoc } from '@/lib/cad/document';
import { indexShapes, resolveAnchor, traceRing } from '@/lib/cad/geometry';
import { chainGroup } from '@/lib/cad/modify';
import type { LineShape, Shape } from '@/lib/geometry/types';
import type { Annotation } from '@/lib/cad/types';

type P = [number, number];
const r6 = (v: number) => Math.round(v * 1e6) / 1e6;
// Canvas is Y down; DXF is Y up.
const up = (p: { x: number; y: number }): P => [r6(p.x), r6(-p.y)];

interface Geom {
  polylines: { pts: P[]; closed: boolean; layer: string }[];
  lines: { a: P; b: P; layer: string }[];
  circles: { c: P; r: number; layer: string }[];
  texts: { at: P; text: string; h: number; rot: number; layer: string }[];
  dims: { p1: P; p2: P; axis: 'x' | 'y' | null; offset: number; layer: string }[];
  hatches: { outer: P[]; holes: P[][]; material: string }[];
  leaders: { pts: P[]; text: string; h: number }[];
}

function insert(definitionId: string, values: Record<string, number> = {}) {
  const r = applyCadAction([], emptyCadDoc(), { type: 'CAD_INSERT_COMPONENT', definitionId, at: { x: 0, y: 0 }, values } as any);
  if (!r || !r.cad.componentNotice?.ok) return null;
  return { shapes: r.shapes as Shape[], annotations: r.cad.annotations as Annotation[], settings: r.cad.settings, layers: r.cad.layers };
}

function flatten(out: NonNullable<ReturnType<typeof insert>>): Geom {
  const layerName = (id?: string) => out.layers.find((l: any) => l.id === id)?.name ?? id ?? '0';
  const g: Geom = { polylines: [], lines: [], circles: [], texts: [], dims: [], hatches: [], leaders: [] };
  const groups = new Map<string, LineShape[]>();
  for (const s of out.shapes) {
    if (s.type === 'line' && s.groupId) {
      groups.set(s.groupId, [...(groups.get(s.groupId) ?? []), s]);
    } else if (s.type === 'line') {
      g.lines.push({ a: up({ x: s.x1, y: s.y1 }), b: up({ x: s.x2, y: s.y2 }), layer: layerName(s.layerId) });
    } else if (s.type === 'circle') {
      g.circles.push({ c: up({ x: s.cx, y: s.cy }), r: r6(s.r), layer: layerName(s.layerId) });
    }
  }
  for (const lines of groups.values()) {
    const chain = chainGroup(lines);
    const layer = layerName(lines[0].layerId);
    if (chain) g.polylines.push({ pts: chain.points.map(up), closed: chain.closed, layer });
    else for (const s of lines) g.lines.push({ a: up({ x: s.x1, y: s.y1 }), b: up({ x: s.x2, y: s.y2 }), layer });
  }
  const idx = indexShapes(out.shapes);
  const at = (r: any) => resolveAnchor(r, idx);
  for (const a of out.annotations) {
    const layer = layerName(a.layerId);
    if (a.type === 'dimension' && (a.kind === 'linear' || a.kind === 'aligned')) {
      const p1 = at(a.p1), p2 = at(a.p2);
      if (p1 && p2) g.dims.push({ p1: up(p1), p2: up(p2), axis: a.kind === 'linear' ? (a.axis ?? null) : null, offset: r6(a.offset), layer });
    } else if (a.type === 'text') {
      const p = at(a.at);
      if (p && a.text.trim()) g.texts.push({ at: up(p), text: a.text, h: a.height, rot: a.rotation ?? 0, layer });
    } else if (a.type === 'level') {
      const p = at(a.at);
      if (p) {
        const rl = (out.settings.datumRL ?? 0) - p.y / 1000;
        g.texts.push({ at: up(p), text: `${a.label} ${rl.toFixed(3)}`.trim(), h: 2.5 * out.settings.annotationScale, rot: 0, layer });
      }
    } else if (a.type === 'leader') {
      const pts = a.points.map(at).filter(Boolean) as { x: number; y: number }[];
      if (pts.length >= 2) g.leaders.push({ pts: pts.map(up), text: a.text, h: a.height });
    } else if (a.type === 'hatch') {
      const b: any = a.boundary;
      if (b.kind === 'polygon') {
        g.hatches.push({ outer: b.outer.map(up), holes: (b.holes ?? []).map((h: any[]) => h.map(up)), material: a.material });
      } else if (b.kind === 'shapes') {
        const ring = traceRing(b.shapeIds.map((i: string) => idx.get(i)).filter(Boolean) as Shape[]);
        const holes = (b.holeShapeIds ?? []).map((i: string) => traceRing([idx.get(i)].filter(Boolean) as Shape[])).filter(Boolean) as { x: number; y: number }[][];
        if (ring) g.hatches.push({ outer: ring.map(up), holes: holes.map((h) => h.map(up)), material: a.material });
      }
    }
  }
  return g;
}

const outDir = process.argv[2] ?? 'fixtures/library';
mkdirSync(outDir, { recursive: true });
const index: any[] = [];
for (const D of COMPONENT_LIBRARY) {
  const base = insert(D.id);
  if (!base) { console.log(`skip ${D.id}: cannot insert`); continue; }
  const variants: any[] = [];
  for (const p of D.parameters) {
    if (p.kind !== 'length' || typeof p.default !== 'number') continue;
    const v = p.default;
    const delta = Math.max(100, Math.round(v * 0.2));
    const r = insert(D.id, { [p.name]: v + delta });
    variants.push({ param: p.name, label: p.label ?? p.name, base: v, delta, ok: !!r, geom: r ? flatten(r) : null });
  }
  const file = `${D.id.replace(/[^a-z0-9]+/gi, '_')}.json`;
  writeFileSync(path.join(outDir, file), JSON.stringify({ id: D.id, name: D.name, base: flatten(base), variants }));
  index.push({ id: D.id, name: D.name, file, lengthParams: variants.length, otherParams: D.parameters.filter((p) => p.kind !== 'length').map((p) => `${p.name}:${p.kind}`) });
  console.log(`${D.id}: ${variants.length} length parameter variants`);
}
writeFileSync(path.join(outDir, 'index.json'), JSON.stringify(index, null, 2));
