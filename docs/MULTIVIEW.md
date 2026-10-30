# A whole GAD sheet, parametric across its views

**Import → understand → separate views → select components → parameterize → edit → propagate → validate → export.**
This document is the architecture assessment and the guide for the multi-view work in `dxf-autoparam` (branch
`feat/dxf-autoparam`). Every number below was measured in this repository; nothing here was run against Gemini live.

---

## 1. Assessment: where it started, what stopped the workflow

| What existed (single view) | What stopped a whole-sheet workflow |
|---|---|
| A robust DXF reader (blocks, broken files, dimensions), a generic analysis (set-out lines → gaps → candidate sizes → regions), a UPCE-style program (parameters → formulas → lines), closed-form regeneration, a validator (named sizes drive their lines, measured behaviours and constraints), DXF export that edits the original, a tool-using Gemini agent | **Views**: a sheet was one drawing, or one bounding box a person picked. One sheet-wide line merged every view (`BRG. NO.80`: 1 view of 22 831 entities). |
| A demo page (SVG) | **No cross-view model**: a size shown in an elevation and in its plan was two unrelated numbers; editing one left the other stale. |
| Notes that state a *named* value follow it | **Numbers nobody named did not follow** (an overall width, an exploded dimension). |
| | **The page could not hold a sheet**: 24 195 SVG elements, a zoom frame of 67.5 ms, 67 s to open. |

**Decision.** The DXF → parametric engine is `dxf-autoparam` (the owner chose a standalone Python prototype; it is the
only code in the workspace that imports an arbitrary DXF into a parametric model). The multi-view system *extends* it:
the same validated engine builds every view's program, and a sheet layer above it links them. No second parametric
engine was written. `aagento-bridge` (its UPCE kernel builds drawings from a reading, by recipe) and
`Aagento-GAD-Foundation-Model` were not touched.

## 2. Three layers

```
DRAWING      the DXF as read: entities, coordinates, layers, dimensions, texts           (dxf_read.py — never edited)
   │
SEMANTIC     views, tables, notes, title block            sheet.py      (logical: lists of entity indices)
             projection links between views, relations    crossview.py  (view_links, accept_link, relations)
   │
PARAMETRIC   one program per UNIT — a LOCAL SYSTEM: one view, its own set-out, dependency graph, values and frame
             shared parameters bound by name into several units: the ONE authoritative value of a quantity several views show
             projection links as explicit constraints between local systems  projection.py, crossview.py (SheetModel)
             (a sheet saved before 2026-10-29 with views joined in one unit reads as it was made: systems = "joined")
   │
EXECUTION    regenerate only what a change touches; check the whole sheet; commit or refuse     crossview.py
VALIDATION   per view (collapse, flip, inside-out), across views (every bound size measures the shared value),
             annotations (numbers = measured distances; notes pushed onto notes reported)
```

## 3. Views (`sheet.py`)

1. **Frame** — the outermost rectangle holding nearly every entity (a double border is one frame); anything outside is
   *stray*. A drawing's own outline with its dimensions outside it is not a border (reader fix).
2. **Panel rules** — long straight lines joined to the frame through other long lines (a notes column, the title
   block's rules). They part the sheet; views never grow across them.
3. **Watermark** — one text repeated across the sheet (a converter's stamp).
4. **Pieces** — the structural geometry rasterized (800 cells on the long side), touching parts are atoms; a wave grown
   from every atom measures the white space between them; geometry closer than 0.5 % of the sheet is one piece.
5. **Merges** — a piece joins a bigger one when it lies mostly inside its extent (a section's level lines), when their
   extents mostly overlap, when it is a small satellite close by (a dimension chain, a mark), when it is a thin chain
   set out on the other's lines (an exploded dimension's ticks), or when it is the titled part of an untitled body —
   **never across two different titles**.
6. **Titles** — texts with view words (plan, section, elevation, detail, arrangement — `knowledge/drafting.json`,
   drafting conventions only) matched to pieces by casting rays both ways from the title, cheapest first (a view stands
   over its title; a table hangs under its heading); a piece takes a second title only beside its first (halves of one
   figure). Underlines go with their title.
7. **Annotation** — a dimension joins the view of the points it measures, a leader the view it points into, a word the
   nearest view within eight of the sheet's text heights.
8. **Kinds** — table (straight rules on a grid with words; also a grid of small walled panels), notes, title block (its
   ownership words), view. Each view gets a type, a stated scale, and its own drawing unit when its dimensions agree on
   another scale (a 1:25 detail on a 1:100 sheet). What is unsure becomes a question, not a decision. The number a dimension
   states is read from its own text, or — for an automatic dimension, which has none — from the text of the block CAD draws it
   with. Work saved while such a view was still read at the sheet's scale carries every value times one ratio: they are
   measured again (`validator.rescale_values`, only when every measurable value of the unit is off by the same drafting ratio),
   and the names, parts and levels are kept.

Measured on four real sheets (VERIFIED, `tests/test_sheet.py` + overlays):

| Sheet | Entities | Read + segment | What it found |
|---|---|---|---|
| `gad_ezdxf_b` | 370 | 1.3 s | composite half section & half elevation, C/S of return wall (1:100), hydraulic table, track-structure table, title block |
| `gad_ezdxf_a` | 2 076 | 1.7 s | longitudinal section X-X (1:100) and plan top (linked), half section & half elevation, cross section of the box, 5 sections at 1:25, sectional elevation, 3 tables, title block |
| `mib173` | 2 349 | 1.5 s | A-A and D-D composites, half plans, section B-B, return wall at C-C, wing / return wall details, toe wall, 4 tables |
| `BRG. NO.80 (Doubling)` (PDF conversion) | 24 193 | 2.2 s (sheet open 4–6 s) | PRO and EXG half elevation/section, site plan, half plans, sectional elevation X-X, toe wall, drop wall, inspection steps, return wall, junction arrangement, typical details, hydraulic and span tables, title block |

## 4. One model across views (`crossview.py`)

- **Projection links.** Two views at one scale, one over the other (or side by side), that share enough *faces* — the
  x of vertical edges / the y of horizontal ones at least 3 % of the view long, matched to 1/10 000 of the sheet — are
  drawn in projection. Strong links (≥ 6 faces and ≥ 25 % of the smaller view's, or ≥ 4 and ≥ 60 %) are taken; weak ones
  are proposals a person or the views stage confirms. Counting every vertex instead linked all 16 views of the PDF
  conversion by chance; exact CAD tolerance missed its noise.
- **Units are local systems (2026-10-29).** Every view is a unit of its own: its analysis, its program (one dependency graph), its
  values and its frame (frames.py: millimetres from its own origin, RL where it states a level; to the sheet and back exactly). A change
  regenerates the units it reaches and nothing else; the design intent of a view is tried on that view alone (a joined section and plan
  took 2–4 minutes per commit, and a clash in the plan refused the section's sides). A projection link joins nothing; it is an explicit
  constraint (projection.py):
  - **faces** — the lines of the two views on the link's axis that stand at one sheet coordinate (to the precision the link was found with);
  - **values** — a size one view names between two such faces, or a level on one, is ONE shared value bound in both, when that view commits
    (or shares it): the other view takes the same name (its own name for that size gives way), or is bound by its two lines there. A view
    that cannot take it is said in the commit's `projection` rows, never forced. One undo takes the commit and its bindings back;
  - **alignment** — after any change the common faces still stand in line: each moves as its counterpart does (check PROJECTION, refusal kind
    incomplete_model, naming both views and the faces). A held line (dismantled work, a boundary, a part kept as drawn) is no face;
  - **sides** — a side chosen for a shared value (`anchor`: start = left or bottom, end = right or top, centre) is chosen in every view drawn
    in projection with it, in that view's own set-out; if one view cannot take it the whole choice is refused and says which view and why. The
    side the engine derives for a shared value in one view is the first it tries in the other ("drawn in projection with V01, where ClearSpan
    grows about its centre"), with the faces the first view moves with that value made members of the second view's assembly too (each view's
    own connectivity would otherwise decide what follows — a wall face connected to the span in the section and not in the plan stayed in the
    plan while it moved in the section), so both grow alike unless the drawing says otherwise; what still does not line up is refused, said.
  A sheet saved with joined units (a unit named by two views, U01_03) keeps them (`systems: "joined"` in the project; AUTOPARAM_SYSTEMS=joined
  opens a fresh sheet that way): its answers number the joined unit's lines, candidates and entities, and are read as they were made.
- **Units on a joined sheet.** Linked views are analysed together: a face they share is ONE set-out line, so a change in one view changes
  the other by construction. Distances between them across the projection are sheet layout and are dropped.
- **Shared parameters.** A size two separate views both state (a dimension or a note in each) is proposed; a person or
  Gemini names it; `share()` binds the name into each unit's answer and every unit is rebuilt by the validated engine —
  refused as a whole when the views do not state one size or it drives none of them.
- **Regeneration** touches only the units a change reaches; every bound size is re-measured on its own lines in every
  view (`"that view did not follow"` otherwise); a change is **committed only if the whole sheet holds**.
- **Design intent is asked, not assumed**: `growth()` measures which line of a size moves (start / end / both about a
  centre line); `anchor()` lets a person choose the line that stays; `valid_range()` finds how far a value can go and
  names the first entity that would break.
- **Edits are transactions** with undo / redo: values, shares, renames (everywhere: formulas, relations, behaviours,
  every bound unit — value and effect unchanged, refused when the name is taken or not PascalCase), anchors, links,
  view corrections (rename, retype, merge, split by a drawn box). The project (decisions, answers, shared values) saves
  as JSON keyed to the DXF's fingerprint.

## 5. Dimensions and annotations

- A number no named value matches is linked to the **distance between the two set-out lines it is written between**
  (best evidence: a dimension line whose ends sit on those lines, the number beside it — an exploded dimension). Sizes
  nobody named (an overall width) follow; an ambiguous fit is left as written.
- A dimension whose text was typed over with its own number shows (and exports) the new measurement; dimensions are
  re-rendered on export; notes keep their place against the line they label.
- A note a change pushes onto another note of its view is **reported**, never silently overlapped or moved.

## 6. Gemini (`ai/sheet_ai.py`) — staged, checked, never trusted blindly

| Stage | Input | Output (schema-validated) | What the engine accepts |
|---|---|---|---|
| Views | the sheet picture, every group boxed and labelled; the groups (titles, prominent words, counts, links) | names, types, kinds, merges, relations (projection / same structure / detail of), questions | existing ids only; a projection only where the views share set-out lines |
| Units | one unit's own drawing — the existing tool-using agent | its parametrization (small checked edits) | the agent's validated answer, as one undoable edit |
| Shared | the units' named values + the sizes two views state | named shared sizes | `share()`: the values must agree |

Text from the DXF travels only as quoted data inside JSON (a test writes an instruction on the sheet and checks it is
data). The workspace runs each stage in the background with streamed thoughts and **Stop**. **Every run is billed;
none was made in this work.**

## 7. The workspace (`static/workspace.html`, `workspace.py`)

Canvas renderer (batched paths, viewport culling on a grid index, text level of detail); cursor-centred zoom; middle /
space / right-drag pan; fit sheet (F), view (V), selection (Shift+F); click, Shift add, Ctrl/⌘ remove; window (drag →)
and crossing (drag ←) selection; a structure / annotation filter; Esc backs out one step; undo / redo
(Ctrl/⌘ Z). Panels: Sheet (views, links, tables, notes), Parameters (shared and the open unit's, edit in place),
Review (views to confirm, shared-size proposals, checks), Gemini (the three stages, progress, Stop); an inspector for an
entity, a view (correct it; name a size) or a value (preview before apply, valid-range slider, how it grows and the line
that stays, impact per view, rename, stop sharing). The classic single-view page is at `/classic`.

Benchmarks (headless Chrome over the DevTools protocol, `tools/bench_ui.mjs`; 1680 × 1000):

| Sheet | Entities | Sheet ready | Geometry (gzip) | Page loaded | Full-sheet frame (median / p95) | Hit test |
|---|---|---|---|---|---|---|
| small (`two_cell_box_section`) | 20 | 1.8 s | — | 0.21 s | 1.3 / 1.8 ms | < 1 ms |
| medium (`gad_ezdxf_a`) | 2 076 | 2.6 s | 95 kB | 0.22 s | 1.6 / 3.2 ms | < 1 ms |
| large (`BRG. NO.80`) | 24 193 | 5.8 s | 297 kB | 1.1 s | 4.0 / 12.2 ms (zoomed in on text: 14 / 20 ms) | < 0.5 ms |
| large, the old SVG page | 24 195 SVG elements | 67 s | 5.6 MB | — | zoom 67.5 ms, redraw 116 ms | — |

Opening the biggest view of the large sheet (8 203 entities) analyses its unit once: 1.2–3.7 s.

## 8. The end-to-end walk-through (VERIFIED in the page, `gad_ezdxf_a`)

1. The sheet opens: 20 views, 3 tables, title block; LONGITUDINAL SECTION(X-X) and PLAN TOP are linked (8 common faces).
2. In the section, the size written "BARREL LENGTH = 11740" in both views is named `BarrelLength`; the engine measures it
   grows at its upstream end; the person chooses "start stays" (the upstream wall stays).
3. Valid range 7 782 – 14 380 mm, each limit with the entity that would break first.
4. Preview 13 000: 347 entities change — section 216, plan 131 — the other 18 views stay. Apply.
5. Export: 643 entities updated, 77 dimensions re-rendered (0 failed), both barrel notes read 13 000, the two reshaped
   view blocks written out, 1 380 entities kept; the file re-opens with 0 audit errors. Undo restores 11 740.

The engine repaired five lines the set-out had hung on the wrong chain (each said in words, e.g. *"x92 was dragged by
BarrelLength through x106 − GapX21; it is set out from x93 instead"*).

## 9. Tests

`tests/test_sheet.py` (segmentation, built and real sheets), `tests/test_crossview.py` (projection units, shared sizes,
refusals, rename / undo, anchors, persistence, export, the real sheet), `tests/test_workspace_api.py` (the HTTP API as the
page uses it, a background Gemini stage), `tests/test_sheet_ai.py` (the three stages with scripted Gemini),
`tests/test_annotations.py` (exploded dimensions, typed-over dimensions, overlaps), plus the earlier suites and the
generic property check. `uv run pytest` — 155 passed; `uv run ruff check src tests` — clean.

## 10. What remains (honest)

- **PDF-converted sheets** (`BRG. NO.80`): views, units, editing and export work, but its exploded dimensions do not
  yield a consistent drawing scale (number ÷ nearest line ranges 0.3 – 117), so its written sizes are not linked. It needs
  a recognizer of exploded dimensions (arrows, extension lines) or Gemini reading values off the picture.
- **Which line stays** is the engine's first guess until a person (or the agent) anchors it; on `gad_ezdxf_a` the track
  centre line follows the barrel's free end until pinned.
- **Segmentation** can leave a few small fragments or read a stray duplicate title; the page offers merge / split /
  retype and the views stage reviews it. Two-title clusters are asked about, not split.
- **Gemini stages** are tested with scripts only; one consented live run is the next step.
- Overlaps are reported, not resolved; history lives in memory (the project file keeps decisions and values); no 3-D
  model is invented — cross-view links are projections and named correspondences.
