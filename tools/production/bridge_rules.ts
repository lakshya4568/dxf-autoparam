// ─────────────────────────────────────────────────────────────────────────────
// The production bridge rules, served to Python over JSON lines (stdin → stdout).
//
// This file is the ONLY execution boundary between dxf-autoparam and the production bridge system. It imports the production
// app's own dispatch object, `BRIDGE_REGISTRY` (aagento-bridge: src/app/features/bridges/models/bridge-registry.ts) — the same object
// the production right panel calls `ruleEngine.compute(model)` / `ruleEngine.validate(model, derived)` on — and answers requests
// about it. Nothing here re-implements a formula: every number comes from the production code as it is in the checked-out revision.
//
// Built (bundled with esbuild) and started by `dxf_autoparam.production` — never edited for one bridge family:
//
//   dxf-autoparam production build         → .cache/production/bridge_rules.mjs + build.json
//
// Requests (one JSON object per line):  {"id": 1, "op": "compute", "family": "railway_rcc_box", "model": {...}}
// Answers  (one JSON object per line):  {"id": 1, "ok": true, "result": {...}}  or  {"id": 1, "ok": false, "error": "..."}
//
// Read-only use of aagento-bridge: nothing there is modified, and production code never writes to stdout (its console goes to stderr).
// ─────────────────────────────────────────────────────────────────────────────

// The registry's scene renderers import Angular components of partially compiled libraries: the JIT compiler must be loadable before
// the registry module is evaluated, or importing it throws. Nothing Angular is ever bootstrapped.
import '@angular/compiler';
import * as readline from 'node:readline';
import { BRIDGE_REGISTRY } from 'aagento-bridges/models/bridge-registry';
import { createMockCanvasContext } from 'aagento-bridges/utils/shared/mock-canvas-context';

declare const __BUILD_INFO__: unknown;

const PROTOCOL = 1;

// stdout is the protocol: whatever the production code logs goes to stderr
const toErr = (...a: unknown[]) => { process.stderr.write(a.map((x) => (typeof x === 'string' ? x : safeString(x))).join(' ') + '\n'); };
for (const k of ['log', 'info', 'warn', 'debug', 'trace']) (console as any)[k] = toErr;

function safeString(x: unknown): string {
  try { return JSON.stringify(x); } catch { return String(x); }
}

// ── values that cross the boundary ──────────────────────────────────────────────

// Plain JSON only: a non-finite number is said, not silently turned into null; functions and cycles are dropped.
function clean(v: any, depth = 0, seen = new Set<any>()): any {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : { nonfinite: String(v) };
  if (typeof v === 'string' || typeof v === 'boolean') return v;
  if (typeof v === 'function' || typeof v === 'symbol' || typeof v === 'bigint') return undefined;
  if (depth > 12 || seen.has(v)) return undefined;
  seen.add(v);
  if (Array.isArray(v)) return v.map((x) => clean(x, depth + 1, seen)).filter((x) => x !== undefined);
  const out: Record<string, any> = {};
  for (const [k, x] of Object.entries(v)) {
    const c = clean(x, depth + 1, seen);
    if (c !== undefined) out[k] = c;
  }
  seen.delete(v);
  return out;
}

const clone = (m: unknown) => JSON.parse(JSON.stringify(m ?? {}));

// A model wrapped so that every leaf read is recorded by its dotted path ("geometry.clear_w"); a read of a path that is absent is
// recorded too (the production code then falls back to a default of its own: that is knowledge about the code, not about a drawing).
const PUSH = Array.prototype.push;  // captured before anything observes push (validate does, for one call)

function tracked(obj: any, path: string, reads: Set<string>, missing: Set<string>, log?: string[]): any {
  if (obj === null || typeof obj !== 'object') return obj;
  return new Proxy(obj, {
    get(t, p) {
      if (typeof p !== 'string') return (t as any)[p];
      const v = (t as any)[p];
      const q = path ? `${path}.${p}` : p;
      if (v === null || v === undefined) { (p in t ? reads : missing).add(q); if (log) PUSH.call(log, q); return v; }
      if (typeof v !== 'object') { reads.add(q); if (log) PUSH.call(log, q); return v; }
      return tracked(v, q, reads, missing, log);
    },
  });
}

function family(name: string): any {
  const cfg = (BRIDGE_REGISTRY as any)[name];
  if (!cfg) throw new Error(`no family '${name}' in BRIDGE_REGISTRY (it has: ${Object.keys(BRIDGE_REGISTRY).join(', ')})`);
  return cfg;
}

function engine(name: string): any {
  const e = family(name).ruleEngine;
  if (!e || typeof e.compute !== 'function') throw new Error(`family '${name}' has no rule engine with compute() in BRIDGE_REGISTRY`);
  return e;
}

// ── headless rendering (only for the render op) ──────────────────────────────────

// The production renderers draw on a canvas: the production code's own mock context stands in for it. A few browser globals some views
// touch (an offscreen label canvas, Path2D) are given inert stand-ins; a view that needs more fails and says so.
function installBrowserStandIns(W: number, H: number): void {
  const g = globalThis as any;
  if (!g.document) g.document = { createElement: () => ({ width: W, height: H, style: {}, getContext: () => createMockCanvasContext(W, H) }) };
  if (!g.window) g.window = { devicePixelRatio: 1 };
  if (!g.Path2D) g.Path2D = class { constructor(_d?: unknown) {} addPath() {} moveTo() {} lineTo() {} closePath() {} rect() {} arc() {} ellipse() {} bezierCurveTo() {} quadraticCurveTo() {} };
}

const DRAW_OPS = new Set(['moveTo', 'lineTo', 'arc', 'arcTo', 'ellipse', 'rect', 'strokeRect', 'fillRect', 'fillText', 'strokeText', 'bezierCurveTo', 'quadraticCurveTo', 'roundRect']);

function fnv1a(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, '0');
}

function render(name: string, model: any, mode: string, W: number, H: number, stateIn: any): any {
  installBrowserStandIns(W, H);
  const cfg = family(name);
  const R = cfg.sceneRenderer;
  if (!R) return { available: false, reason: `family '${name}' has no scene renderer` };
  const reads = new Set<string>();
  const missing = new Set<string>();
  const m = tracked(clone(model), '', reads, missing);
  const bridges = [{ model: m, offset: 0, drawingColor: '#000000', bridgeTypeId: name }];
  let state = stateIn;
  if (!state) {
    state = { scale: 40, panX: 0, panY: 0 };
    try {
      if (cfg.initial2DScaleAndPan) state = { ...state, ...cfg.initial2DScaleAndPan(mode, W, H, { bridges: () => bridges, model: () => m }, name) };
    } catch { /* the default state stands: the view is still drawn, at a scale of our choosing */ }
    state = { ...state, defaultScale: state.scale };
  }
  const stream: string[] = [];
  let draws = 0;
  const base = createMockCanvasContext(W, H);
  const ctx = new Proxy(base, {
    get(t, p) {
      if (p === 'roundRect') return (...a: any[]) => { draws++; stream.push('roundRect:' + a.slice(0, 4).map((x) => (typeof x === 'number' ? x.toFixed(2) : '')).join(',')); };
      const x = (t as any)[p];
      if (typeof x === 'function' && DRAW_OPS.has(String(p))) {
        return (...a: any[]) => {
          draws++;
          stream.push(String(p) + ':' + a.map((v) => (typeof v === 'number' ? v.toFixed(2) : typeof v === 'string' ? v : '')).join(','));
          return x.apply(t, a);
        };
      }
      return x;
    },
    set(t, p, v) { (t as any)[p] = v; return true; },
  });
  const started = Date.now();
  try {
    if (typeof R.renderScene === 'function') R.renderScene(ctx, mode, W, H, 1, { ...state, model: m }, name, bridges, 0, false);
    else if (typeof R.draw === 'function') R.draw(ctx, W, H, mode, bridges[0], { ...state, model: m });
    else return { available: false, reason: `family '${name}' scene renderer has neither renderScene nor draw` };
  } catch (e: any) {
    return { available: true, ok: false, error: String(e?.message || e).slice(0, 300), draws, reads: [...reads].sort(), missing: [...missing].sort(), state: clean(state) };
  }
  return { available: true, ok: true, draws, signature: fnv1a(stream.join(';')), reads: [...reads].sort(), missing: [...missing].sort(),
           state: clean(state), ms: Date.now() - started };
}

// ── the operations ──────────────────────────────────────────────────────────────

function hello(): any {
  const families = Object.entries(BRIDGE_REGISTRY as Record<string, any>).map(([key, cfg]) => ({
    key,
    title: cfg.title,
    has_compute: typeof cfg.ruleEngine?.compute === 'function',
    has_validate: typeof cfg.ruleEngine?.validate === 'function',
    has_levels: typeof cfg.computedLevelsMapper === 'function',
    has_views: typeof cfg.viewButtons === 'function',
    has_renderer: !!cfg.sceneRenderer && (typeof cfg.sceneRenderer.renderScene === 'function' || typeof cfg.sceneRenderer.draw === 'function'),
    has_defaults: !!cfg.defaults && Object.keys(cfg.defaults).length > 0,
  }));
  return { protocol: PROTOCOL, build: typeof __BUILD_INFO__ === 'undefined' ? null : __BUILD_INFO__, node: process.version, families };
}

function compute(name: string, model: any): any {
  return clean(engine(name).compute(clone(model)));
}

const OPS: Record<string, (r: any) => any> = {
  hello: () => hello(),
  defaults: (r) => clean(clone(family(r.family).defaults)),
  compute: (r) => ({ derived: compute(r.family, r.model) }),
  compute_many: (r) => ({
    derived: (r.models as any[]).map((m) => {
      try { return { ok: true, derived: compute(r.family, m) }; } catch (e: any) { return { ok: false, error: String(e?.message || e).slice(0, 300) }; }
    }),
  }),
  validate: (r) => {
    const e = engine(r.family);
    if (typeof e.validate !== 'function') return { available: false, reason: `the rule engine registered for '${r.family}' has no validate()` };
    // what the checks read — model fields and computed values — so a caller can tell a check made on drawing values from one made on defaults
    const reads = new Set<string>();
    const missing = new Set<string>();
    const dReads = new Set<string>();
    const dMissing = new Set<string>();
    const log: string[] = [];
    const dLog: string[] = [];
    const m = tracked(clone(r.model), '', reads, missing, log);
    const d = tracked(e.compute(clone(r.model)), '', dReads, dMissing, dLog);
    // Each check reads its fields, then pushes its message: the reads logged since the previous message are that message's own. Array
    // push is observed for the duration of this one call (restored in finally), so every message says which fields decided it.
    const attributed: any[] = [];
    let mMark = 0; let dMark = 0;
    let issues: any;
    try {
      (Array.prototype as any).push = function (this: any[], ...items: any[]) {
        for (const it of items) {
          if (it && typeof it === 'object' && typeof it.sev === 'string' && typeof it.msg === 'string') {
            PUSH.call(attributed, { sev: it.sev, msg: it.msg, reads: [...new Set(log.slice(mMark))], derived_reads: [...new Set(dLog.slice(dMark))] });
            mMark = log.length; dMark = dLog.length;
          }
        }
        return PUSH.apply(this, items);
      };
      issues = e.validate(m, d);
    } finally {
      (Array.prototype as any).push = PUSH;
    }
    return { available: true, issues: clean(Array.isArray(issues) ? issues : []), attributed: clean(attributed), reads: [...reads].sort(),
             missing: [...missing].sort(), derived_reads: [...dReads].sort() };
  },
  levels: (r) => {
    const cfg = family(r.family);
    if (typeof cfg.computedLevelsMapper !== 'function') return { available: false, reason: `'${r.family}' registers no computedLevelsMapper` };
    return { available: true, levels: clean(cfg.computedLevelsMapper(compute(r.family, r.model), clone(r.model))) };
  },
  views: (r) => {
    const cfg = family(r.family);
    if (typeof cfg.viewButtons !== 'function') return { available: false, reason: `'${r.family}' registers no viewButtons` };
    // which model paths decide the list (a wing wall shown adds a view): read while the production code builds it
    const reads = new Set<string>();
    const missing = new Set<string>();
    const m = tracked(clone(r.model), '', reads, missing);
    const bs = { model: () => m, bridges: () => [{ model: m }], activeTemplate: () => r.family, workspaceBridges: () => [{ model: m, bridgeTypeId: r.family }] };
    let lineTypeRead = false;
    const ps = { activeProject: () => { lineTypeRead = true; return { lineType: r.line_type ?? null }; } };
    const views = clean(cfg.viewButtons(bs, ps));
    return { available: true, views, reads: [...reads].sort(), missing: [...missing].sort(), reads_project_line_type: lineTypeRead };
  },
  trace: (r) => {
    const reads = new Set<string>();
    const missing = new Set<string>();
    const derived = clean(engine(r.family).compute(tracked(clone(r.model), '', reads, missing)));
    return { reads: [...reads].sort(), missing: [...missing].sort(), derived };
  },
  render: (r) => render(r.family, r.model, String(r.mode), Number(r.width || 1600), Number(r.height || 1000), r.state || null),
};

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on('line', (line) => {
  if (!line.trim()) return;
  let req: any;
  try { req = JSON.parse(line); } catch (e: any) {
    process.stdout.write(JSON.stringify({ id: null, ok: false, error: `not JSON: ${String(e?.message || e).slice(0, 120)}` }) + '\n');
    return;
  }
  const op = OPS[req?.op];
  let out: any;
  if (!op) out = { id: req?.id ?? null, ok: false, error: `unknown op '${req?.op}' (ops: ${Object.keys(OPS).join(', ')})` };
  else {
    try { out = { id: req.id ?? null, ok: true, result: op(req) }; } catch (e: any) { out = { id: req.id ?? null, ok: false, error: String(e?.message || e).slice(0, 400) }; }
  }
  process.stdout.write(JSON.stringify(out) + '\n');
});
