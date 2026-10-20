// The typed contract between this app and the Python engine (src/dxf_autoparam/workspace.py). The engine owns the geometry,
// the formulas and every check; these types describe what it sends. tests/test_web_contract.py asserts the Python side
// keeps the keys listed in CONTRACT below, so a change on either side is caught.

export type Box = [number, number, number, number];
export type XY = [number, number];

/** One drawn primitive, in drawing units (world coordinates). */
export interface Prim {
  i: number; // the sheet entity it draws
  k: "p" | "g" | "t" | "m"; // polyline · filled polygon · text · many segments (hatch pattern lines)
  r: string; // role: structural | reference | annotation | fixed
  l: string; // layer
  v: string; // the sheet group (view) it is in
  p?: number[]; // flat x0 y0 x1 y1 …
  m?: number[]; // flat segments x0 y0 x1 y1 x0 y0 x1 y1 …
  c?: 1; // closed
  d?: 1; // part of a dimension
  s?: number; // index into styles
  tag?: "arrow" | "hatch" | "band" | "text";
  mask?: 1; // a wipeout
  fill?: "pattern" | "solid" | "gradient"; // a hatch boundary
  pat?: string;
  at?: XY;
  t?: string;
  h?: number;
  rot?: number;
  ha?: "c" | "r";
  va?: "t" | "m" | "bt";
  wf?: number;
  ls?: number;
  width?: number;
  oblique?: number;
}

/** A resolved CAD style: colour (ACI 7 = foreground), lineweight (mm), linetype and its dash pattern (drawing units). */
export interface Style {
  c: string;
  w: number;
  lt: string;
  fg?: 1;
  a?: number;
  d?: number[];
  f?: string;
}

export interface Geometry {
  prims: Prim[];
  styles: Style[];
  extent: Box;
  frame: Box | null;
}

export interface Group {
  id: string;
  kind: "view" | "table" | "notes" | "title_block" | "label";
  name: string;
  view_type: string;
  bbox: Box;
  entities: number;
  scale?: number | null;
  unit?: string | null;
}

export interface UnitRow {
  id: string;
  views: string[];
  built: boolean;
  entities: number;
  parametrized: boolean;
  params: number | null;
  /** Measured sizes nobody named, kept as drawn (not inputs; released one by one or all). */
  kept_as_drawn?: number;
  dropped: string;
}

export interface SharedRow {
  id: string;
  name: string;
  label: string;
  value: number;
  unit: string;
  bindings: { unit: string; param: string; status: string; reason: string; views: string[] }[];
}

export interface Summary {
  file: string;
  path: string;
  units_mm: number;
  extent: Box;
  frame: Box | null;
  entities: number;
  notes: string[];
  groups: Group[];
  furniture: { frame: number[]; rules: number[]; stray: number[]; watermark: number[] };
  units: UnitRow[];
  shared: SharedRow[];
  values: Record<string, number>;
  can_undo: boolean;
  can_redo: boolean;
  ai_running: boolean;
  current_run: string | null;
  revision: number;
  /** Where the work is kept while it is made, and what was opened from there (null: autosave is off). */
  autosave?: AutosaveInfo | null;
  empty?: boolean;
}

export interface AutosaveInfo {
  path: string | null;
  saved_at: number | null; // epoch seconds of the last write this session
  saved_revision: number | null;
  revision: number | null;
  restored: { from?: string | null; revision?: number; path?: string; saved_at?: number; kept_as?: string; problems?: string[] } | null;
  error: string | null;
  /** Another live server that keeps this drawing's saved work (this one writes nothing while it does). */
  owner?: { pid: number; port?: number | null } | null;
}

export interface ParamRow {
  name: string;
  key: string; // what preview / apply take: the shared name, or "U…" + "." + local name
  shared: boolean;
  label: string;
  state: string;
  changed: boolean;
  value: number;
  drawn: number;
  unit: string;
  kind: string;
  source: string;
  /** The engine's own measurement (GapX6, ThkY1 …) that nobody named. */
  generic?: boolean;
  entities: number;
  views: string[];
  parts: string[];
  evidence: string[];
}

/** A named quantity that is measured, not an input: a size of work kept as drawn, or a size the set-out fixes at both ends. */
export interface MeasuredRow {
  name: string;
  label: string;
  value: number;
  unit: string;
  expr: string;
  between: string[] | null;
  part: string | null;
  held: boolean;
  existing: boolean;
}

/** A measured size nobody named, kept as drawn: not an input, the drawing is as it was. */
export interface FrozenRow {
  name: string;
  value: number;
  unit: string;
  label: string;
  kind: string;
  occurrences: number;
  measures: string[] | null;
  why: string;
}

export interface UnitInfo {
  id: string;
  /** The sheet revision this was read at: the panel reads the unit again when the sheet has moved on. */
  revision?: number;
  views: string[];
  params: ParamRow[];
  measured?: MeasuredRow[];
  frozen?: FrozenRow[];
  /** The choices a person made to settle an undecided direction in this unit (each can be taken back). */
  settled?: { choice: string; title: string; kind: string }[];
  findings: { code: string; severity: string; item: string; message: string }[];
  components: { name: string; type: string; regions: string[] }[];
  /** How many of the unit's dimensions a named value drives, measured by stepping each value (null: nobody parametrized the unit). */
  dimensions?: { total: number; driven: number; constant: number; unread: number; constants: { mm: number; text: string }[]; unsteppable: string[] } | null;
}

export interface Highlight {
  drives: number[];
  follows: number[];
  texts: number[];
  /** The parts a plan keeps fixed, by label → their entities ({} when none). Read through entitySet (api/normalize): the engine sends an
   * object, the page once took it for a list, and a click on a value did nothing. */
  holds: Record<string, number[]> | { label: string; set: number[] }[] | number[] | null;
  open?: Record<string, number[]> | null;
}

/** How one view takes a value growing, measured by the engine (SheetModel.growth): which of the size's two lines stays, and the design intent behind it
 * (who decided — the engine's default or a person —, on what evidence). `mode` names the line that STAYS: start (left / bottom), end (right / top). */
export interface GrowthRow {
  unit: string;
  mode: "start" | "end" | "centre" | "slides" | "other" | "none";
  why: string;
  from?: string;
  to?: string;
  moves?: Record<string, number>;
  intent?: { policy: string | null; centre: string | null; source: string | null; status: string | null; evidence: string[]; line?: string | null; assembly?: string | null; settled?: string[] } | null;
  /** The size's axis ended undecided (no side could stay without breaking something): why, and the lines nothing may move that stood in the way. */
  undecided?: { axis: string; assembly: string; evidence: string[]; blocked: Blocker[]; drivers: string[] };
  /** The size was left out of its structure's growth (it keeps the direction the set-out gave it), and why. */
  left_out?: { axis: string; status: string; why: string };
  /** The choices a person already made about this size's direction (each can be taken back). */
  settled?: { choice: string; title: string; kind: string }[];
}

/** A line nothing may move that stood in the way of a side staying, and what sets it. */
export interface Blocker {
  line: string;
  kind: string;
  level?: string;
  part?: string;
}

/** One way to settle an undecided direction, TRIED FOR REAL by the engine (SheetModel.settle_options): a pinned level left free, a held part
 * released or a size read instead of set — with what it would do. Only what settles the axis and breaks nothing is offered. */
export interface SettleChoice {
  id: string;
  title: string;
  kinds: string[];
  edits: { kind: string; target: string; lines: string[] }[];
  policy: string | null;
  centre: string | null;
  status: string;
  stays: string;
  evidence: string[];
  driver: string | null;
  moves: string[];
  left_out: { name: string; why: string }[];
  stops_being_input: string[];
  become_inputs: string[];
  collateral: string[];
  asked_in_growth: boolean;
  discards: string[];
}

export interface SettleOptions {
  unit: string;
  name: string;
  local: string;
  revision: number;
  axis: string | null;
  assembly: string | null;
  status: string;
  evidence: string[];
  blocked: Blocker[];
  drivers: string[];
  choices: SettleChoice[];
  rejected: { id: string; why: string }[];
  notes: string[];
}

export interface ParamInfo {
  impact: { name: string; value: number; step: number; views: string[]; entities: number; per_view: Record<string, number>; errors: string[] };
  range: { name: string; value: number; min?: number; max?: number; min_reason?: string; max_reason?: string };
  growth?: GrowthRow[];
  highlight: Highlight;
  card?: unknown;
}

export interface DeltaResult {
  ok: boolean;
  errors?: string[];
  warnings?: string[];
  delta?: Prim[];
  styles?: Style[];
  summary?: Summary;
  reload?: boolean;
  by_view?: Record<string, number>;
  changed?: number;
  measured?: Record<string, Record<string, number>>;
  error?: string;
}

export interface EntityRecord {
  index: number;
  id: string;
  type: string;
  layer: string;
  role: string;
  source: Record<string, unknown>;
  style: { color: string; fg: boolean; alpha: number; lw: number; lt: string; dash: number[]; font?: string } | null;
  geometry: { points_mm: XY[]; closed: boolean; radius_mm?: number; points_total?: number };
  view: { id: string; name: string; kind: string };
  unit: string | null;
  text?: string;
  dimension?: { measurement_mm: number; override: string; dimtype: number; dimstyle?: string };
  drawn_with?: Record<string, number>;
  hatch?: { fill: string; pattern: string; pattern_lines: number; too_dense: boolean };
  parametric?: { points: { x: PointAxis | null; y: PointAxis | null }[]; parameters: string[]; held: boolean; fixed: boolean };
  parts?: string[];
  text_height_mm?: number;
  symbol_of?: string;
}

/** How one coordinate of a point is set out: a datum line plus an offset, the line's formula and the values it reaches. */
export interface PointAxis {
  line: string;
  offset_mm: number;
  formula: string;
  origin: string;
  parameters: string[];
}

export interface Annotation {
  id: string;
  kind: string;
  text: string;
  attachment: "geometry" | "component" | "datum" | "view" | "sheet" | "fixed";
  status: "resolved" | "ambiguous" | "unassociated";
  items: number[];
  evidence: string[];
  targets?: { kind: string; ref: string; index?: number; score: number; evidence: string[] }[];
  states?: Record<string, unknown>;
  quantity?: Record<string, unknown>;
  view?: string;
  unit?: string | null;
}

export interface LayerRow {
  name: string;
  on: boolean;
  frozen: boolean;
  locked: boolean;
  color: string;
  linetype: string;
  entities: number;
  types: Record<string, number>;
  roles: Record<string, number>;
  views: Record<string, number>;
  colours_used: Record<string, number>;
  linetypes_used: Record<string, number>;
  words: string[];
  in_analysis: boolean;
  character: string;
  name_says?: string;
}

export interface Statuses {
  counts: Record<string, number>;
  learned_colours: Record<string, { status: string; notes: string[]; count: number; contrary?: number }>;
  entities: Record<string, { status: string; evidence: string[] }>;
}

export interface CheckRow {
  status: "pass" | "fail" | "not checked";
  [k: string]: unknown;
}

export interface BehaviourReport {
  ok: boolean;
  failed: string[];
  changes: Record<string, number>;
  changed_entities: number;
  categories: Record<string, { status: "pass" | "fail" | "not checked"; items: CheckRow[]; basis?: string }>;
}

export interface CoverageRow {
  type: string;
  in_file: number;
  read: number;
  drawn: number;
  editable: number;
  hidden: number;
  not_read: number;
  export: string;
  not_read_handles?: string[];
}

export interface Coverage {
  file: string;
  faithful: boolean;
  problems: string[];
  entities: Record<string, number>;
  types: CoverageRow[];
  linetypes: Record<string, { entities: number; dash: number[]; drawn_as: string }>;
  hatch_patterns: Record<string, { count: number; drawn_as: string[] }>;
  compound_parts?: Record<string, number>;
  colors?: Record<string, number>;
  lineweights?: Record<string, number>;
  fonts?: Record<string, number>;
  dimension_styles?: Record<string, number>;
  header?: Record<string, number | string>;
  layouts?: { name: string; entities: number; read: boolean; viewports: Record<string, unknown>[] }[];
}

export interface AgentNotes {
  checklist: { id: string; text: string; status: "todo" | "doing" | "done" | "blocked"; revision: number; evidence?: string }[];
  learned: { fact: string; about?: string; evidence: string; revision: number; stale?: boolean }[];
  revision?: number;
}

/** What the engine says about a picture it gave the model (run.py `note_image`). The event's own `kind` is "image": the picture's kind travels here. */
export interface PictureMeta {
  kind: string; // overview · tile · zoom · sheet
  size: [number, number]; // pixels
  mm_per_px: number | null;
  text_px: number | null; // how tall the drawing's own text is in this picture: under about 9 px it is a blur
  legible: boolean | null;
  box_mm: number[]; // the part of the sheet it shows, x0 y0 x1 y1
  turn: number; // the model turn it was given on
  tiles: string[]; // the tiles marked on it (an overview)
  caption: string;
}

/** One event of a run, as the engine emitted it (src/dxf_autoparam/ai/run.py, loop.py, narrate.py). Fields depend on `kind`. */
export interface RunEvent {
  kind: string; // run_start · user · stage · turn · call · thought · retry · tool_start · tool · image · applied · state · question · verdict · error · note · budget · status
  seq?: number;
  t?: number; // seconds since the run started
  turn?: number;
  id?: string; // a tool call's id (tool_start and its tool)
  name?: string; // the tool
  doing?: string; // what the tool is doing, in words (the engine's)
  stage?: string | null;
  phase?: string | null; // planning · inspecting · applying · validating · asking
  args?: string;
  args_full?: unknown;
  result?: unknown;
  ok?: boolean;
  why?: string;
  said?: string; // the model's own one-line reason for the call
  summary?: string; // the engine's sentence about the result
  ms?: number;
  unit?: string | null;
  image?: { id?: string; revision?: number; unit?: string; view_ids?: string[]; state?: string };
  pic?: PictureMeta; // an `image` event: what the picture is
  text?: string;
  instruction?: string;
  scope?: Record<string, unknown>;
  answers?: Record<string, string>;
  from?: string;
  to?: string;
  label?: string;
  reason?: string;
  options?: string[];
  recommended?: string;
  about?: string;
  model?: string;
  thinking?: string;
  cached?: boolean;
  revision?: number;
  values?: string[];
  [k: string]: unknown;
}

export interface RunQuestion {
  id: string;
  text: string;
  options?: string[];
  recommended?: string;
  about?: string;
  why?: string;
}

export interface Criterion {
  id: string;
  ok: boolean;
  detail: string;
}

/** What the sheet holds for one unit at the end of a run — read off the sheet, never off what the model said. */
export interface CoverageRow {
  unit: string;
  views: string[];
  state: "parametrized" | "skipped" | "looked_at" | "untouched";
  covered: boolean;
  parts?: number;
  inputs?: number;
  measured?: number;
  kept_as_drawn?: number;
  reason?: string;
  refused?: string[];
}

export interface RunVerdict {
  state?: string;
  headline?: string;
  remaining?: unknown;
  criteria?: Criterion[];
  coverage?: CoverageRow[];
  coverage_sentence?: string;
  engine_summary?: string;
  finish_summary?: string;
  values_applied?: { name: string; value: number; already?: boolean }[];
  notes?: string[];
  [k: string]: unknown;
}

export interface RunProgress {
  run: string | null;
  status: string;
  label?: string;
  reason?: string | null;
  stage?: string | null;
  phase?: string | null;
  error?: string | null;
  events: RunEvent[];
  next: number;
  usage?: { turns?: number; tool_calls?: number; tokens?: number; seconds?: number; limits?: Record<string, number> };
  questions?: RunQuestion[];
  verdict?: RunVerdict | null;
  can?: { stop: boolean; continue: boolean; answer: boolean; apply: boolean; revert: boolean };
  instruction?: string;
  scope?: Record<string, unknown>;
  elapsed?: number;
  parent?: string | null;
  reverted?: boolean;
}

export interface RunSummary {
  id: string;
  instruction: string;
  status: string;
  label: string;
  started?: number;
  finished?: number | null;
  usage?: Record<string, unknown>;
  units?: string[];
  verdict?: { state?: string; headline?: string; remaining?: unknown } | null;
  reason?: string | null;
  scope?: Record<string, unknown>;
  timeline?: RunEvent[];
}

/** Keys the Python side must keep (checked by tests/test_web_contract.py). */
export const CONTRACT = {
  summary: ["file", "units_mm", "extent", "groups", "units", "shared", "values", "can_undo", "can_redo", "revision"],
  geometry: ["prims", "styles", "extent", "frame"],
  prim: ["i", "k", "r", "l", "v"],
  style: ["c", "w", "lt"],
  delta: ["ok"],
  entity: ["index", "id", "type", "layer", "role", "source", "style", "geometry", "view", "unit"],
  annotation: ["id", "kind", "text", "attachment", "status", "items", "evidence"],
  layer: ["name", "on", "frozen", "color", "linetype", "entities", "character"],
  behaviour: ["ok", "failed", "categories", "changed_entities"],
  coverage: ["faithful", "problems", "types", "linetypes"],
  notes: ["checklist", "learned"],
  run_progress: ["run", "status", "events", "next", "phase", "can", "usage"],
  tool_start: ["id", "name", "doing", "stage", "phase", "args_full"],
  tool_result: ["id", "name", "doing", "stage", "phase", "ok", "summary", "ms", "args_full", "result"],
} as const;
