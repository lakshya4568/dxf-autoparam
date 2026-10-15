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
  empty?: boolean;
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
  entities: number;
  views: string[];
  parts: string[];
  evidence: string[];
}

export interface UnitInfo {
  id: string;
  views: string[];
  params: ParamRow[];
  findings: { code: string; severity: string; item: string; message: string }[];
  components: { name: string; type: string; regions: string[] }[];
}

export interface Highlight {
  drives: number[];
  follows: number[];
  texts: number[];
  holds: { label: string; set: number[] }[] | number[];
  open?: unknown;
}

export interface ParamInfo {
  impact: { name: string; value: number; step: number; views: string[]; entities: number; per_view: Record<string, number>; errors: string[] };
  range: { name: string; value: number; min?: number; max?: number; min_reason?: string; max_reason?: string };
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

export interface RunEvent {
  kind: string;
  name?: string;
  ok?: boolean;
  summary?: string;
  said?: string;
  why?: string;
  text?: string;
  t?: number;
  turn?: number;
  [k: string]: unknown;
}

export interface RunProgress {
  run: string | null;
  status: string;
  label?: string;
  reason?: string | null;
  stage?: string | null;
  error?: string | null;
  events: RunEvent[];
  next: number;
  usage?: Record<string, unknown>;
  questions?: unknown[];
  verdict?: Record<string, unknown> | null;
  can?: { stop: boolean; continue: boolean; answer: boolean; apply: boolean; revert: boolean };
  instruction?: string;
  elapsed?: number;
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
} as const;
