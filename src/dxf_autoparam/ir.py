"""The parametric IR — every data structure the pipeline passes along.

    DXF ─► Drawing (Items + Slots) ─► Analysis (Datums, Gaps, Clusters, Constraints)
        ─► Model (Parameters, LinearForms per datum, tree, results) ─► regenerate ─► DXF

The central idea: a 2D drawing is a set of SCALAR COORDINATE SLOTS (every x and y of
every vertex, centre and text anchor). Slots that coincide are one DATUM (a vertical
or horizontal line of the drawing's set-out). A parametric model writes every datum
as an expression of named PARAMETERS, so every slot is `datum(params) + offset`.

Because a set-out drawing's datums are chained by sizes (wall, opening, wall ...),
every datum turns out to be LINEAR in the parameters: `const + Σ coeff·param`. The
model therefore regenerates in closed form, with no iterative solver (see the docs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

Axis = Literal["x", "y"]
Point = tuple[float, float]


# ── Drawing: what the DXF holds ─────────────────────────────────────────────────


class Role(StrEnum):
    """What an item contributes to the analysis."""

    STRUCTURAL = "structural"  # defines the set-out: its vertices are datums
    REFERENCE = "reference"  # centre / axis lines: construction axes, not faces
    ANNOTATION = "annotation"  # follows the structure: dims, texts, hatches, blocks
    FIXED = "fixed"  # never moves: sheet border, title block


@dataclass
class Item:
    """One DXF entity, reduced to the points that position it."""

    index: int
    handle: str
    dxftype: str
    layer: str
    role: Role
    pts: list[Point]
    closed: bool = False
    bulges: list[float] = field(default_factory=list)
    radius: float | None = None  # CIRCLE / ARC
    text: str | None = None  # TEXT / MTEXT / DIMENSION override
    text_height: float | None = None
    # Indices into `pts` that are true structural vertices (an ARC's centre is not).
    vertex_pts: list[int] = field(default_factory=list)
    # Point index pairs that are straight segments (polyline edges without bulge).
    segments: list[tuple[int, int]] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    # Where it came from, for writing back: the top-level handle, then the index path
    # through nested block references ("2A4/7/3"). Top-level entities: just the handle.
    src: str = ""
    # A rigid symbol (a small block: a level marker, a north arrow) moves as one piece
    # with its insertion point; this is the index of that insertion point's item.
    anchor: int | None = None
    # Curves the prototype does not reshape (ellipse, spline, text outlines), as
    # flattened world polylines for display; they translate with pts[0].
    display: list[list[tuple[float, float]]] = field(default_factory=list)


@dataclass
class Drawing:
    path: str
    units_mm: float  # millimetres per drawing unit
    tol: float  # coincidence tolerance, drawing units
    items: list[Item]
    extent: tuple[float, float, float, float]  # minx, miny, maxx, maxy of structural geometry
    unsupported: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # what the reader repaired, skipped or assumed
    layout: str = "Model"
    # What the file held and what of it is read, drawn, editable and exportable (fidelity.coverage_report) — by type,
    # with the handles of every visible entity that is not drawn. Empty for a drawing not read from a file.
    coverage: dict = field(default_factory=dict)


# ── Analysis: what the geometry says about itself ───────────────────────────────


@dataclass
class Datum:
    """A set-out line: every slot within tolerance of `value` on one axis."""

    id: str  # "x12", "y3", "ax0" (a construction axis)
    axis: Axis
    value: float
    virtual: bool = False  # a construction axis no vertex sits on (a loop's own centre line)
    weak: bool = False  # carried only by loose lines (level / water / ground lines): a poor parent
    source: str = "vertex"  # vertex | drawn-axis | loop-axis | global-axis
    items: set[int] = field(default_factory=set)


class GapKind(StrEnum):
    """How a gap between two datums was found — and therefore what it probably is."""

    SOLID = "solid"  # two parallel faces with material (hatch / inside a closed outline) between
    VOID = "void"  # two parallel faces with an opening between (a hole in an outline)
    OPEN = "open"  # two parallel faces, nothing known between
    LEG = "leg"  # equal run and rise of a sloped edge (a 45° chamfer / haunch leg)
    RUN = "run"  # horizontal extent of a sloped edge
    RISE = "rise"  # vertical extent of a sloped edge
    CHAIN = "chain"  # consecutive vertices along one straight edge (a step, a projection)
    PITCH = "pitch"  # between the axes of repeated congruent members
    OFFSET = "offset"  # from a member axis / centre to the nearest face
    ARC = "arc"  # centre ↔ end of an arc (rigid)
    DIM = "dim"  # measured only by a DIMENSION entity (an overall size)
    SLOPE = "slope"  # the run of an inclined edge at a recognisable ratio: it follows the rise
    DIAMETER = "diameter"  # a circle's size (the innermost of concentric circles)
    RING = "ring"  # radial wall between concentric circles


@dataclass
class Evidence:
    kind: str  # dimension | repeat | mirror | text | round | not-round | material | void | overlap | symmetric
    weight: float
    detail: str


@dataclass
class Gap:
    """A candidate relationship: datum `b` sits `value` from datum `a` (a < b)."""

    id: str
    axis: Axis
    a: str
    b: str
    value: float
    kind: GapKind
    overlap: float = 0.0  # facing length, for faces
    sample: Point | None = None  # where it was observed (for text proximity, UI)
    sym_axis: str | None = None  # a construction axis this gap is centred on
    dims: list[int] = field(default_factory=list)  # DIMENSION items measuring it
    cluster: str | None = None
    lengthwise: bool = False  # faces much shorter than the gap: a member's LENGTH, not a thickness
    # SLOPE: (x datum of end 1, y datum of end 1, x datum of end 2, y datum of end 2, run/rise)
    slope: tuple[str, str, str, str, float] | None = None
    circle: int | None = None  # DIAMETER / RING: the circle item it sizes
    inner: int | None = None  # RING: the circle inside it
    # the lines it was measured on, when a line existing work and new work share was split for the build (intent.split_structures): every
    # build starts by putting them back, so a split never outlives the answer it was made for
    split_of: tuple[str, str] | None = None


class Status(StrEnum):
    CONFIRMED = "confirmed"  # a dimension states it, or overwhelming geometric evidence
    PROBABLE = "probable"
    CANDIDATE = "candidate"
    WEAK = "weak"  # kept as a fixed offset unless a person promotes it


@dataclass
class Cluster:
    """Equal gaps of one kind and axis: one candidate PARAMETER."""

    id: str
    name: str
    label: str
    kind: GapKind
    axes: set[str]
    value: float
    gaps: list[str]
    confidence: float = 0.0
    status: Status = Status.WEAK
    evidence: list[Evidence] = field(default_factory=list)
    suggested: str | None = None  # a name read from the drawing's own words
    accepted: bool = False


@dataclass
class Constraint:
    """A geometric relationship detected in the drawing (reported; most are kept by construction)."""

    kind: str  # horizontal | vertical | parallel | perpendicular | coincident | collinear | equal_length | concentric | symmetric
    items: list[int]
    confidence: float
    kept_by: str  # "construction" (shared datums keep it) | "parameter" | "reported"
    detail: str = ""


@dataclass
class Analysis:
    drawing: Drawing
    datums: dict[str, Datum]
    slot_datum: dict[tuple[int, int, str], tuple[str, float]]  # (item, pt, axis) -> (datum id, offset)
    gaps: dict[str, Gap]
    clusters: dict[str, Cluster]
    constraints: list[Constraint]
    axes: list[str]  # construction axis datum ids
    global_axis: dict[str, str | None]  # axis -> datum id of a whole-drawing symmetry axis
    notes: list[str] = field(default_factory=list)
    # Notes that state the height of a horizontal line in metres ("FORMATION LEVEL 101.250"):
    # (y datum id, text item, the note's words, the stated value in m)
    stated_levels: list[tuple[str, int, str, float]] = field(default_factory=list)
    sym_counts: dict[str, int] = field(default_factory=dict)  # axis datum -> gaps centred on it
    # The drawing's level datum: RL (mm) = y (mm) + level_offset_mm. 0 when drawn at RL×1000;
    # found from the level notes themselves, so a sheet drawn at any origin still reads its levels.
    level_offset_mm: float = 0.0
    # In a unit of views linked by projection: the views each line is drawn in, on an axis the views do NOT share (views one over the other share
    # their vertical lines; their horizontal lines are each its own view's). Such a line is set out within its own view only (build.py).
    datum_views: dict[str, list[str]] = field(default_factory=dict)
    # Derived structures computed once on demand (the planar topology, …); not part of the analysis proper.
    cache: dict = field(default_factory=dict, repr=False)


# ── Model: the recovered parametric program ─────────────────────────────────────


@dataclass
class LinearForm:
    """const + Σ coeff·param — every datum of a set-out drawing is one of these."""

    const: float = 0.0
    terms: dict[str, float] = field(default_factory=dict)

    def evaluate(self, values: dict[str, float]) -> float:
        return self.const + sum(c * values[p] for p, c in self.terms.items())

    def plus(self, other: LinearForm, k: float = 1.0) -> LinearForm:
        terms = dict(self.terms)
        for p, c in other.terms.items():
            terms[p] = terms.get(p, 0.0) + k * c
            if abs(terms[p]) < 1e-12:
                del terms[p]
        return LinearForm(self.const + k * other.const, terms)

    @staticmethod
    def param(name: str, k: float = 1.0) -> LinearForm:
        return LinearForm(0.0, {name: k})


@dataclass
class TreeEdge:
    """How one datum is set out from another — the dependency graph."""

    child: str
    parent: str
    how: str  # "param" | "const" | "symmetric" | "attach"
    gap: str | None
    param: str | None
    sign: float
    amount: float  # the constant (for const/attach) or the coefficient (for param)


@dataclass
class Parameter:
    name: str
    label: str
    value: float
    unit: str
    kind: str
    axes: list[str]
    confidence: float
    status: str
    evidence: list[Evidence]
    occurrences: int
    suggested: str | None = None
    affects: int = 0  # slots that move when it changes
    min: float | None = None


@dataclass
class Result:
    """A relationship the tree did not need: worked out, reported — e.g. Overall = 2·T + S."""

    gap: str
    label: str
    value: float
    form: LinearForm
    dimensioned: bool


@dataclass
class Model:
    analysis: Analysis
    parameters: dict[str, Parameter]
    forms: dict[str, LinearForm]  # datum id -> linear form
    tree: list[TreeEdge]
    results: list[Result]
    roots: dict[str, str]  # axis -> root datum id
    radius: dict[int, LinearForm]  # item index -> radius (or diameter/2) form
    text_links: dict[int, list[tuple[str, str, int]]]  # item -> [(token, param or datum ref, decimals)]
    warnings: list[str] = field(default_factory=list)

    def defaults(self) -> dict[str, float]:
        return {p.name: p.value for p in self.parameters.values()}
