# Drawing understanding and formula binding — a design

How to turn a multi-view engineering drawing into per-view states that a multimodal LLM can reason over, and how
to bind parameters and formulas to the exact geometry without the model ever becoming the source of a number.

Written 2026-10-12 for dxf-autoparam (DXF-first, Gemini on Vertex AI). §10 maps every part onto the code that
exists today and names the gaps. External capabilities are cited in §11 and kept apart from design choices, which
are mine and are marked **Design**.

---

## The direct answer

**What to create for each view.** Build a **View State**: a typed graph whose authority is the source geometry,
not a picture. It holds:

- **Frames and transforms.** Pixel, page (sheet), view-local and model frames, with explicit 3×3 matrices between
  them and the view's scale and units.
- **Entities.** Every primitive with a stable ID, its exact parameters, the line class (visible, hidden, centre, dimension) and its provenance.
- **Datums.** The set-out lines, axes and centres that entities share: the vocabulary dimensions refer to.
- **Features.** Closed profiles, holes, slots and patterns, built from entities.
- **Annotations.** Every dimension as a *measurement between two loci* ("the centre of `C1`", "the line of `L4`",
  "the −y quadrant of `A1`"), with its parsed text, role markers and tolerance. Each one also records how it was
  associated with those loci, and how good that association is.
- **A relation index.** Precomputed facts: what lies on one line, equal sizes, mirror pairs, projection
  correspondences with other views.
- **Ambiguities.** Kept as explicit records, never silently resolved.

The image is a rendering of this state, not a second source.

**What to send the LLM.**

- *Always:* a per-view crop rendered from the state, with Set-of-Mark ID labels drawn on it; a compact text digest
  of the same state (features, datums and dimensions with parsed values); for every dimension, the candidate
  bindings the deterministic associator found, each with its evidence; the closed list of IDs it may use; the
  output schema.
- *On demand, through read-only tools:* exact properties, measurements between loci, detail crops, projections into
  another view, and a dry-run of the validator.
- *Never:* raw full-precision dumps, raw DXF, drawing text as instructions, or any channel through which a number
  the model writes becomes geometry.

**What the LLM returns.** *Proposals*, never coordinates:

- typed records that reference existing IDs only: parameter bindings, constraints, formulas, view correspondences;
- explicit `unresolved` records listing the remaining candidates and the evidence that would separate them.

A deterministic pipeline turns those proposals into geometry:

1. The validator checks each proposal.
2. A policy, or a person, accepts it into a ledger.
3. A compiler turns the accepted ledger into a constraint graph.
4. A solver, or closed-form regeneration, produces the geometry.
5. A comparator checks that the result, with no parameter changed, reproduces the source.

This is option **E** of §2.4: parameter bindings plus a constraint graph. The geometry-edit program is compiled from
that graph and never written by the model.

---

## 1. Assumptions and accuracy limits

### 1.1 Input cases

| Case | What you really have | What is lost | What is authoritative |
|---|---|---|---|
| **A. Native CAD** (DXF/DWG, STEP AP242 with PMI) | Typed entities (LINE, ARC, CIRCLE, LWPOLYLINE, DIMENSION…) with exact coordinates, layers, linetypes, handles. DIMENSION entities carry definition points and the measured value. Associative dimensions may carry a link to the geometry they measure. | Design intent (which size drives); often associativity (dimensions exploded or made non-associative); sometimes text-override values that no longer match the geometry. | Geometry coordinates. Native dimension definition points. Native associations where present. |
| **B. Vector PDF / SVG** | Paths (lines, cubic Béziers, rectangles), dash patterns, colours, and text spans with boxes — unless the text was outlined. | Entity types (a circle arrives as ≥4 Béziers), dimension objects (always exploded), layers (sometimes recoverable from optional content), text when outlined, the model scale (only the page scale exists). | Path coordinates up to the page transform; text strings when they are real text. Everything semantic is reconstructed. |
| **C. Raster / scan** | Pixels. | Everything structural. | Nothing geometric. The *dimension text*, once OCR'd and confirmed, is the only authoritative numeric source; positions are measured with pixel-level uncertainty. |
| **D. Mixed** | Authoritative geometry plus visual-only annotations: markups, scanned stamps, a raster detail pasted into a DXF. | The registration between the two. | Geometry from the native part. Annotation values only after registration and confirmation. |

**Assumption.** The primary target is case A: DXF GADs, many of them generated, some converted from PDF (the BRG
NO.80 file is a PDF→DXF conversion, so it is case A in format but case B in content). Cases B and C are designed
for, but are later milestones (§8).

### 1.2 What "accurate" means, layer by layer

| Layer | Question it answers | A — native | B — vector | C — raster |
|---|---|---|---|---|
| Source geometry | Are the coordinates true? | Exact as stored. A drafting error is still "exact". | Exact up to the PDF transform and the producer's rounding. | Measured: ±(1–2 px) × mm per px × scale. |
| Extraction | Did we read every primitive correctly? | Lossless for supported types. Proxy, unknown and custom entities must be counted and reported, never dropped silently. | Exact for paths. Arcs and circles need a fit from Béziers (fit residual reported). Text exact when present, OCR otherwise. | Detection precision/recall plus localisation error. |
| View segmentation | Which entities form which view? | Deterministic; only ambiguous where views touch or share titles. | Same as A. | Same as A, but on detected primitives. |
| Annotation interpretation | What does "2X Ø10 THRU" mean? | Text exact (MTEXT codes decoded); grammar parse deterministic. | Same as A when text is real; OCR when outlined. | OCR. Must be confirmed. |
| Dimension association | Which two loci does a dimension measure? | Exact when native associativity exists. Otherwise near-exact by definition-point snapping (§3.4). | Reconstructed from arrowheads, extension lines and text placement: heuristic. | Heuristic, on measured primitives. |
| Cross-view correspondence | Which entities are the same model feature? | Deterministic projection alignment (shared coordinates in exact geometry). | Same as A. | Approximate alignment with tolerance. |
| Formula binding | Is parameter P bound to the right property of the right entity? | **Never guaranteed by extraction.** Validated: the bound value must reproduce the authoritative dimension and the source geometry. | Same as A. | Validated against dimension text only. |
| Constraint solving | Does the solved geometry satisfy the accepted constraints? | Numerically exact to solver tolerance (or closed form). | Same as A. | Same as A. |
| Output geometry | Does the result match the source, and the intent after a change? | Identity regeneration to ~1e-6 × extent; a change checked by measuring the result. | Same as A at extraction tolerance. | Only the dimension values are guaranteed. Undimensioned geometry is "measured" and flagged. |

Two things are never guaranteed, whatever the input:

- **Design intent.** Which dimension drives, which end moves. It can be proposed, supported by evidence, and
  confirmed by a person; it cannot be read off the drawing.
- **The drawing's own correctness.** A drawing can state a dimension its geometry contradicts. The system detects
  and reports the conflict; it never decides it silently.

### 1.3 Value classes — every number carries one

| Class | Meaning | Example | Can drive geometry? |
|---|---|---|---|
| `authoritative` | Read from native geometry or a native association, exactly. | A circle's radius from DXF: 5.000000. | Yes, as the identity value. |
| `stated` | Written on the drawing (dimension text, a note), parsed and associated. | "Ø10" → 10 mm on `C1`'s diameter. | Yes, once the binding is accepted. |
| `measured` | Computed from geometry that has no statement. Exact for vector geometry, ±σ for raster. | The gap 46→54 on an undimensioned feature. | Only as the current value of an un-stated parameter, flagged. |
| `inferred` | Produced by a rule or by the LLM: symmetry, equality, "the slot stays on the hole centre line". | `C1`, `C2` mirror about `CL2`. | Only after acceptance, with recorded evidence. |
| `assumed` | A default nobody stated (e.g. first-angle projection). | Projection system. | Never silently; it must appear in the review. |
| `unknown` | No evidence. | The hole depth when no view shows it. | No. It stays a hole in the model. |

**Confidence is not validation.** A confidence score ranks candidates for review. It never admits a proposal to
the accepted ledger. Only the deterministic checks of §6 can do that, sometimes together with a person.

---

## 2. Architecture and responsibility boundaries

### 2.1 Components

```
 source file ──► [1 Ingest adapter: DXF | AP242 | PDF | raster] ──► Primitive store (entities, IDs, provenance)
                                                                          │
              [2 Sheet segmenter] ──► View registry (views, titles, frames, scale, units, transforms)
                                                                          │
              [3 Topology & feature builder] ──► datums, loops, features, patterns
              [4 Annotation interpreter] ──► dimensions as measurements between loci; text grammar; leaders
              [5 Dimension associator] ──► candidate loci per dimension, with method and quality
              [6 Correspondence engine] ──► projection links, section/detail callouts, feature pairs across views
              [7 Relation index] ──► collinear, concentric, equal, mirror, coincident facts (exact or measured)
                                                                          │
                                            View State (one per view, versioned) ◄────────┐
                                                                          │                │
 [8 Render service] ──► crops + Set-of-Mark overlays ──┐                  │                │
                                                       ▼                  ▼                │
                         [9 LLM binding session] ◄──► [10 Read-only query tools + dry-run validator]
                                     │ proposals (IDs only)                                │
                                     ▼                                                     │
                         [11 Proposal ledger]  proposed → validated → accepted / rejected / stale
                                     │ accepted only                                       │
                         [12 Validator] (schema, refs, units, expressions, cycles, rank/DOF,
                                     │    agreement, cross-view, regeneration identity, perturbation)
                                     ▼                                                     │
                         [13 Constraint compiler] ──► constraint graph (per axis DAG + local solver blocks)
                                     ▼                                                     │
                         [14 Solver / regenerator] ──► new coordinates ──► [15 Comparator] ─┘ (new revision)
                                     ▼
                         [16 Writer] (edit the source DXF in place / build a CAD model) ──► [17 Review UI]
```

### 2.2 Contracts

| # | Input | Output | Invariants |
|---|---|---|---|
| 1 Ingest | file bytes, adapter options | `Primitive[]` (kind, exact params, layer, linetype, colour, `src` handle path), a `Document` (units, header), an `extraction_report` (unsupported, proxy and skipped entities with counts) | Nothing dropped silently. Every primitive carries `src` and an `adapter@version`. |
| 2 Segmenter | primitives | `View[]`: member IDs, bbox, title, type candidates, scale candidates, `questions[]` | Non-destructive. Uncertain views are offered as candidates, not forced. |
| 3 Features | view members | `Datum[]`, `Feature[]`, topology (loops, adjacency, coincident groups) | Datums keyed by their defining entities (stable), not by order. |
| 4 Annotations | view members, document text styles | `Annotation[]` with parsed text (`value`, `kind`, `count`, `tolerance`, `role markers`) | Raw text is kept. The parse never runs code. |
| 5 Associator | annotations, datums, features | per dimension: `loci[2]`, `candidates[]` (each `{target, method, quality, residual}`) | Never picks by value coincidence alone (§3.4). |
| 6 Correspondence | ≥ 2 views | `Correspondence[]` (view pair, axis map, transform, member pairs, residual, strength) | Strong links need ≥ k shared planes (§3.6). Weak ones are offered, not taken. |
| 7 Relations | view state | facts with `exact`/`measured` and their tolerance | Facts are observations, not constraints, until accepted. |
| 8 Render | view state, region, overlay spec, px per mm | PNG + `crop_transform` (page→pixel) + `label_map` (label → ID) | Labels are drawn from geometry, so the same ID gets the same label in every crop. |
| 9 LLM session | package of §4 | `Proposal[]` (schema of §5) | IDs from the closed list only. No coordinates. Values only by reference to annotations. |
| 10 Tools | typed queries | typed answers, plus dry-run reports | Read-only. Deterministic. Logged. |
| 11 Ledger | proposals, validation results, decisions | ledger revision | Only `accepted` entries are visible to the compiler. |
| 12 Validator | ledger snapshot plus view states | `ValidationReport` (§6.3) | Pure function of its inputs. Reproducible. |
| 13 Compiler | accepted ledger | constraint graph, dependency order, DOF report | Rejects cycles. Every equation traces to a ledger entry. |
| 14 Solver | graph, values | coordinates per entity point, residuals | Starts from source geometry. Checks orientation invariants. |
| 15 Comparator | source vs regenerated | identity error, changed set, per-dimension measured values | Identity must hold before any change is accepted. |
| 16 Writer | regenerated coordinates, source file | edited file plus an audit report | Writes only changed entities. Re-renders dimension text from measurement. |

### 2.3 Who decides what

| Responsibility | Owner | The LLM must not |
|---|---|---|
| Reading primitives, coordinates, units, scale candidates | Ingest + segmenter | — |
| Parsing dimension text ("2X Ø10 THRU", "R5 TYP", "(60)", "25±0.1") | Deterministic grammar; OCR for C | Re-read numbers off the image when parsed text exists. |
| Associating a dimension with loci | Associator (methods ranked §3.4) | Invent a target the associator did not list. It may only *choose* among candidates, or call `unresolved`. |
| What a view *is* (plan, section A-A, detail B) and which views relate | LLM proposes; segmenter and correspondence engine supply the evidence | Merge views without a correspondence record. |
| Which dimensions drive and what to call them (design intent) | LLM proposes; rank check verifies independence | Mark a reference dimension "(60)" as driving. |
| Formulas between parameters | LLM proposes; parser, unit checker and agreement check verify | Write coordinates, or expressions outside the grammar. |
| Constraints implied by convention (symmetry about a drawn centre line, concentricity) | Relation index observes; LLM proposes; policy accepts | Assert one with no observation behind it. |
| Solving and regenerating | Solver / closed-form regenerator | — |
| Accepting conflicts, design-intent choices, unresolved items | Human (review UI) | — |

### 2.4 What the LLM should return

| Option | Accuracy | Traceability | Failure mode | Verdict |
|---|---|---|---|---|
| A. Final coordinates | Worst: numbers re-derived by a model, with transcription and arithmetic errors | None: a coordinate has no "why" | Plausible-looking wrong geometry | Reject. |
| B. Parameter bindings only | Good for sizes | Good | Leaves topology and positioning implicit; under-constrained geometry | Necessary, not sufficient. |
| C. Constraint graph | Good | Good | Large surface for the model; still needs a solver | Use as the *compiled* form, not the model's raw output. |
| D. Geometry-edit program (e.g. a CAD script) | Varies | Medium | Executes model-written code; hard to validate partially | Generate it deterministically *from* C, never from the model. |
| **E. B + typed constraint/formula proposals referencing IDs, compiled to C, then D** | Best | Every equation traces to a proposal, its evidence and its source annotation | Wrong or unknown targets are caught by closed-world and agreement checks | **Recommend.** |

The model's output space is deliberately small:

- *choose* a candidate for a dimension, or mark it unresolved;
- *name* a parameter;
- *state* a relation between existing parameters;
- *propose* a constraint between existing IDs;
- *propose* a cross-view correspondence where the engine found more than one plausible.

---

## 3. The per-view state

### 3.1 Candidate representations compared

| Representation | Model can see the drawing | Exactness | Can reference entities | Token cost | Verdict |
|---|---|---|---|---|---|
| Image only | yes | none (pixel estimates) | no IDs | low | Insufficient: no grounding, coordinates estimated. |
| Image + prose description | yes | prose numbers drift | weak | medium | Still no closed ID set. |
| Image + structured geometry | yes | exact | yes, if both share IDs | high for big views | Good if the image is labelled with the same IDs. |
| Entity graph (scene graph) | no | exact | yes | medium | Strong for relations; weak for "what is this view". |
| Constraint graph | no | exact | yes | low | The *target* form, not an input: the drawing has no constraints until someone asserts them. |
| **Hybrid: entity graph + datums + annotation graph + relation index + rendered image with ID marks + tools** | yes | exact | yes, closed world | controlled by digest + tools | **Recommend.** |

### 3.2 Coordinate frames and transforms

Four frames per view. Every transform is an explicit 3×3 homogeneous matrix with provenance.

| Frame | Origin and axes | Units | Used by |
|---|---|---|---|
| `pixel` (per render) | top-left of the crop, +x right, **+y down** | px | images, overlays, any box the model returns |
| `page` | the sheet origin (DXF modelspace / PDF page user space), +y up | drawing units (DXF) or pt (PDF) | segmentation, rendering |
| `view` | a view datum (e.g. the plate's lower-left corner), +x right, +y up on the sheet | **model mm** (page units × `mm_per_unit` ÷ view scale) | everything the LLM and the validator see |
| `model` | the object's frame, X Y Z | mm | cross-view work, 3D output |

- `page→view`: `T_pv = S(mm_per_unit / k_view) · T(−origin)`. Here `k_view` is how many page units one model unit
  occupies: 1 for a view drawn true-size in DXF modelspace, 1/50 for a 1:50 view drawn at paper size. `k_view` is per
  view, so a detail drawn at another size than its sheet has its own (your sheets already do this, via per-view
  `units_mm`).
- `view→model`: a 3×2 projection map, from the view type and projection system. Top view: x→X, y→Y. Front view:
  x→X, y→Z. Right view: x→Y, y→Z. Under the first-angle vs third-angle convention the *placement* differs but the
  axis map does not. A section view adds its cutting plane.
- `page→pixel` (per crop): `px = (page_x − crop_x0)·k`, `py = (crop_y1 − page_y)·k`, with `k = px_per_unit`. It is
  stored with the image, so a box returned by the model maps back exactly.

Gemini reports boxes as `[ymin, xmin, ymax, xmax]` normalised to 0–1000 (§11). Converting them needs the crop size
*as sent*: after any resize, invert the resize too. Boxes are only used to *find* entities (a spatial query
returning IDs), never as geometry.

### 3.3 Stable IDs

- **Entities.** `"{view}:{kind}{n}"`, minted once by an **ID registry** per document. The primary key is the source
  identity: DXF handle plus block path (`src`), the PDF content-stream path index, or a raster detection ID. The
  secondary key is a geometric signature: kind, canonical parameters rounded to the source tolerance, layer and
  linetype, plus the hash of neighbour signatures. IDs are never reused once retired (tombstones).
- **Datums.** Identified by their *defining set*: the sorted IDs of the entities or loci that lie on them, plus the
  axis. They are not identified by order. Today's ordinal datum names (`x105`, `y170`) change whenever a line is
  added before them. That is the most important gap to close (§10).
- **Dimensions and annotations.** By source handle. An exploded dimension (a line, two ticks and a text) gets a
  synthetic ID from the IDs of its parts.
- **Re-extraction after an edit or a new revision of the file.** Match old to new by handle first. Then use a
  one-to-one assignment on signature distance, under the source tolerance (Hungarian), for the rest. Unmatched old
  IDs are tombstoned, unmatched new ones are minted, and every re-identification is logged with its method.
- **Crops and transformations.** IDs belong to entities, not to pixels. Overlays are drawn from the state through
  the crop transform, so any crop shows the same label for the same entity. A regeneration moves coordinates but
  keeps IDs.
- **Repeated LLM calls.** The same strings are used in every call. A call's whitelist is the ID set of the view-state
  revision it was given, so a proposal referencing anything else is rejected (`E_UNKNOWN_ID`).

### 3.4 Dimension association — the step most errors come from

A dimension does not measure "an entity". It measures a distance (or an angle, radius or diameter) between two
**loci**, along a direction:

```
locus     := { entity: ID, select: "line" | "start" | "end" | "mid" | "center" | "quadrant:+x|-x|+y|-y" | "tangent:<dir>" | "vertex:<k>" }
           | { datum: ID }
measure   := { kind: "distance", a: locus, b: locus, along: "x" | "y" | "aligned" | {"dir": [ux, uy]} }
           | { kind: "radius" | "diameter", of: { entity: ID } }
           | { kind: "angle", a: {entity: ID, select: "line"}, b: {entity: ID, select: "line"}, sector: "a→b ccw" }
```

Association methods, strongest first. Each candidate records which one produced it:

1. **Native association.** A DXF `DIMASSOC` object, where present, links each point reference to the referenced
   geometry by object handle and osnap type (endpoint, midpoint, center, quadrant…). STEP AP242 semantic PMI ties
   dimensions to faces. Quality: `exact`.
2. **Definition point on a locus.** Snap each extension-line origin (ezdxf `defpoint2`, `defpoint3`) to points of
   interest (vertices, centres, quadrants) *and* to lines. For an axis-aligned dimension, only the measured axis
   matters: snap to the *datum* the point lies on along that axis. The same rule applies to a point that lies on a
   line but on no drawn vertex, such as a wall dimensioned along the slab beneath it. That case was today's live
   bug: it followed the nearest corner instead. Quality: `exact` if the residual is ≤ `tol_geom` and the locus is
   unique; `ambiguous` if several loci tie.
3. **Exploded-dimension reconstruction.** Find a dimension line (a straight run whose ends sit on two datums), with
   ticks or arrows and a number beside it. Then the extension-line feet. Quality: `reconstructed`, with the residual.
4. **Text-only proximity.** A number near a gap of the same length. Quality: `weak`. Never auto-accepted.

**Do not associate by value.** Two different sizes can share a value: a 1350 wall height and a 1350 toe width
caused the earlier wing-wall bug. Association is by loci. The value only *confirms*: `|measured − stated| ≤ tol_text
+ tol_geom`.

### 3.5 Line classes and roles

`visible`, `hidden` (dashed, used to infer through-features), `center` (chain; symmetry and axis evidence),
`phantom`, `dimension`, `extension`, `leader`, `section-cut`, `hatch`, `border/title` (furniture, fixed). Classify
from layer, linetype and colour, then from geometry (a dashed run ending on a solid outline). Record the method, as
in `"class": {"value": "hidden", "by": "linetype:DASHED"}`.

### 3.6 Cross-view correspondence

Run deterministically first:

1. **Projection alignment.** Collect each view's datum coordinates along the shared axis: top-view x and front-view
   x share model X. Use only "faces", i.e. datums with substantial drawn length, so chance alignments of short
   lines don't count.
2. Find the 1D offset that maximises the coincident planes.
3. Accept a link as `strong` if `planes ≥ 6 and fraction ≥ 0.25`, or `planes ≥ 4 and fraction ≥ 0.6`. These are the
   thresholds already in `crossview.view_links`. Otherwise record it as `weak` for review.
4. **Feature pairing.** A circle of diameter d at x = c in the top view corresponds to a pair of hidden or visible
   lines at c ± d/2 in the front view, plus a centre line at c. The pairing is one-to-many when several features
   share an x: both holes on one centre line project onto the same front-view lines. That is not an error, and it
   is recorded as such.
5. **Sections and details.** A cutting-plane line labelled "A-A" maps to the view titled "SECTION A-A". A detail
   circle labelled "B" maps to "DETAIL B", which has its own scale.

The LLM confirms ambiguous correspondences or chooses between them. It never creates a link that the alignment
residual contradicts.

### 3.7 JSON Schema (abridged to the load-bearing fields)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://aagento.local/schemas/view-state/1.2.0",
  "title": "ViewState",
  "type": "object",
  "required": ["schema", "schema_version", "doc", "revision", "view", "units", "frames", "entities", "datums", "annotations"],
  "properties": {
    "schema": { "const": "view-state" },
    "schema_version": { "type": "string", "pattern": "^1\\.\\d+\\.\\d+$" },
    "doc": { "type": "object", "required": ["doc_id", "sha256", "adapter"],
             "properties": { "doc_id": {"type": "string"}, "sha256": {"type": "string"}, "adapter": {"type": "string"} } },
    "revision": { "type": "object", "required": ["n", "content_hash"],
                  "properties": { "n": {"type": "integer", "minimum": 0}, "content_hash": {"type": "string"}, "parent": {"type": ["string", "null"]} } },
    "view": { "type": "object", "required": ["id", "kind", "bbox_page"],
      "properties": {
        "id": {"type": "string"},
        "kind": {"enum": ["view", "table", "notes", "title_block"]},
        "title": {"type": ["string", "null"]},
        "type_candidates": {"type": "array", "items": {"type": "object",
          "properties": {"type": {"enum": ["front", "top", "side", "plan", "elevation", "section", "detail", "isometric", "auxiliary", "unknown"]},
                         "evidence": {"type": "array", "items": {"type": "string"}}}}},
        "projection": {"type": "object", "properties": {"system": {"enum": ["first_angle", "third_angle", "unknown"]},
                       "axis_map": {"type": "object", "properties": {"x": {"enum": ["X", "-X", "Y", "-Y", "Z", "-Z"]}, "y": {"enum": ["X", "-X", "Y", "-Y", "Z", "-Z"]}}},
                       "value_class": {"$ref": "#/$defs/value_class"}}},
        "bbox_page": {"$ref": "#/$defs/bbox"}
      } },
    "units": { "type": "object", "required": ["view_unit", "mm_per_page_unit", "scale"],
      "properties": { "view_unit": {"const": "mm"}, "angle_unit": {"const": "deg"},
                      "mm_per_page_unit": {"type": "number", "exclusiveMinimum": 0},
                      "scale": {"type": "object", "properties": {"factor": {"type": "number"}, "stated": {"type": ["string", "null"]},
                                "verified_by": {"type": "array", "items": {"type": "string"}}, "value_class": {"$ref": "#/$defs/value_class"}}},
                      "tol_geom_mm": {"type": "number", "minimum": 0} } },
    "frames": { "type": "object", "required": ["page_to_view", "view_to_model"],
      "properties": { "page_to_view": {"$ref": "#/$defs/mat3"}, "view_to_model": {"type": "array", "minItems": 3, "maxItems": 3,
                      "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}} } },
    "entities": { "type": "array", "items": {"$ref": "#/$defs/entity"} },
    "datums": { "type": "array", "items": {"$ref": "#/$defs/datum"} },
    "features": { "type": "array", "items": {"$ref": "#/$defs/feature"} },
    "annotations": { "type": "array", "items": {"$ref": "#/$defs/annotation"} },
    "relations": { "type": "array", "items": {"$ref": "#/$defs/relation"} },
    "correspondences": { "type": "array", "items": {"$ref": "#/$defs/correspondence"} },
    "ambiguities": { "type": "array", "items": {"$ref": "#/$defs/ambiguity"} }
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[A-Z][A-Z0-9]*:[A-Z]{1,3}[0-9]+$"},
    "bbox": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}},
    "mat3": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}},
    "value_class": {"enum": ["authoritative", "stated", "measured", "inferred", "assumed", "unknown"]},
    "num": {"type": "object", "required": ["v", "class"],
            "properties": {"v": {"type": "number"}, "class": {"$ref": "#/$defs/value_class"}, "sigma": {"type": "number", "minimum": 0},
                           "src": {"type": "array", "items": {"type": "string"}}}},
    "entity": {"type": "object", "required": ["id", "kind", "geom", "src", "line_class"],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "kind": {"enum": ["line", "arc", "circle", "polyline", "ellipse", "spline", "point", "text", "hatch", "insert"]},
        "geom": {"type": "object", "description": "kind-specific exact parameters in VIEW frame mm: line {a,b}; circle {c,r}; arc {c,r,a0,a1}; polyline {pts,bulges,closed}"},
        "line_class": {"type": "object", "properties": {"value": {"enum": ["visible", "hidden", "center", "phantom", "dimension", "extension", "leader", "section_cut", "hatch", "furniture"]},
                                                         "by": {"type": "string"}}},
        "layer": {"type": "string"},
        "src": {"type": "object", "required": ["adapter", "ref"], "properties": {"adapter": {"type": "string"}, "ref": {"type": "string"}}},
        "value_class": {"$ref": "#/$defs/value_class"},
        "sigma_mm": {"type": "number", "minimum": 0}
      } },
    "datum": {"type": "object", "required": ["id", "axis", "value", "defined_by"],
      "properties": {"id": {"$ref": "#/$defs/id"}, "axis": {"enum": ["x", "y", "point", "axis"]}, "value": {"$ref": "#/$defs/num"},
                     "defined_by": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/locus"}},
                     "faces": {"type": "number", "description": "drawn length on it / view extent"}} },
    "locus": {"oneOf": [
      {"type": "object", "required": ["entity", "select"], "properties": {"entity": {"$ref": "#/$defs/id"},
        "select": {"type": "string", "pattern": "^(line|start|end|mid|center|vertex:[0-9]+|quadrant:[+-][xy]|tangent:[+-][xy])$"}}},
      {"type": "object", "required": ["datum"], "properties": {"datum": {"$ref": "#/$defs/id"}}}]},
    "feature": {"type": "object", "required": ["id", "kind", "members"],
      "properties": {"id": {"$ref": "#/$defs/id"}, "kind": {"enum": ["profile", "hole", "hole_group", "slot", "pattern", "chamfer", "fillet", "member", "unknown"]},
                     "members": {"type": "array", "items": {"$ref": "#/$defs/id"}}, "params": {"type": "object", "additionalProperties": {"$ref": "#/$defs/num"}},
                     "instances": {"type": "array", "items": {"type": "object"}}} },
    "annotation": {"type": "object", "required": ["id", "kind", "text"],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "kind": {"enum": ["dimension", "leader_note", "note", "gdt", "symbol", "title", "level"]},
        "text": {"type": "object", "required": ["raw"], "properties": {"raw": {"type": "string"}, "plain": {"type": "string"},
                 "parsed": {"type": "object", "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "decimals": {"type": "integer"},
                            "prefix": {"enum": ["", "Ø", "R", "SR", "SØ", "M"]}, "count": {"type": "integer"}, "suffixes": {"type": "array", "items": {"type": "string"}},
                            "tolerance": {"type": "object"}, "markers": {"type": "array", "items": {"enum": ["reference", "basic", "typical", "not_to_scale", "override"]}}}}}},
        "dimension": {"type": "object", "properties": {
          "dimtype": {"enum": ["linear", "aligned", "angular", "radius", "diameter", "ordinate", "arc_length"]},
          "measure": {"type": "object", "description": "the measure grammar of §3.4"},
          "native_measurement": {"type": ["number", "null"]},
          "candidates": {"type": "array", "items": {"type": "object", "required": ["cid", "measure", "method", "quality", "residual_mm"],
            "properties": {"cid": {"type": "string"}, "measure": {"type": "object"}, "method": {"enum": ["native_assoc", "defpoint_snap", "exploded_reconstruct", "text_proximity", "ocr_layout"]},
                           "quality": {"enum": ["exact", "ambiguous", "reconstructed", "weak"]}, "residual_mm": {"type": "number"}}}}}}
      } },
    "relation": {"type": "object", "required": ["id", "kind", "refs", "class"],
      "properties": {"id": {"type": "string"}, "kind": {"enum": ["on_datum", "collinear", "concentric", "equal_size", "mirror", "parallel", "perpendicular", "tangent", "pattern"]},
                     "refs": {"type": "array", "items": {"type": "object"}}, "class": {"enum": ["exact", "measured"]}, "residual_mm": {"type": "number"}}},
    "correspondence": {"type": "object", "required": ["id", "views", "axis", "pairs", "strength"],
      "properties": {"id": {"type": "string"}, "views": {"type": "array", "minItems": 2, "maxItems": 2}, "axis": {"enum": ["X", "Y", "Z"]},
                     "offset_mm": {"type": "number"}, "pairs": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2}},
                     "planes": {"type": "integer"}, "fraction": {"type": "number"}, "strength": {"enum": ["strong", "weak", "accepted", "refused"]}}},
    "ambiguity": {"type": "object", "required": ["id", "about", "options", "would_resolve"],
      "properties": {"id": {"type": "string"}, "about": {"type": "string"}, "options": {"type": "array", "minItems": 2},
                     "would_resolve": {"type": "string"}}}
  }
}
```

**Versioning.**

- `schema_version` is semver. A *minor* bump adds optional fields; readers ignore unknown fields. A *major* bump
  changes meaning and needs a migration.
- Every view state carries `revision.n`, `revision.content_hash` and its parent hash.
  - The content hash covers the authoritative parts: entities' geometry and class, annotations, datums' defining
    sets.
  - It excludes derived caches (relations, rendered images).

A complete example of one view state is in §7.2.

---

## 4. Multimodal input strategy

### 4.1 What goes where

| Input | Always | On demand | Never in context | Why |
|---|---|---|---|---|
| Whole-sheet overview at low resolution, with view boxes | ✓ (sheet stage only) | | | Views, titles and layout; ~280–560 tokens at `low`/`medium` (§11). |
| Per-view crop, rendered from the state | ✓ | | | What the view *is*: the conventions, the feature shapes. `high` = 1120 tokens. |
| Set-of-Mark overlay of the same crop (entity, datum and dimension labels) | ✓ | | | Grounds the image in the closed ID set (SoM, §11). Sent as a *second* image, so labels never hide drawing text. |
| Detail crop of one region at higher px per mm | | ✓ `render(region)` | | Small text, dense dimension chains; `ultra_high` only per item. |
| View digest (text) | ✓ | | | Features, datums, dimensions with parsed values, candidate bindings, relations. |
| Exact coordinates of every entity | | ✓ `get(ids, fields)` | | Most reasoning doesn't need them; the relation index replaces them. |
| Measurements between loci | | ✓ `measure(a, b, along)` | | Lets the model check its own hypotheses without arithmetic. |
| Projection of a locus into another view | | ✓ `project(locus, view)` | | Cross-view reasoning on demand. |
| Dry-run validation of proposals | | ✓ `check(proposals)` | | The model sees exact failures before committing. |
| Raw DXF, full-precision dumps, other sheets | | | ✓ | Cost; and raw text is an injection channel. |
| Drawing text as instructions | | | ✓ | Text is quoted as *data* (`DATA_RULE`). |

### 4.2 One rendering, one ID set

- Render from the view state, not from the original file's raster. Labels are then placed from the state's own
  geometry: midpoint of a line, centre of a circle, beside a dimension's text.
- Colour by class: structure, datum (thin cyan lines with `X3`), dimension (`D4` boxed at its text).
- Placement avoids collisions; when a label is moved off its anchor, a short leader keeps it attached.
- The digest uses the *same* labels. Within a single-view crop, the short label (`C1`) stands for the full ID
  (`TV:C1`); the digest header states the prefix.
- The render returns the `label_map` and the `crop_transform`; both are stored with the call record.

### 4.3 Does the model need all the coordinates?

No. Models reason better over *relations and references* than over lists of numbers, and arithmetic over many
numbers is where they make transcription errors. Send instead:

- each feature's key parameters (a hole's diameter, a slot's width and centres);
- each dimension's parsed value and candidate loci;
- the relation index: on one datum, equal sizes, mirror pairs.

Exact coordinates come from `get`/`measure` when a decision depends on them. On a 50-entity view the digest is a
few thousand tokens. On a 5,000-entity view (a full GAD unit) it would be tens of thousands, so large views are
summarised:

- features with members collapsed;
- dimension chains grouped;
- repeated members as one pattern record;
- with tools for the rest.

### 4.4 Numbers, units, precision

- **Canonical units.** View and model frames in **mm**. Angles shown in **degrees** and stored internally in
  radians. Conversion happens once, at ingestion: from DXF `$INSUNITS` or the per-view inferred unit (§10), and for
  text with explicit units through a units library (Pint parses quantities and refuses dimension-mismatched
  conversions, §11).
- **Serialisation.** In the digest, print `authoritative` numbers at the source tolerance: `20` not `20.000000001`
  when `tol_geom` = 1e-6 × extent. The full value stays server-side.
- **Mark every number's class.** `measured` numbers carry `±σ`; `stated` numbers carry their source annotation ID,
  e.g. `Ø10 [stated D3]`, `46 [authoritative]`, `≈20.4±0.6 [measured, raster]`.
- **The model never sends a number that becomes geometry.** A parameter's value comes from the annotation it is
  bound to, or from the current geometry. A literal in a formula (the `2` in `W − 2·e`) is allowed. Its units are
  checked, and the agreement check verifies the whole expression against authoritative geometry.

### 4.5 Large drawings and context

- Run in stages, each its own call with its own small context:
  1. sheet: views, titles, relations;
  2. per unit (views linked in projection): bindings;
  3. across units: shared sizes.
  This is what `sheet_ai.py` already does.
- Within a unit, cache the shared prefix (system rules, images, digest) with an explicit prompt cache, and send
  only deltas per step.
- Deduplicate: exploded block content, hatch boundaries, and repeated members as one pattern with instances.

---

## 5. The formula-binding schema

### 5.1 A binding record

```json
{
  "id": "B-TV-0007",
  "rev": 3,
  "status": "proposed",
  "role": "driving_parameter",
  "parameter": { "name": "HoleOffsetX", "dim_type": "length", "unit": "mm" },
  "target": {
    "measure": { "kind": "distance", "a": { "datum": "TV:X0" }, "b": { "datum": "TV:X1" }, "along": "x" },
    "frame": "TV.view"
  },
  "expression": null,
  "value_source": { "annotation": "TV:D4", "candidate": "D4/c1" },
  "depends_on": [],
  "evidence": [
    { "kind": "association", "detail": "D4 defpoints snap exactly to X0 (L4 line) and X1 (C1 centre)", "refs": ["TV:D4", "TV:L4", "TV:C1"] },
    { "kind": "agreement", "detail": "measured 20 vs stated 20, residual 0" }
  ],
  "assumptions": [],
  "alternatives": [],
  "proposed_by": { "agent": "binding-session", "model": "<model id>", "call": "c-0192", "base_view_revision": { "TV": 4, "FV": 2 } },
  "validation": { "status": "pending", "report": null }
}
```

A formula binding sets `role: "formula"`. It gives an `expression` and `depends_on`, and it binds the *result* to a
target or to a derived parameter:

```json
{ "id": "B-TV-0011", "role": "derived_parameter",
  "parameter": { "name": "HolePitch", "dim_type": "length", "unit": "mm" },
  "expression": { "text": "PlateWidth - 2*HoleOffsetX" },
  "depends_on": ["PlateWidth", "HoleOffsetX"],
  "target": { "measure": { "kind": "distance", "a": { "entity": "TV:C1", "select": "center" }, "b": { "entity": "TV:C2", "select": "center" }, "along": "x" } },
  "checks": [{ "annotation": "TV:D8", "as": "reference" }] }
```

**Expression grammar** (parsed server-side, never evaluated as code):

```
expr  := term (("+" | "-") term)*
term  := unary (("*" | "/") unary)*
unary := "-" unary | power
power := atom ("^" integer)?
atom  := number | NAME | func "(" expr ("," expr)* ")" | "(" expr ")"
func  := min | max | abs | sqrt | round | sin | cos | tan | atan2      (angles in degrees at the boundary)
NAME  := a declared parameter of the same scope or a shared parameter
```

The server parses it with a whitelist (the Python `ast` approach `program.py` already uses: only
`BinOp`/`UnaryOp`/`Constant`/`Name`/whitelisted `Call` nodes, then compiling the *validated* AST). Do **not** use
SymPy's `sympify` on model output; its documentation warns that it uses `eval` (§11).

Dimensional analysis runs on the AST: `length ± length → length`, `length·length → area`, `sin(angle) → ratio`,
and `count` must be an integer. A mismatch fails with `E_DIM_TYPE`.

### 5.2 The six kinds of thing a number on a drawing can be

| Kind | What it is | In the ledger | Drives geometry? |
|---|---|---|---|
| **Displayed dimension** | An annotation object with text and loci | `annotation` (evidence only) | Never by itself. |
| **Driving parameter** | An independent variable, chosen from the stated dimensions | `role: driving_parameter` with `value_source` = that annotation | Yes. |
| **Derived measurement** | Computed from geometry or other parameters; includes reference dimensions "(60)" | `role: derived_parameter` / `reference_check` | No. It is *checked*. |
| **Geometric constraint** | Non-numeric: on, parallel, perpendicular, concentric, equal, mirror, tangent | `role: constraint` with `refs` | Yes, after acceptance. |
| **Formula** | An equation among parameters | `role: formula` / `derived_parameter` | Yes, through its terms. |
| **Manufacturing annotation** | Tolerance, fit (H7), surface finish, GD&T frame, thread class, "DEBURR", "THRU" | `attribute` on a feature | Never. "THRU" and thread *nominal size* inform geometry through the feature, not as drivers. |

### 5.3 The hard cases, rule by rule

- **Radius vs diameter.**
  - The dimension type (DXF dimtype 3 = diameter, 4 = radius) or the text prefix (`Ø`, `R`) decides the property:
    a `diameter` measure binds to `diameter`, a `radius` measure to `radius`.
  - A parameter named for the other quantity binds through an expression (`radius = HoleDia/2`), never by copying
    the value.
  - Validator rule `E_PROPERTY_KIND`: a diameter annotation bound to `radius` without a `/2` path fails, and the
    agreement check fails too (§7.7).
- **Edge distance vs centre distance.** Decided by the loci's `select`: `center` vs `quadrant`/`tangent`. A
  definition point on the circumference snaps to `quadrant:±x`, so the constraint is `distance(edge, x) =
  centre_offset − r`, written through the circle's own parameter. Never re-derived by the model.
- **Repeated holes and patterns.**
  - `2X Ø10` parses to `count = 2, diameter = 10`. It binds *one* parameter to a `hole_group` feature's diameter.
    Instance equality becomes a constraint, and the count is checked against the instances found.
  - A pattern has `count`, `pitch` and an anchor. Changing `count` adds or removes instances: a topology change. The
    writer creates or deletes entities, and the instances get indexed IDs (`TV:C1#1…#n`), so IDs stay stable for the
    survivors.
- **Symmetry.**
  - It is a *constraint* (`mirror(a, b, axis)`). It needs a drawn centre line or axis as the mirror, and an exact or
    measured observation, before it can be proposed.
  - It is never inferred from "looks centred" alone. Without a drawn axis it stays `inferred`, and accepting it
    needs a person or an explicit policy.
- **Angular dimensions.**
  - Bind to `angle(lineA, lineB)` with a `sector`: which of θ, 180°−θ, 180°+θ or 360°−θ.
  - The sector comes from the dimension arc's location (ezdxf `defpoint5` for angular dimensions, §11) or from the
    arc's quadrant.
  - Degrees are shown at the boundary; radians are stored internally.
- **Projected vs true length.**
  - An edge not parallel to the view plane is foreshortened. A dimension is assumed to state *true length* only on
    an `aligned` dimension in a view where the edge is true-size (an auxiliary view, or a line parallel to that
    view's plane, established by cross-view correspondence).
  - In any other view, the validator computes both values. It flags `E_PROJECTED_LENGTH` when the stated value
    matches the projected length but the binding claims true length, or the reverse.
- **Reference dimensions.**
  - Markers: parentheses or "REF" → `role: reference_check`. They are evaluated, never driving. A mismatch beyond
    tolerance becomes a `conflict`, not a failed binding.
  - Basic dimensions (boxed) are exact values, and they are driving.
- **Tolerances.**
  - The parameter takes the *nominal* value; the tolerance is an attribute. Manufacturing tolerance is never used
    as a matching tolerance.
  - Matching tolerance comes from source precision (§6.2). A drawing tolerance of ±0.1 does not let a 20.4
    measurement "match" a stated 20.
- **Conflicting dimensions.** When two stated dimensions disagree after binding (the system's residual exceeds the
  tolerance), keep both. Record a `conflict` with both evidence chains. The binding stays out of the accepted
  ledger until a person decides, or a documented precedence applies (§10: the Aagento dispute precedence).
- **Circular dependencies.** The parameter graph must be a DAG. The compiler runs a topological sort (iterative, as
  `program.order()` already does) and rejects any proposal that closes a cycle, with `E_CYCLE` and the cycle path.
- **Under-constrained.**
  - The DOF report lists free directions, e.g. "datum X6 has no equation", or "the slot can slide along CL2".
  - Free datums keep their current position as an *implicit anchor*, marked as such, so geometry stays generable.
    The review shows them.
  - Which end moves when a size grows is an explicit `anchor` choice, not an accident of formula order.
- **Over-constrained.** Compute the rank of the constraint Jacobian at the current geometry (numeric; exact in
  closed form for axis-aligned datums). A consistent redundant constraint is demoted to `reference_check`, using the
  drafting convention that the overall size or a chain member becomes reference. An inconsistent one becomes a
  `conflict`.

### 5.4 The unresolved state is a first-class answer

When more than one binding stays plausible, the model must return:

```json
{ "id": "U-TV-0002", "status": "unresolved", "about": "TV:D5",
  "options": [
    { "candidate": "D5/c1", "meaning": "hole centre row height", "evidence": ["defpoint3 on CL1, which also carries C1.center and C2.center"] },
    { "candidate": "D5/c2", "meaning": "slot centre height",      "evidence": ["the slot's mid-point lies on CL1"] } ],
  "would_resolve": "Is the slot meant to stay on the hole centre line when HoleRowY changes? (design intent)",
  "safe_default": "bind to datum TV:Y2 (CL1): exact for both readings; record the slot-on-CL1 constraint as inferred, pending review" }
```

The schema makes `unresolved` an allowed result for every dimension, so the model is never forced to guess. Where a
reading exists that is exact for every option (here, binding to the datum they share), the system can apply it
while keeping the semantic question open.

---

## 6. Validation and repair

### 6.1 The checks, in order (each stage gates the next)

| Stage | Check | Error codes |
|---|---|---|
| V0 Schema | JSON Schema of §5, plus the model API's structured-output schema. Structured output guarantees *syntax*, not values (§11). | `E_SCHEMA` |
| V1 References | Every ID exists in the referenced view-state revision; every candidate ID belongs to the annotation it names; `value_source` is a stated annotation. | `E_UNKNOWN_ID`, `E_NOT_A_CANDIDATE`, `E_NO_SOURCE` |
| V2 Kind compatibility | Measure kind vs property (diameter→diameter); axis vs dimension type; angle sectors. | `E_PROPERTY_KIND`, `E_AXIS` |
| V3 Expression | Grammar; names declared; no free numbers other than literals; dimensional analysis. | `E_PARSE`, `E_UNDECLARED`, `E_DIM_TYPE` |
| V4 Dependencies | DAG; no self-reference; a shared parameter has exactly one driver per unit. | `E_CYCLE`, `E_DOUBLE_DRIVER` |
| V5 Agreement | The bound measure evaluated on authoritative geometry equals the stated value within `tol_agree`. | `E_DISAGREES` |
| V6 Rank / DOF | Independence of driving parameters; redundancy and inconsistency; free DOF report. | `E_REDUNDANT`, `E_INCONSISTENT`, `W_UNDERCONSTRAINED` |
| V7 Identity regeneration | With all values at their current values, regenerate: every entity within `tol_geom` of the source. | `E_IDENTITY` |
| V8 Perturbation | Change each driving parameter by ±δ: no self-intersection; orientation and order invariants hold; the bound measure changes by exactly δ; everything the binding claims to move moves, and nothing else does. | `E_PERTURB`, `E_ORDER`, `E_SPILL` |
| V9 Cross-view | For every correspondence, the corresponding loci in linked views move together; true vs projected lengths are consistent. | `E_CROSSVIEW`, `E_PROJECTED_LENGTH` |
| V10 References | Every reference dimension evaluates within tolerance after regeneration. | `C_REFERENCE_MISMATCH` (conflict) |

V7–V9 are what `validator.py` already does for the datum program: regeneration, invariants, perturbation, the
measured shared-size check. They become the gate for every binding, not only for the final model.

### 6.2 Tolerances come from the source, not from a constant

Let `u` = view mm per page unit.

- `tol_geom`, how exactly the source states a position:
  - native: `max(1e-6 × view_extent, float_eps × |coordinate|)`;
  - vector PDF: `max(0.01 pt × u, the observed quantum)`, where the quantum is the smallest non-zero coordinate
    difference that recurs;
  - raster: `1.5 px × mm_per_px`.
- `tol_text`, how exactly a dimension's text states its value: half a unit of its last printed digit. "20" → ±0.5;
  "20.0" → ±0.05; "20.00" → ±0.005. A text override with fewer digits than the measurement widens it accordingly.
- `tol_agree = tol_text + 2·tol_geom` for V5. The factor 2 is for the two loci.
- `tol_solver`: the numerical tolerance of the solver (1e-9 relative). It is never mixed with the others.
- `tol_app`: an application requirement, e.g. "the regenerated drawing within 0.5 mm of the source for unchanged
  parameters". A policy, set per project.

### 6.3 Validation-error format

```json
{ "code": "E_DISAGREES", "severity": "error",
  "binding": "B-TV-0009", "path": "/target/measure",
  "refs": ["TV:D3", "TV:C1"],
  "expected": { "value": 10.0, "class": "stated", "src": "TV:D3" },
  "actual":   { "value": 20.0, "how": "radius bound to HoleDia → diameter would be 20 ≠ authoritative 10.000" },
  "tolerance": { "agree": 0.5, "text": 0.5, "geom": 1e-6 },
  "message": "HoleDia is bound to C1.radius but D3 is a diameter dimension",
  "hint": "bind to {entity: TV:C1, property: diameter}, or keep radius with expression HoleDia/2",
  "repair_scope": ["B-TV-0009"] }
```

### 6.4 The repair loop

1. Validate all proposals from the call. Collect the errors, each grouped under its `repair_scope`.
2. Send the model only:
   - the failing proposals;
   - their errors;
   - the IDs of the *accepted* entries, frozen (read-only);
   - the allowed operations: `replace(id, fields)`, `withdraw(id)`, `mark_unresolved(id, options)`;
   - the list of previously *rejected* proposals, so they are not proposed again.
3. Apply the patch to a copy. Accept the round only if it is **monotone**: errors in scope decrease, no new errors
   appear elsewhere, and accepted entries are untouched. Otherwise discard it and keep the previous state.
4. Stop after N rounds (3). Whatever still fails becomes `unresolved` and goes to review.

This is the shape of `parametrize.py`'s repair rounds and of the agent's checked edits. What is new is the separate
ledger and the monotone acceptance at proposal granularity.

### 6.5 The ledger

```
proposed ──V0–V10 ok──► validated ──policy/human──► accepted ──(source revision changes a referenced entity)──► stale
    │                       │                           │
    └──fail──► rejected     └──conflict──► conflict ──human──► accepted | rejected
                                                        └──superseded by a newer accepted proposal──► superseded
```

- Only `accepted` entries compile. The compiled graph is stamped with the ledger revision hash. A geometry output
  records the hash of the graph it came from.
- **Auto-accept policy** (configurable). `stated` bindings with `exact` association, V0–V10 clean, and no conflict
  are auto-accepted. Everything `inferred`, every design-intent choice (driving set, anchors) and every `weak`
  association needs a person.
- **Staleness.** Each entry stores the hashes of the entities and datums it references. If a new view-state revision
  changes a referenced entity's *kind* or *topology*, or retires its ID, the entry turns `stale` and leaves the
  compiled graph until it is revalidated. A coordinate change made by regeneration from the same graph does not
  stale anything.
- **Undo/redo** operates on ledger revisions. The `SheetModel` history already stores whole states; the ledger makes
  each step attributable.

---

## 7. Worked example — a plate with two holes and a slot

> **Every value in this section is illustrative.** It is a constructed example, not data extracted from any
> drawing. The source is assumed to be a native DXF (case A) with DIMENSION entities. Where cases B and C would
> differ, this is noted.

The plate (illustrative): 100 × 60 × 10 mm. Two through holes Ø10 at (20, 30) and (80, 30). One slot 8 wide, 24
long overall, vertical, centred at (50, 30). The views are a top view (TV, the XY plane) and a front view (FV, the
XZ plane), in third-angle projection, so TV is drawn above FV.

### 7.1 Extracted entities (view frame, mm; illustrative)

**Top view (TV)**

| ID | Kind | Geometry | Class | Source |
|---|---|---|---|---|
| TV:L1 | line | (0,0)→(100,0) | visible | DXF handle 2A1 |
| TV:L2 | line | (100,0)→(100,60) | visible | 2A2 |
| TV:L3 | line | (100,60)→(0,60) | visible | 2A3 |
| TV:L4 | line | (0,60)→(0,0) | visible | 2A4 |
| TV:C1 | circle | c=(20,30) r=5 | visible | 2B0 |
| TV:C2 | circle | c=(80,30) r=5 | visible | 2B1 |
| TV:A1 | arc | c=(50,22) r=4, 180°→360° | visible | 2C0 |
| TV:A2 | arc | c=(50,38) r=4, 0°→180° | visible | 2C1 |
| TV:L5 | line | (46,22)→(46,38) | visible | 2C2 |
| TV:L6 | line | (54,22)→(54,38) | visible | 2C3 |
| TV:CL1 | line | (−5,30)→(105,30) | center (linetype CENTER) | 2D0 |
| TV:CL2 | line | (50,−5)→(50,65) | center | 2D1 |
| TV:D1 | dimension | linear, defpoint2 (0,0), defpoint3 (100,0), text "<>" → 100 | dimension | 3A0 |
| TV:D2 | dimension | linear rotated 90°, (100,0)→(100,60), "<>" → 60 | dimension | 3A1 |
| TV:D3 | dimension | diameter on C1, text "2X %%c10" → "2X Ø10" | dimension | 3A2 |
| TV:D4 | dimension | linear, (0,60)→(20,30) measured along x → 20 | dimension | 3A3 |
| TV:D5 | dimension | linear rotated 90°, (100,0)→(105,30) → 30 | dimension | 3A4 |
| TV:D6 | dimension | linear, (46,30)→(54,30) → 8 | dimension | 3A5 |
| TV:D7 | dimension | linear rotated 90°, (50,18)→(50,42) → 24 | dimension | 3A6 |
| TV:D8 | dimension | linear, (20,30)→(80,30), text "(<>)" → "(60)" | dimension | 3A7 |

**Front view (FV)**

| ID | Kind | Geometry | Class |
|---|---|---|---|
| FV:L1–FV:L4 | lines | rectangle (0,0)–(100,10) | visible |
| FV:H1, FV:H2 | lines | x = 15 and x = 25, z 0→10 | hidden |
| FV:H3, FV:H4 | lines | x = 75 and x = 85 | hidden |
| FV:H5, FV:H6 | lines | x = 46 and x = 54 | hidden |
| FV:CL1, FV:CL2, FV:CL3 | lines | x = 20, 80, 50 | center |
| FV:D1 | dimension | rotated 90°, (100,0)→(100,10) → 10 | dimension |

FV datums: FV:X0 = 0, X1 = 15, X2 = 20, X3 = 25, X4 = 46, X5 = 50, X6 = 54, X7 = 75, X8 = 80, X9 = 85, X10 = 100
(on model X); FV:Z0 = 0, Z1 = 10 (on model Z).

**Datums built from these (TV).** Each is identified by what defines it:

| Datum | Axis | Value | Defined by |
|---|---|---|---|
| TV:X0 | x | 0 | L4 (line), L1.start, L3.end |
| TV:X1 | x | 20 | C1.center |
| TV:X2 | x | 46 | L5 |
| TV:X3 | x | 50 | CL2, A1.center, A2.center |
| TV:X4 | x | 54 | L6 |
| TV:X5 | x | 80 | C2.center |
| TV:X6 | x | 100 | L2 |
| TV:Y0 | y | 0 | L1 |
| TV:Y1 | y | 18 | A1.quadrant:−y |
| TV:Y2 | y | 30 | CL1, C1.center, C2.center |
| TV:Y3 | y | 42 | A2.quadrant:+y |
| TV:Y4 | y | 60 | L3 |

Hole edges (x = 15, 25, 75, 85) and arc centres (y = 22, 38) are *dependent loci*, written from these through the
features' own parameters. They are not datums of their own.

### 7.2 The complete TV view state (illustrative)

```json
{
  "schema": "view-state", "schema_version": "1.2.0",
  "doc": { "doc_id": "plate-demo", "sha256": "<file hash>", "adapter": "dxf@ezdxf" },
  "revision": { "n": 4, "content_hash": "<hash of entities+annotations+datum definitions>", "parent": "<rev 3 hash>" },
  "view": {
    "id": "TV", "kind": "view", "title": "TOP VIEW",
    "type_candidates": [ { "type": "top", "evidence": ["title 'TOP VIEW'", "drawn above FV, sharing x faces (third-angle)"] } ],
    "projection": { "system": "third_angle", "axis_map": { "x": "X", "y": "Y" }, "value_class": "inferred" },
    "bbox_page": [52.0, 112.0, 168.0, 188.0]
  },
  "units": { "view_unit": "mm", "angle_unit": "deg", "mm_per_page_unit": 1.0,
             "scale": { "factor": 1.0, "stated": "SCALE 1:1", "verified_by": ["TV:D1", "TV:D2", "TV:D4", "TV:D6", "TV:D7"], "value_class": "authoritative" },
             "tol_geom_mm": 1e-6 },
  "frames": {
    "page_to_view": [[1, 0, -60], [0, 1, -120], [0, 0, 1]],
    "view_to_model": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
  },
  "entities": [
    { "id": "TV:L1", "kind": "line", "geom": { "a": [0, 0], "b": [100, 0] }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2A1" }, "value_class": "authoritative" },
    { "id": "TV:L2", "kind": "line", "geom": { "a": [100, 0], "b": [100, 60] }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2A2" }, "value_class": "authoritative" },
    { "id": "TV:L3", "kind": "line", "geom": { "a": [100, 60], "b": [0, 60] }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2A3" }, "value_class": "authoritative" },
    { "id": "TV:L4", "kind": "line", "geom": { "a": [0, 60], "b": [0, 0] }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2A4" }, "value_class": "authoritative" },
    { "id": "TV:C1", "kind": "circle", "geom": { "c": [20, 30], "r": 5 }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2B0" }, "value_class": "authoritative" },
    { "id": "TV:C2", "kind": "circle", "geom": { "c": [80, 30], "r": 5 }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2B1" }, "value_class": "authoritative" },
    { "id": "TV:A1", "kind": "arc", "geom": { "c": [50, 22], "r": 4, "a0": 180, "a1": 360 }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2C0" }, "value_class": "authoritative" },
    { "id": "TV:A2", "kind": "arc", "geom": { "c": [50, 38], "r": 4, "a0": 0, "a1": 180 }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2C1" }, "value_class": "authoritative" },
    { "id": "TV:L5", "kind": "line", "geom": { "a": [46, 22], "b": [46, 38] }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2C2" }, "value_class": "authoritative" },
    { "id": "TV:L6", "kind": "line", "geom": { "a": [54, 22], "b": [54, 38] }, "line_class": { "value": "visible", "by": "layer:OUTLINE" }, "layer": "OUTLINE", "src": { "adapter": "dxf", "ref": "2C3" }, "value_class": "authoritative" },
    { "id": "TV:CL1", "kind": "line", "geom": { "a": [-5, 30], "b": [105, 30] }, "line_class": { "value": "center", "by": "linetype:CENTER" }, "layer": "CENTER", "src": { "adapter": "dxf", "ref": "2D0" }, "value_class": "authoritative" },
    { "id": "TV:CL2", "kind": "line", "geom": { "a": [50, -5], "b": [50, 65] }, "line_class": { "value": "center", "by": "linetype:CENTER" }, "layer": "CENTER", "src": { "adapter": "dxf", "ref": "2D1" }, "value_class": "authoritative" }
  ],
  "datums": [
    { "id": "TV:X0", "axis": "x", "value": { "v": 0,   "class": "authoritative" }, "defined_by": [{ "entity": "TV:L4", "select": "line" }], "faces": 0.55 },
    { "id": "TV:X1", "axis": "x", "value": { "v": 20,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:C1", "select": "center" }], "faces": 0.0 },
    { "id": "TV:X2", "axis": "x", "value": { "v": 46,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:L5", "select": "line" }], "faces": 0.15 },
    { "id": "TV:X3", "axis": "x", "value": { "v": 50,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:CL2", "select": "line" }, { "entity": "TV:A1", "select": "center" }, { "entity": "TV:A2", "select": "center" }], "faces": 0.0 },
    { "id": "TV:X4", "axis": "x", "value": { "v": 54,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:L6", "select": "line" }], "faces": 0.15 },
    { "id": "TV:X5", "axis": "x", "value": { "v": 80,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:C2", "select": "center" }], "faces": 0.0 },
    { "id": "TV:X6", "axis": "x", "value": { "v": 100, "class": "authoritative" }, "defined_by": [{ "entity": "TV:L2", "select": "line" }], "faces": 0.55 },
    { "id": "TV:Y0", "axis": "y", "value": { "v": 0,   "class": "authoritative" }, "defined_by": [{ "entity": "TV:L1", "select": "line" }], "faces": 0.91 },
    { "id": "TV:Y1", "axis": "y", "value": { "v": 18,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:A1", "select": "quadrant:-y" }], "faces": 0.0 },
    { "id": "TV:Y2", "axis": "y", "value": { "v": 30,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:CL1", "select": "line" }, { "entity": "TV:C1", "select": "center" }, { "entity": "TV:C2", "select": "center" }], "faces": 0.0 },
    { "id": "TV:Y3", "axis": "y", "value": { "v": 42,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:A2", "select": "quadrant:+y" }], "faces": 0.0 },
    { "id": "TV:Y4", "axis": "y", "value": { "v": 60,  "class": "authoritative" }, "defined_by": [{ "entity": "TV:L3", "select": "line" }], "faces": 0.91 }
  ],
  "features": [
    { "id": "TV:F1", "kind": "profile", "members": ["TV:L1", "TV:L2", "TV:L3", "TV:L4"], "params": { "width": { "v": 100, "class": "authoritative" }, "depth": { "v": 60, "class": "authoritative" } } },
    { "id": "TV:F2", "kind": "hole_group", "members": ["TV:C1", "TV:C2"], "params": { "diameter": { "v": 10, "class": "authoritative" } },
      "instances": [ { "id": "TV:C1", "center": ["TV:X1", "TV:Y2"] }, { "id": "TV:C2", "center": ["TV:X5", "TV:Y2"] } ] },
    { "id": "TV:F3", "kind": "slot", "members": ["TV:A1", "TV:A2", "TV:L5", "TV:L6"],
      "params": { "width": { "v": 8, "class": "authoritative" }, "length_overall": { "v": 24, "class": "authoritative" }, "centre_distance": { "v": 16, "class": "authoritative" } } }
  ],
  "annotations": [
    { "id": "TV:D1", "kind": "dimension", "text": { "raw": "<>", "plain": "100", "parsed": { "value": 100, "unit": "mm", "decimals": 0, "prefix": "", "markers": [] } },
      "dimension": { "dimtype": "linear", "native_measurement": 100,
        "candidates": [ { "cid": "D1/c1", "measure": { "kind": "distance", "a": { "datum": "TV:X0" }, "b": { "datum": "TV:X6" }, "along": "x" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D2", "kind": "dimension", "text": { "raw": "<>", "plain": "60", "parsed": { "value": 60, "unit": "mm", "decimals": 0, "prefix": "", "markers": [] } },
      "dimension": { "dimtype": "linear", "native_measurement": 60,
        "candidates": [ { "cid": "D2/c1", "measure": { "kind": "distance", "a": { "datum": "TV:Y0" }, "b": { "datum": "TV:Y4" }, "along": "y" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D3", "kind": "dimension", "text": { "raw": "2X %%c10", "plain": "2X Ø10", "parsed": { "value": 10, "unit": "mm", "decimals": 0, "prefix": "Ø", "count": 2, "markers": [] } },
      "dimension": { "dimtype": "diameter", "native_measurement": 10,
        "candidates": [ { "cid": "D3/c1", "measure": { "kind": "diameter", "of": { "entity": "TV:F2" } }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D4", "kind": "dimension", "text": { "raw": "<>", "plain": "20", "parsed": { "value": 20, "unit": "mm", "decimals": 0, "prefix": "", "markers": [] } },
      "dimension": { "dimtype": "linear", "native_measurement": 20,
        "candidates": [ { "cid": "D4/c1", "measure": { "kind": "distance", "a": { "datum": "TV:X0" }, "b": { "datum": "TV:X1" }, "along": "x" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D5", "kind": "dimension", "text": { "raw": "<>", "plain": "30", "parsed": { "value": 30, "unit": "mm", "decimals": 0, "prefix": "", "markers": [] } },
      "dimension": { "dimtype": "linear", "native_measurement": 30,
        "candidates": [ { "cid": "D5/c1", "measure": { "kind": "distance", "a": { "datum": "TV:Y0" }, "b": { "datum": "TV:Y2" }, "along": "y" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D6", "kind": "dimension", "text": { "raw": "<>", "plain": "8", "parsed": { "value": 8, "unit": "mm", "decimals": 0, "prefix": "", "markers": [] } },
      "dimension": { "dimtype": "linear", "native_measurement": 8,
        "candidates": [ { "cid": "D6/c1", "measure": { "kind": "distance", "a": { "datum": "TV:X2" }, "b": { "datum": "TV:X4" }, "along": "x" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D7", "kind": "dimension", "text": { "raw": "<>", "plain": "24", "parsed": { "value": 24, "unit": "mm", "decimals": 0, "prefix": "", "markers": [] } },
      "dimension": { "dimtype": "linear", "native_measurement": 24,
        "candidates": [ { "cid": "D7/c1", "measure": { "kind": "distance", "a": { "datum": "TV:Y1" }, "b": { "datum": "TV:Y3" }, "along": "y" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } },
    { "id": "TV:D8", "kind": "dimension", "text": { "raw": "(<>)", "plain": "(60)", "parsed": { "value": 60, "unit": "mm", "decimals": 0, "prefix": "", "markers": ["reference"] } },
      "dimension": { "dimtype": "linear", "native_measurement": 60,
        "candidates": [ { "cid": "D8/c1", "measure": { "kind": "distance", "a": { "datum": "TV:X1" }, "b": { "datum": "TV:X5" }, "along": "x" }, "method": "defpoint_snap", "quality": "exact", "residual_mm": 0 } ] } }
  ],
  "relations": [
    { "id": "R1", "kind": "on_datum", "refs": [{ "datum": "TV:Y2" }, { "entity": "TV:C1", "select": "center" }, { "entity": "TV:C2", "select": "center" }], "class": "exact", "residual_mm": 0 },
    { "id": "R2", "kind": "mirror", "refs": [{ "entity": "TV:C1", "select": "center" }, { "entity": "TV:C2", "select": "center" }, { "entity": "TV:CL2", "select": "line" }], "class": "exact", "residual_mm": 0 },
    { "id": "R3", "kind": "mirror", "refs": [{ "datum": "TV:X0" }, { "datum": "TV:X6" }, { "entity": "TV:CL2", "select": "line" }], "class": "exact", "residual_mm": 0 },
    { "id": "R4", "kind": "on_datum", "refs": [{ "datum": "TV:X3" }, { "entity": "TV:F3", "select": "mid" }], "class": "exact", "residual_mm": 0 },
    { "id": "R5", "kind": "on_datum", "refs": [{ "datum": "TV:Y2" }, { "entity": "TV:F3", "select": "mid" }], "class": "exact", "residual_mm": 0 },
    { "id": "R6", "kind": "equal_size", "refs": [{ "entity": "TV:C1" }, { "entity": "TV:C2" }], "class": "exact", "residual_mm": 0 }
  ],
  "correspondences": [ { "id": "K1", "views": ["TV", "FV"], "axis": "X", "offset_mm": 0, "planes": 7, "fraction": 1.0, "strength": "strong",
    "pairs": [["TV:X0", "FV:X0"], ["TV:X1", "FV:X2"], ["TV:X2", "FV:X4"], ["TV:X3", "FV:X5"], ["TV:X4", "FV:X6"], ["TV:X5", "FV:X8"], ["TV:X6", "FV:X10"]] } ],
  "ambiguities": [ { "id": "A1", "about": "TV:D5", "options": ["hole centre row height", "slot centre height"],
                     "would_resolve": "design intent: does the slot stay on the hole centre line?" } ]
}
```

Notes on that state:

- **D5 snaps exactly.** Its second definition point (105, 30) lies on CL1, beyond the plate. It is on no vertex of
  any outline, yet its datum is unique (Y2): this is method 2 of §3.4 working as intended. The remaining ambiguity is
  semantic, not geometric, and is recorded as `A1`.
- **D7 is an overall length.** Its candidate measures between arc *quadrants* (Y1, Y3), not arc centres. The
  edge-vs-centre question is settled by the definition points, not by the model.
- **How the input cases differ for this state.**
  - Case B: D-entities would arrive as exploded lines, arrows and text, so method 3 applies, and A1/A2 would arrive
    as Bézier fits with a residual.
  - Case C: every entity would be `measured` with `sigma_mm`. Only the D-texts, once confirmed, would be `stated`.

### 7.3 Cross-view associations (illustrative)

- **Alignment.** The engine aligns TV and FV on model X: 7 of 7 TV x-datums coincide with FV x-datums, at offset 0
  and residual 0. Link `K1` is `strong`.
- **Feature pairing.**
  - TV:C1 (x 15–25) ↔ FV:{H1, H2, CL1}. The hidden lines span the full thickness (z 0→10), so the hole is
    "through" (`inferred`, consistent with no depth note).
  - TV:C2 ↔ FV:{H3, H4, CL2}.
  - TV:F3 (x 46–54) ↔ FV:{H5, H6, CL3}.
- **Thickness.** It is stated only in FV (FV:D1 = 10), on FV:Z0–Z1. It has no TV counterpart. That is expected: the
  top view cannot show thickness.
- **Consequence.** A parameter bound in TV (HoleDia) also drives FV:H1–H4 through K1: FV:X1 = X1 − HoleDia/2. This
  is what `crossview` does today when it analyses linked views as one unit.

### 7.4 The exact multimodal input package (binding call for unit TV+FV)

| # | Part | Content | Tokens (est.) |
|---|---|---|---|
| 1 | system instruction | Role; the rules (closed IDs; values only from annotations; no coordinates; `unresolved` allowed); DATA_RULE (drawing text is quoted data); the output contract (call `submit_proposals`) | ~1.2k |
| 2 | image | TV crop, rendered from the state at 8 px/mm, 928×608 px, no overlay; `media_resolution: high` | 1,120 |
| 3 | image | the same crop with Set-of-Mark labels: L1–L6, C1, C2, A1, A2, CL1, CL2 in the structure colour; X0–X6, Y0–Y4 as thin cyan ticks at the frame edge; D1–D8 boxed at their text | 1,120 |
| 4 | image | FV crop with labels (FV:H1–H6, FV:CL1–3, FV:D1) | 1,120 |
| 5 | text | the digest below | ~1.5k |
| 6 | tools | `get`, `measure`, `project`, `render`, `check`, `submit_proposals` (function calling; `submit_proposals` validated against its schema) | ~0.8k |

The digest (part 5), exactly as sent (illustrative values):

```
UNIT U1 = views TV (top) + FV (front), linked on model X (K1: 7/7 planes, offset 0).  Units: mm, degrees.
Numbers: [A] authoritative native geometry, exact to 1e-6 · [S:Dn] stated by annotation Dn · [M±σ] measured.

TV "TOP VIEW"  scale 1:1 [S: "SCALE 1:1", verified by 5 dimensions]  frame: origin plate corner, +x right, +y up
FEATURES
  F1 profile rectangle [L1 L2 L3 L4]  100 × 60 [A]
  F2 hole_group [C1 C2]  Ø10 [A] each, centres (20,30) (80,30) [A]
  F3 slot [A1 A2 L5 L6]  width 8 [A], overall 24 [A], centre distance 16 [A], centred on X3
DATUMS  x: X0=0(L4) X1=20(C1.c) X2=46(L5) X3=50(CL2,A1.c,A2.c) X4=54(L6) X5=80(C2.c) X6=100(L2)
        y: Y0=0(L1) Y1=18(A1 quadrant −y) Y2=30(CL1,C1.c,C2.c) Y3=42(A2 quadrant +y) Y4=60(L3)
RELATIONS (exact)  R1 C1.c,C2.c on Y2 · R2 C1.c↔C2.c mirror about CL2 · R3 X0↔X6 mirror about CL2
                   R4 F3 mid on X3 · R5 F3 mid on Y2 · R6 C1 = C2 size
DIMENSIONS (text parsed; candidates from definition points — choose one, or mark unresolved)
  D1 "100"        → D1/c1 distance x X0–X6         exact
  D2 "60"         → D2/c1 distance y Y0–Y4         exact
  D3 "2X Ø10"     → D3/c1 diameter of F2 (count 2) exact
  D4 "20"         → D4/c1 distance x X0–X1         exact
  D5 "30"         → D5/c1 distance y Y0–Y2         exact   (Y2 carries C1.c, C2.c, F3 mid — see ambiguity A1)
  D6 "8"          → D6/c1 distance x X2–X4         exact
  D7 "24"         → D7/c1 distance y Y1–Y3         exact   (arc quadrants: overall length, not centres)
  D8 "(60)"       → D8/c1 distance x X1–X5         exact   REFERENCE (parentheses): check only, never driving

FV "FRONT VIEW"  scale 1:1  frame: x = model X, y = model Z
  outline 100 × 10 [A]; hidden pairs H1/H2 (x 15/25), H3/H4 (75/85), H5/H6 (46/54) span z 0→10; centre lines at 20, 80, 50
  FV:D1 "10" → FV:D1/c1 distance z FV:Z0–FV:Z1 exact

TASK  For every dimension: bind it (driving / reference), name the parameter, and state formulas and constraints the
      drawing shows. Use only the IDs above. Never write coordinates. If two readings remain, return unresolved.
```

### 7.5 Proposed bindings (the model's answer; illustrative)

```json
{ "proposals": [
  { "id": "P1", "role": "driving_parameter", "parameter": { "name": "PlateWidth", "dim_type": "length" }, "value_source": { "annotation": "TV:D1", "candidate": "D1/c1" } },
  { "id": "P2", "role": "driving_parameter", "parameter": { "name": "PlateDepth", "dim_type": "length" }, "value_source": { "annotation": "TV:D2", "candidate": "D2/c1" } },
  { "id": "P3", "role": "driving_parameter", "parameter": { "name": "PlateThickness", "dim_type": "length" }, "value_source": { "annotation": "FV:D1", "candidate": "FV:D1/c1" } },
  { "id": "P4", "role": "driving_parameter", "parameter": { "name": "HoleDia", "dim_type": "length" },
    "target": { "entity": "TV:F2", "property": "radius" }, "value_source": { "annotation": "TV:D3", "candidate": "D3/c1" } },
  { "id": "P5", "role": "driving_parameter", "parameter": { "name": "HoleOffsetX", "dim_type": "length" }, "value_source": { "annotation": "TV:D4", "candidate": "D4/c1" } },
  { "id": "P6", "role": "driving_parameter", "parameter": { "name": "HoleRowY", "dim_type": "length" }, "value_source": { "annotation": "TV:D5", "candidate": "D5/c1" },
    "assumptions": ["the slot centre stays on the hole centre line (R5) — design intent, see A1"] },
  { "id": "P7", "role": "driving_parameter", "parameter": { "name": "SlotWidth", "dim_type": "length" }, "value_source": { "annotation": "TV:D6", "candidate": "D6/c1" } },
  { "id": "P8", "role": "driving_parameter", "parameter": { "name": "SlotLength", "dim_type": "length" }, "value_source": { "annotation": "TV:D7", "candidate": "D7/c1" } },
  { "id": "P9", "role": "constraint", "kind": "mirror", "refs": [{ "entity": "TV:C1", "select": "center" }, { "entity": "TV:C2", "select": "center" }, { "entity": "TV:CL2", "select": "line" }], "evidence": ["R2 exact", "CL2 drawn as centre line"] },
  { "id": "P10", "role": "constraint", "kind": "mirror", "refs": [{ "datum": "TV:X0" }, { "datum": "TV:X6" }, { "entity": "TV:CL2", "select": "line" }], "evidence": ["R3 exact"] },
  { "id": "P11", "role": "constraint", "kind": "on_datum", "refs": [{ "datum": "TV:X3" }, { "entity": "TV:F3", "select": "mid" }], "evidence": ["R4 exact", "slot axis on CL2"] },
  { "id": "P12", "role": "constraint", "kind": "on_datum", "refs": [{ "datum": "TV:Y2" }, { "entity": "TV:F3", "select": "mid" }], "evidence": ["R5 exact"], "status_request": "inferred" },
  { "id": "P13", "role": "derived_parameter", "parameter": { "name": "HolePitch", "dim_type": "length" }, "expression": { "text": "PlateWidth - 2*HoleOffsetX" },
    "depends_on": ["PlateWidth", "HoleOffsetX"], "checks": [{ "annotation": "TV:D8", "as": "reference" }] },
  { "id": "P14", "role": "derived_parameter", "parameter": { "name": "SlotCentreDistance", "dim_type": "length" }, "expression": { "text": "SlotLength - SlotWidth" },
    "depends_on": ["SlotLength", "SlotWidth"] },
  { "id": "P15", "role": "reference_check", "annotation": "TV:D8", "against": "HolePitch" }
] }
```

### 7.6 Deterministic validation (illustrative results)

| Proposal | V1 refs | V2 kind | V3 expr | V4 DAG | V5 agreement | V6 rank | Result |
|---|---|---|---|---|---|---|---|
| P1 PlateWidth | ok | ok | — | ok | 100 vs 100 ✓ | independent | validated |
| P2 PlateDepth | ok | ok | — | ok | 60 vs 60 ✓ | independent | validated |
| P3 PlateThickness | ok | ok | — | ok | 10 vs 10 ✓ | independent | validated |
| **P4 HoleDia** | ok | **E_PROPERTY_KIND** | — | ok | **E_DISAGREES**: radius ← 10 means Ø20 ≠ 10 | — | **rejected** |
| P5 HoleOffsetX | ok | ok | — | ok | 20 vs 20 ✓ | independent | validated |
| P6 HoleRowY | ok | ok | — | ok | 30 vs 30 ✓ | independent | validated (assumption logged) |
| P7 SlotWidth | ok | ok | — | ok | 8 vs 8 ✓ | independent | validated |
| P8 SlotLength | ok | ok | — | ok | 24 vs 24 ✓ | independent | validated |
| P9–P11 | ok | ok | — | ok | residual 0 | removes 3 DOF | validated |
| P12 slot on Y2 | ok | ok | — | ok | residual 0 | removes 1 DOF | validated, **needs review** (`inferred`) |
| P13 HolePitch | ok | ok | length − 2·length → length ✓ | ok | 100 − 40 = 60 vs D8 (60) ✓ | derived | validated |
| P14 | ok | ok | ✓ | ok | 24 − 8 = 16 vs slot centres 16 ✓ | derived | validated |
| P15 | ok | ok | — | ok | 60 within ±0.5 | reference | validated |

With P4 out, the DOF report is: "F2 diameter has no driver (it keeps its current value 10, implicit anchor)". The
identity regeneration (V7) passes; V8 is skipped for F2's diameter until it has a driver.

### 7.7 The deliberately wrong binding, and how it is caught

P4 binds `HoleDia` (value 10, from the *diameter* dimension D3) to the hole group's **radius**. Applied, it would
make Ø20 holes. They would still sit inside the plate: plausible-looking, and wrong. Two independent checks catch it:

```json
[ { "code": "E_PROPERTY_KIND", "severity": "error", "binding": "P4", "path": "/target/property",
    "refs": ["TV:D3", "TV:F2"], "expected": { "property": "diameter", "because": "D3 dimtype = diameter, text prefix Ø" },
    "actual": { "property": "radius" },
    "message": "a diameter annotation is bound to a radius",
    "hint": "target {entity: TV:F2, property: diameter}, or radius with expression HoleDia/2", "repair_scope": ["P4"] },
  { "code": "E_DISAGREES", "severity": "error", "binding": "P4", "path": "/value_source",
    "refs": ["TV:D3", "TV:C1", "TV:C2"], "expected": { "value": 5.0, "class": "authoritative", "what": "C1.radius" },
    "actual": { "value": 10.0, "what": "radius implied by the binding" },
    "tolerance": { "agree": 0.500002, "text": 0.5, "geom": 1e-6 }, "repair_scope": ["P4"] } ]
```

The repair round sends the model P4, these two errors, the frozen IDs of P1–P3 and P5–P15, and the operations
allowed. The model returns:

```json
{ "op": "replace", "id": "P4", "fields": { "target": { "entity": "TV:F2", "property": "diameter" } } }
```

Re-validation passes: diameter 10 vs authoritative 2 × 5.000000 = 10, residual 0. The round is monotone (2 errors →
0, no new errors), so the patch is kept.

A second kind of wrong binding is caught even earlier. Had the model bound D4 "20" to C2 (whose centre is 80 from X0),
V1 would refuse it with `E_NOT_A_CANDIDATE`: D4's only candidate is X0–X1. A target outside the associator's list
never reaches the agreement stage.

### 7.8 The accepted output (illustrative)

Ledger after review. The person accepts P12, the slot staying on the hole centre line, which resolves A1:

```
accepted: P1 PlateWidth=100 · P2 PlateDepth=60 · P3 PlateThickness=10 · P4' HoleDia=10 (F2.diameter)
          P5 HoleOffsetX=20 · P6 HoleRowY=30 · P7 SlotWidth=8 · P8 SlotLength=24
          P9 mirror(C1.c, C2.c, CL2) · P10 mirror(X0, X6, CL2) · P11 F3.mid on X3 · P12 F3.mid on Y2 (reviewed)
          P13 HolePitch = PlateWidth − 2·HoleOffsetX · P14 SlotCentreDistance = SlotLength − SlotWidth
          P15 D8 "(60)" checks HolePitch
rejected: P4 (radius) — superseded by P4'
```

Compiled constraint graph, as per-axis closed-form datum formulas in model mm (the same form as the dxf-autoparam
program):

```
X:  X0 = 0 (anchor: the plate's left edge stays)
    X6 = X0 + PlateWidth
    X3 = (X0 + X6) / 2                       ← P10 (CL2 mid-plane)
    X1 = X0 + HoleOffsetX                    ← P5
    X5 = 2·X3 − X1                           ← P9 mirror
    X2 = X3 − SlotWidth/2 ;  X4 = X3 + SlotWidth/2         ← P7, P11
    hole edges: X1 ± HoleDia/2, X5 ± HoleDia/2              ← P4'
Y:  Y0 = 0 (anchor) ;  Y4 = Y0 + PlateDepth ;  Y2 = Y0 + HoleRowY
    Y1 = Y2 − SlotLength/2 ;  Y3 = Y2 + SlotLength/2       ← P8, P12
    slot arc centres: Y1 + SlotWidth/2, Y3 − SlotWidth/2
Z:  Z0 = 0 (anchor) ;  Z1 = Z0 + PlateThickness
FV (through K1): every FV x-datum = its TV partner; hidden lines X1 ± HoleDia/2, X5 ± HoleDia/2, X2, X4
DOF: 0 free (anchors X0, Y0, Z0 declared) · rank: 8 driving parameters independent · reference D8 consistent
```

Two checks of the compiled graph:

- **Identity regeneration.** Every entity is reproduced within 1e-6 mm.
- **Perturbation, PlateWidth 100 → 120** (illustrative). X6 = 120 and X3 = 60. The holes move to x = 20 and x = 100
  (the mirror keeps them symmetric), and the slot to x 56–64. The FV hidden lines follow: 15/25, 95/105, 56/64.
  HolePitch = 80. The reference "(60)" becomes a *reported* mismatch (`C_REFERENCE_MISMATCH`, expected after a
  change), and the writer re-renders its text to "(80)", because a reference dimension shows the measurement.

---

## 8. MVP implementation plan

### 8.1 Pipeline pseudocode

```python
def run(file, policy):
    prims, report = ingest(file)                          # adapter by type; nothing dropped silently
    views = segment(prims)                                # View[] with questions
    states = {v.id: build_view_state(v, prims) for v in views}
    links = correspond(states)                            # projection alignment, section/detail callouts
    for s in states.values():
        s.datums = datums(s)                              # keyed by defining sets → stable IDs (registry)
        s.features = features(s)
        s.annotations = interpret(s)                      # text grammar; never eval
        for d in s.annotations.dimensions():
            d.candidates = associate(d, s)                # native assoc > defpoint snap > exploded > proximity
        s.relations = relation_index(s)
    ledger = Ledger.load_or_new(file)
    for unit in units(states, links):                     # linked views together
        pkg = package(unit, ledger.accepted(), render(unit, overlays=True))
        proposals = llm_session(pkg, tools=ReadOnlyTools(unit, ledger))   # function calls; submit_proposals
        for rnd in range(3):
            rep = validate(proposals, unit, ledger)       # V0–V10
            ledger.record(proposals, rep)
            failing = rep.failing()
            if not failing:
                break
            patch = llm_repair(failing, rep, frozen=ledger.accepted_ids(), rejected=ledger.rejected())
            proposals = apply_if_monotone(proposals, patch, validate)
        ledger.auto_accept(policy)                        # stated+exact+clean only; the rest → review queue
    graph = compile(ledger.accepted())                    # DAG per axis + local solver blocks; DOF/rank report
    geom = regenerate(graph, values=ledger.values())      # closed form; solver for non-axis blocks
    assert identity(geom, states, tol_geom)               # V7 before anything is written
    return write(file, geom, re_render_dimensions=True), ledger, graph
```

### 8.2 Milestones (case A first, on the existing engine)

| # | Deliverable | Acceptance |
|---|---|---|
| M1 | **Annotation objects with loci.** Every DIMENSION (native and reconstructed exploded) becomes an `annotation` with `measure` and `candidates[]` (method, quality, residual). Today's `relink_texts` / `_measured_between` and the analysis's DIMENSION point binding become one associator. | On the labelled set (§8.4): association accuracy ≥ 99% on native dimensions, 0 value-only associations, ambiguity reported, never guessed. |
| M2 | **Stable IDs.** Entity IDs from `src` handles. Datum IDs from defining sets, with a persistent registry. The ID map survives re-read and edit. | Re-reading an edited DXF keeps ≥ 99.9% of IDs; no ID is reused. |
| M3 | **Binding ledger.** Proposals separate from the unit's answer, with states, base revisions, evidence and staleness. | Every equation in a compiled program traces to an accepted ledger entry. |
| M4 | **The candidate-choice contract for the LLM.** `bind_dimension(annotation, candidate \| unresolved)` replaces free-form `from_line/to_line` wherever a dimension exists. SoM overlays are rendered from the state. The digest format of §7.4. | The model cannot express a target outside the candidates (closed world, enforced by V1). |
| M5 | **Validator extensions.** Dimensional types on parameters; reference/basic markers; rank/DOF report; projected-length check; conflict records. | All §5.3 rules have a failing test that the validator catches. |
| M6 | **Evaluation harness and labelled set** (§8.4). | Metrics reported per release; the silent-wrong-binding rate is tracked as a release blocker. |
| M7 | Vector PDF adapter: paths and Béziers from PyMuPDF `get_drawings()`; circle and arc fits; text from `rawdict` (line `dir` gives the text direction, §11); exploded-dimension reconstruction (M1 method 3). | On PDF exports of the same drawings, association within the reconstructed-quality bounds. |
| M8 | Local general solver blocks for non-axis constraints (angles, tangency, aligned dimensions), using PlaneGCS (`planegcs`) or SolveSpace (`py-slvs` / `python-solvespace`). The axis DAG supplies boundary values. Licences and maintenance must be verified before adopting (§11). | Angular and aligned dimensions bind and regenerate. |
| M9 | Raster adapter: OCR plus primitive detection. Everything `measured`. Geometry driven by confirmed dimension text; confirmation UI. | Separate metrics; never auto-accept. |

### 8.3 Metrics

- **Extraction:** precision/recall per entity kind; arc and circle fit residuals (case B).
- **Segmentation:** view-level IoU; entity assignment accuracy; question rate.
- **Association:** fraction of dimensions whose accepted loci equal the labels; `exact`/`ambiguous`/`weak` rates;
  **wrong-but-exact rate** (must be 0).
- **Binding:**
  - exact-match accuracy of (target, property, role, expression semantics) against labels;
  - **silent wrong binding rate**: accepted and wrong. This is the headline metric, and must be 0 on the regression
    set;
  - unresolved rate (lower is better only while the wrong rate stays 0).
- **Cross-view:** correspondence precision/recall; consistency failures after a change.
- **Regeneration:** identity error (max, p95); perturbation correctness against the labelled intent (which entities
  move and by how much).
- **Cost:** tokens per view and per unit; latency per stage; repair rounds per unit; human decisions per drawing.

### 8.4 Representative test set

- **Synthetic, generated with known ground truth** (the `mini_gad` generator in `tests/test_crossview.py` is the
  first). Plates, brackets, box culverts, wing walls. Vary:
  - the dimensioning: associative, non-associative, exploded, text overrides, reference "( )", basic boxed, "2X",
    "TYP";
  - the features: radius vs diameter, edge vs centre, chain plus overall (over-defined), ordinate, angular, slots,
    patterns with count changes;
  - the projection and scale: first vs third angle, details at another scale.
- **Real drawings** (already in use): `gad_ezdxf_a` (20 views); `mib173`; the wing-wall sheet (splay-set gaps, label
  links); BRG NO.80 (PDF-converted: exploded dimensions, inconsistent scale — expected to abstain); the mini live
  sheet with its saved Gemini project.
- **Adversarial cases:**
  - two different sizes with the same value;
  - definition points on lines but not vertices;
  - features stacked on one projection line;
  - mirrored views;
  - text overrides that disagree with the geometry;
  - dimension text containing instructions (prompt injection);
  - rotated views;
  - very small text.

### 8.5 The failure modes that matter most

| Failure | How it shows | Mitigation |
|---|---|---|
| Value coincidence | A label bound to an unrelated size of the same value. Seen live: the horizontal 1350 tied to the vertical 1350. | Associate by loci only; the value only confirms (§3.4). |
| Definition point on a line, not a vertex | The dimension follows the wrong corner. Seen live: the wall dimensions stuck at 300. | Snap per axis to the datum through the point (§3.4 method 2). Fixed in `_attach_free_points`; generalise in M1. |
| ID drift after re-read | Bindings point at different lines | Defining-set datum IDs plus the registry (M2); staleness rules. |
| Invented IDs or targets | References that don't exist or aren't candidates | Closed world, V1 (`E_UNKNOWN_ID`, `E_NOT_A_CANDIDATE`). |
| A number transcribed from the image | The value differs from the text | Values only by annotation reference; V5 agreement. |
| Radius/diameter, edge/centre confusion | Geometry plausible but 2× or ± r off | V2 kind rules plus V5 agreement (§7.7). |
| Over-defined chains | Rank deficiency; the solver fights itself | V6 demotes one to reference; inconsistency → conflict. |
| Projected lengths | A true length bound to a foreshortened view | V9 `E_PROJECTED_LENGTH` using the correspondences. |
| Per-view scale or unit errors | Every value off by a constant factor | Per-view units from agreeing dimensions (exists); abstain when dimensions disagree (BRG). |
| Inferred intent applied silently | Symmetry or "stays on the centre line" changes behaviour unseen | `inferred` never auto-accepts; review queue; anchors explicit. |
| Solver branch flip | A mirror solution or crossed geometry | Start from the source; order and orientation invariants (V8, `check_invariants`). |
| Stale bindings after edits | An old binding drives a changed entity | Ledger staleness by referenced-entity hashes. |
| Prompt injection via drawing text | The model follows text on the drawing | DATA_RULE; text only in data blocks; tools read-only; no free-form actions. |
| Context overflow or slow calls on big units | Truncation, stalls | Staged calls; digest summarisation; tools; prompt cache; step deadlines and stall watchdog (exists since `c01d274`). |

---

## 9. Tradeoffs and open questions

### 9.1 Approaches compared

| Approach | Accuracy | Traceability | Effort | Latency | Token cost | Recoverability | Native CAD | Scans |
|---|---|---|---|---|---|---|---|---|
| Image only → coordinates | low | none | low | low | low | none | wasteful (ignores exact data) | the only option, but unsafe |
| Image + prose | low–medium | weak | low | low | medium | weak | wasteful | weak |
| Structured geometry only | high on geometry, misses conventions | good | medium | low | medium | good | good | n/a |
| Rules only (no LLM) | high where rules exist; no design intent or naming | good | high for coverage | lowest | 0 | good | good | poor |
| **Hybrid state + SoM + candidate choice + tools + ledger (recommended)** | highest | full (evidence chain per equation) | high | medium (staged calls) | medium (digest + 2–3 images + tools) | best (unresolved, repair, staleness) | best | workable with `measured` provenance and confirmation |

Within the recommendation, the main internal choice is this:

| Constraint form | Pros | Cons | Use |
|---|---|---|---|
| Per-axis closed-form datum DAG (today's engine) | Deterministic, fast, no branch flips, exact identity, trivially traceable | Orthogonal set-out only; angles, tangency and aligned dimensions need special handling | GAD structures (almost all set-out is orthogonal): the primary form |
| General 2D solver (PlaneGCS / SolveSpace) | Any constraint; DOF analysis built in | Branch selection, convergence and licensing questions; harder to trace | Local blocks for non-orthogonal features, bounded by the DAG |
| 3D kernel (OCCT through build123d/CadQuery) | Real solids, true lengths, sections derived | Needs a 3D intent model the drawing rarely states fully | Later, if the output must be a 3D model |

### 9.2 Open questions that change the architecture

1. **The output target.** Updated 2D drawings (today) or a 3D model? A 3D target adds the model-frame resolution of
   §3.2 as a hard requirement, and a kernel stage.
2. **Native associativity in your sources.** Do the GADs you receive carry `DIMASSOC` objects (AutoCAD-authored,
   `$DIMASSOC = 2`)? If they do, method 1 of §3.4 gives exact association for free.
   - The ezdxf DIMENSION documentation does not cover DIMASSOC (§11), so reading those objects must be verified
     before relying on it.
   - The generated GADs (`AAGENTO_DIM_*` styles) could write association data themselves, which would make every
     generated drawing round-trip exactly.
3. **Who decides design intent at scale.** The review queue (driving set, anchors, inferred constraints) is where
   people spend time. Is it a draftsman per drawing, or a family-level template ("box culverts: walls grow outward")
   applied by rule? The Aagento knowledge layer suggests the latter. It should then feed the policy, not the model.
4. **Tolerance policy per project** (`tol_app`): what the regenerated drawing must match, and to how many mm.

---

## 10. How this maps onto dxf-autoparam today

| Design element | Exists today | Gap |
|---|---|---|
| Per-view segmentation, titles, scale and units per view | `sheet.py` `segment()`; per-view `units_mm` from agreeing dimensions | View types are candidates only through the Gemini views stage; no `type_candidates` record. |
| Entities with provenance | `ir.Item` with `handle` and `src` (block path); roles | IDs are `item.index` (positional). Use `src` as the stable key (M2). |
| Datums (set-out lines) | `analyse` datums; every entity point bound by `slot_datum` to (datum, offset) | IDs are ordinal (`f"{axis}{len(self.datums)}"`, analyse.py:150), so they change when lines are added. Key them by defining sets (M2). |
| Dimension association | DIMENSION points bound to datums. Since today, a dimension's measured point on a line binds per axis to that line (`_attach_free_points`). Exploded dimensions: `validator._measured_between` (dimension-line evidence first). | Not a first-class annotation with `measure`, `candidates` and quality; text links (`len:a:b`, param names) are a side table. Merge into M1. |
| Candidate sizes | `analysis.clusters` (gap clusters, evidence: dimension / repeat / round / material) | Candidates are per *size*, not per *annotation*. M1 adds per-dimension candidates. |
| Parameters, formulas, safe evaluation | `program.py`: `parse` whitelists `BinOp`/`UnaryOp`/`Constant`/`Name`/`Call` over `FUNCS = {min, max, abs, sqrt, round}`; compiles the validated AST only; iterative topological order with cycle errors | No dimensional types on parameters (all lengths in mm); no trigonometric functions (angles). |
| Validation | `validator`: regeneration, invariants (`check_invariants`), perturbation, measured shared-size checks; `heal_growth_breaks` | No rank/DOF report; no reference/basic markers; no projected-length check. |
| Cross-view | `crossview.view_links` (faces, sheet-relative tolerance, strong/weak thresholds); linked views analysed as one unit; `SharedParam` bindings with `status` drives / worked_out / refused / pending; `_same_size` adoption (since today) | Correspondences are axis-level, not feature-pair records. |
| LLM contract | `ai/agent.py` tools (`define_parameter` with `candidate` or `from_line`/`to_line`, `set_formula`, `define_part`, …), each edit validated; Pydantic schemas; DATA_RULE; staged sheet → unit → shared calls | The model can still name a line pair freely where a dimension exists. M4 makes dimensions candidate-choice only. SoM overlays are not yet drawn from the state. |
| Ledger, revisions | The unit's `answer` dict, undo/redo of whole states, project fingerprint | Proposals are not separate from accepted state; no staleness by referenced entity. M3. |
| Robustness | Stall watchdog, step deadline, retries → fallback model (`c01d274`) | — |

The order to build: **M1 → M2 → M3 → M4** turn the existing engine into the design above without a second engine.
M5–M6 make the accuracy claims measurable. M7–M9 widen the inputs.

---

## 11. Verified capabilities (sources) vs design choices

**Verified in current documentation:**

- **ezdxf DIMENSION.** `defpoint` is the dimension-line location for linear dimensions; `defpoint2`/`defpoint3` are
  the extension-line origins. `defpoint4`/`defpoint5` serve diameter, radius and angular types (`defpoint5` locates
  the arc of angular dimensions). `dimtype` codes are 0 linear/rotated, 1 aligned, 2 angular, 3 diameter, 4 radius,
  5 angular-3P, 6 ordinate, 8 arc. `get_measurement()` returns the measurement in WCS units. Text `"<>"` or empty
  means "draw the measurement". The page does not document DIMASSOC, and dimensional constraints are "not supported
  by ezdxf". — [ezdxf: Dimension](https://ezdxf.readthedocs.io/en/stable/dxfentities/dimension.html)
- **DXF associativity.** `$DIMASSOC` = 2 creates associative dimensions "coupled with association points on
  geometric objects". The DIMASSOC object stores per-point association flags, an osnap type, and the ID of the main
  (and intersection) geometry, with subentity type and GsMarker. —
  [Autodesk DXF: header variables](https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-DXF/files/GUID-A85E8E67-27CD-4C59-BE61-4DC9FADBE74A.htm),
  [Autodesk DXF: DIMASSOC](https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-DXF/files/GUID-C0B96256-A911-4B4D-85E6-EB4AF2C91E27.htm)
- **PyMuPDF.** `Page.get_drawings()` returns paths whose items are lines `l`, rectangles `re`, quads `qu` and cubic
  Béziers `c`. "At least four curves are needed to draw a circle". Clipping is ignored ("will always return all
  paths"). The `rawdict` text extraction gives spans and per-character `bbox`/`origin`, and a line-level `dir`
  writing direction. —
  [PyMuPDF: drawing and graphics](https://pymupdf.readthedocs.io/en/latest/recipes-drawing-and-graphics.html),
  [PyMuPDF: TextPage](https://pymupdf.readthedocs.io/en/latest/textpage.html)
- **Gemini.**
  - Bounding boxes come as `[ymin, xmin, ymax, xmax]` normalised to 0–1000 —
    [Gemini: image understanding](https://ai.google.dev/gemini-api/docs/image-understanding).
  - `media_resolution` per media item on Gemini 3 models: low 280, medium 560, high 1120, ultra_high 2240 tokens per
    image, with `high` "optimal for most use cases" —
    [Gemini: media resolution](https://ai.google.dev/gemini-api/docs/media-resolution).
  - Structured output supports a JSON Schema subset and guarantees syntactically valid JSON. You must "always
    validate values in your application". Combining it with tools is a Gemini 3 preview feature —
    [Gemini: structured output](https://ai.google.dev/gemini-api/docs/structured-output).
  - Function calling: the model does not execute functions. Modes are auto / any / none / validated —
    [Gemini: function calling](https://ai.google.dev/gemini-api/docs/function-calling).
- **Set-of-Mark prompting.** Marks (numbers, boxes, masks) drawn on image regions improve a multimodal model's visual
  grounding, zero-shot. A follow-up notes that other multimodal models struggle with such tags without training. —
  [Yang et al., arXiv 2310.11441](https://arxiv.org/abs/2310.11441),
  [arXiv 2404.16375](https://arxiv.org/abs/2404.16375)
- **SymPy.** `sympify` "uses `eval`, and thus shouldn't be used on unsanitized input" —
  [SymPy core](https://docs.sympy.org/latest/modules/core.html)
- **Pint.** It parses quantities from strings; incompatible conversions raise `DimensionalityError`; quantities
  expose `.dimensionality` — [Pint tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html)
- **Solvers.**
  - `planegcs` (PyPI) wraps FreeCAD's PlaneGCS 2D solver (LGPL-2.1-or-later) — [planegcs](https://planegcs.readthedocs.io).
  - `py-slvs` binds a fork of SolveSpace 2.3 — [py-slvs](https://pypi.org/project/py-slvs).
  - `python-solvespace` wraps SolveSpace's solver; the docs disagree on its module name —
    [python-solvespace API](https://pyslvs-ui.readthedocs.io/en/latest/python-solvespace-api/).
  - Maintenance status and licences beyond planegcs's are not verified here.
- **STEP AP242 PMI.** Semantic PMI (representation) is computer-interpretable; graphic PMI is presentation only.
  Current recommended practices: v4.1 (2024-06-20). The exact rules for linking a dimension to faces were not
  verified here. — [MBx-IF recommended practices](https://www.mbx-if.org/home/?p=194),
  [NIST](https://www.nist.gov/node/413991)
- **Reference and basic dimensions.** Reference dimensions are shown in parentheses (or "REF") and are informational
  only. Basic dimensions are boxed and theoretically exact. Secondary sources only; check ASME Y14.5 itself before
  relying on details. — [machinistguides](https://www.machinistguides.com/tag/reference-dimensions/),
  [metalcraft](https://metalcraftind.com/definition-of-terms-basic-dimensions-gdandt/)
- **build123d.** Builder and algebra APIs; its shapes are CadQuery Direct API objects —
  [build123d key concepts](https://build123d.readthedocs.io/en/latest/key_concepts.html)

**Design choices (mine, not verified facts):**

- the View State structure;
- locus-based association and its method ranking;
- the value classes;
- the tolerance formulas of §6.2;
- the ledger states and auto-accept policy;
- the candidate-choice LLM contract;
- the use of a second, overlay-only image;
- the per-axis DAG with local solver blocks;
- the milestone order.

The token estimates in §7.4 are estimates, not measurements.
