"""The CAD JSON, the regions it is built on, and design intent checked by measurement — no AI calls:
answers are written here; true claims must be confirmed, false ones contradicted with the measurement."""

from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam.analyse import analyse
from dxf_autoparam.cadjson import cad_json, entity_index, write_split
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.topology import of
from dxf_autoparam.validator import apply, baseline

ROOT = Path(__file__).resolve().parents[1]


def two_cell():
    dr, _ = read_dxf(str(ROOT / "examples" / "two_cell_box_section.dxf"))
    return analyse(dr)


# ── regions and the CAD JSON ─────────────────────────────────────────────────────


def test_regions_of_a_box_section_nest_and_carry_their_material():
    an = two_cell()
    regions = of(an).regions
    assert len(regions) == 4
    concrete = max(regions, key=lambda r: len(r.holes))
    assert len(concrete.holes) == 2 and concrete.pattern  # the box concrete, hatched, with two cells in it
    cells = [r for r in regions if r.parent == concrete.id]
    assert len(cells) == 2 and all(r.pattern is None for r in cells)
    u = an.drawing.units_mm
    assert concrete.area * u * u == pytest.approx(7000 * 3750 - sum(c.area * u * u for c in cells), rel=1e-6)
    assert all(concrete.id in c.neighbours for c in cells)


def test_regions_are_found_in_loose_lines_split_at_t_junctions_and_crossings(tmp_path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in (((0, 0), (4000, 0)), ((4000, 0), (4000, 2000)), ((4000, 2000), (0, 2000)), ((0, 2000), (0, 0)),
                 ((1000, 0), (1000, 2000)),  # ends on the outline: T-junctions
                 ((-500, 1000), (4500, 1000)),  # crosses three lines in their interiors
                 ((4000, 2000), (5500, 3000))):  # a dangling slope line: bounds nothing
        msp.add_line(a, b)
    path = tmp_path / "lines.dxf"
    doc.saveas(path)
    dr, _ = read_dxf(str(path))
    topo = of(analyse(dr))
    areas = sorted(round(r.area * dr.units_mm ** 2 / 1e6, 3) for r in topo.regions)
    assert areas == [1.0, 1.0, 3.0, 3.0]
    ground = next(it.index for it in dr.items if it.pts[-1][0] == pytest.approx(5500))
    assert ground in topo.open_items
    assert all(len(r.neighbours) == 2 for r in topo.regions)


def test_the_cad_json_says_what_each_thing_measures_and_touches(tmp_path):
    an = two_cell()
    doc = cad_json(an, baseline(an))
    json.dumps(doc)  # plain data
    ids = [e["id"] for e in doc["entities"]]
    assert len(ids) == len(set(ids)) == len(an.drawing.items)
    assert all(entity_index(i) is not None for i in ids)
    dims = [e for e in doc["entities"] if e["type"] == "DIMENSION" and e.get("measurement") == 3000]
    assert dims and all(d.get("candidate") and None not in d["between_datums"] for d in dims)
    assert any(e.get("measures_entities") for e in doc["entities"] if e["type"] == "DIMENSION")
    hatch = [e for e in doc["entities"] if e["type"] == "HATCH"]
    assert hatch and all(h["fills_regions"] for h in hatch)
    kinds = {r["type"] for r in doc["relationships"]}
    assert {"thickness", "opening", "mirrored_regions", "repeated_regions", "inside"} <= kinds
    opening = next(r for r in doc["relationships"] if r["type"] == "opening" and r["value"] == 3000)
    assert opening["across_region"] in {r["id"] for r in doc["topology"]["regions"]}
    written = write_split(doc, str(tmp_path / "split"))
    assert {Path(p).name for p in written} == {"drawing.json", "geometry.json", "topology.json", "datums.json", "relationships.json", "parameters.json"}
    small = cad_json(an, baseline(an), for_ai=True)
    assert len(json.dumps(small)) < len(json.dumps(doc))


# ── design intent ────────────────────────────────────────────────────────────────


def answer(an, **extra):
    regions = of(an).regions
    concrete = max(regions, key=lambda r: len(r.holes))
    cells = sorted((r for r in regions if r.parent == concrete.id), key=lambda r: r.bbox[0])
    pcc = next(r for r in regions if r is not concrete and r not in cells)
    cand = {(c.kind.value, round(c.value * an.drawing.units_mm), tuple(sorted(c.axes))): c.id for c in an.clusters.values()}
    ans = {
        "structure_type": "RCC box culvert, 2 cells", "family": "rcc_box", "views": ["section"], "summary": "",
        "components": [
            {"name": "Box", "type": "box", "level": "assembly", "regions": [concrete.id], "confidence": 0.95},
            {"name": "CellLeft", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cells[0].id]},
            {"name": "CellRight", "type": "cell", "level": "subcomponent", "parent": "Box", "regions": [cells[1].id]},
            {"name": "PccCourse", "type": "courses", "level": "component", "regions": [pcc.id], "confidence": 0.6},
        ],
        "levels": [],
        "parameters": [
            {"name": "ClearSpan", "label": "", "component": "Box", "candidate": cand[("void", 3000, ("x",))], "value": 3000},
            {"name": "OuterWall", "label": "", "component": "Box", "candidate": cand[("solid", 350, ("x",))], "value": 350},
        ],
        "datum_formulas": [], "relations": [], "behaviours": [], "constraints": [], "questions": [],
    }
    ans.update(extra)
    return ans


def test_behaviours_are_measured_not_believed():
    an = two_cell()
    ans = answer(an, behaviours=[{"parameter": "ClearSpan", "effects": [
        {"target": "Box", "behaviour": "grows", "axis": "x"},  # true
        {"target": "Box", "behaviour": "fixed", "axis": "y"},  # true
        {"target": "CellLeft", "behaviour": "grows", "axis": "x"},  # true
        {"target": "PccCourse", "behaviour": "fixed"},  # false: the course runs under the whole box
    ]}])
    prog, rep = apply(an, ans)
    rows = {(r["target"], r["behaviour"]): r for r in prog.intent["behaviours"]}
    assert rows[("Box", "grows")]["status"] == "confirmed"
    assert rows[("Box", "fixed")]["status"] == "confirmed"
    assert rows[("CellLeft", "grows")]["status"] == "confirmed"
    assert rows[("PccCourse", "fixed")]["status"] == "contradicted"
    assert "grows x" in rows[("PccCourse", "fixed")]["measured"]
    assert any(e["code"] == "V12" and "PccCourse" in e["item"] for e in rep.errors())
    assert "grows x" in prog.intent["impact"]["ClearSpan"]["Box"]
    assert any(r["name"] == "PccCourse" for r in prog.intent["review"])  # 0.6 confidence goes to a person


def test_constraints_hold_are_enforced_or_are_rejected():
    an = two_cell()
    ans = answer(an, constraints=[
        {"type": "symmetric", "datums": ["x1", "x11", "x6"], "description": "box symmetric about its centre line"},
        {"type": "distance", "datums": ["x1", "x2"], "value": "OuterWall"},
        {"type": "distance", "datums": ["x1", "x12"], "value": "7150", "description": "course end fixed from the left face"},
        {"type": "symmetric", "datums": ["x1", "x12", "x6"], "description": "false: not mirrored"},
    ])
    prog, rep = apply(an, ans)
    rows = {r["label"]: r for r in prog.intent["constraints"]}
    assert rows["box symmetric about its centre line"]["status"] == "always"
    assert rows["distance x1 x2"]["status"] == "always"
    kept = rows["course end fixed from the left face"]
    assert kept["status"] == "always" and kept["enforced_on"] == "x12"  # the engine rewrote x12 to keep it
    dv = prog.datum_values({"ClearSpan": 3500})
    assert (dv["x12"] - dv["x1"]) * an.drawing.units_mm == pytest.approx(7150)
    assert rows["false: not mirrored"]["status"] == "false"
    assert any(e["code"] == "V13" for e in rep.errors())
    r = regenerate_program(prog)
    assert not r.issues


def test_a_person_can_hold_parts_and_keep_values_as_drawn():
    an = two_cell()
    ans = answer(an)
    prog, _rep = apply(an, ans, selection={"hold": ["PccCourse"], "exclude": ["OuterWall"]})
    assert "OuterWall" not in prog.params and "ClearSpan" in prog.params
    assert next(c for c in prog.components if c.name == "PccCourse").held
    before = prog.datum_values()
    after = prog.datum_values({"ClearSpan": 3500})
    assert after["x12"] == pytest.approx(before["x12"])  # the held course keeps its drawn end
    assert after["x11"] != pytest.approx(before["x11"])  # the box still grows
    assert (after["x2"] - after["x1"]) * an.drawing.units_mm == pytest.approx(350)  # the wall keeps its drawn size
    r = regenerate_program(prog)
    assert not r.issues
    # the AI's own recommendation is the default selection
    ans2 = answer(two_cell())
    ans2["components"][3]["parametrize"] = False
    prog2, _ = apply(two_cell(), ans2)
    assert prog2.intent["selection"]["hold"] == ["PccCourse"]


# ── learning from an example ─────────────────────────────────────────────────────


def test_an_edit_the_program_can_make_is_explained_exactly(tmp_path):
    from dxf_autoparam.dxf_write import write_dxf
    from dxf_autoparam.learn import learn

    src = ROOT / "examples" / "two_cell_box_section.dxf"
    an = two_cell()
    prog = baseline(an)
    span = next(n for n, p in prog.params.items() if p.value == 3000 and p.measures and p.measures[0].startswith("x"))
    out = tmp_path / "wider.dxf"
    write_dxf(prog, regenerate_program(prog, {span: 3500}), str(out))
    lesson = learn(str(src), str(out), prog)
    assert lesson["fit"]["changes"] == {span: pytest.approx(500)}
    assert lesson["fit"]["unexplained"] == []
    changed = {s["candidate"]: s for s in lesson["sizes_changed"]}
    assert any(s["uniform"] and s["to"] == [3500] for s in changed.values())
    assert lesson["sizes_unchanged"] > 5  # wall, slab, haunch … the invariants of that edit
    assert any("grows x" in v for v in lesson["parts"].values())


def test_an_edit_the_program_cannot_make_is_pointed_out(tmp_path):
    from dxf_autoparam.learn import learn

    src = ROOT / "examples" / "two_cell_box_section.dxf"
    doc = ezdxf.readfile(src)
    moved = 0
    for e in doc.modelspace().query("LWPOLYLINE"):
        pts = [tuple(p) for p in e.get_points("xyseb")]
        if any(abs(p[0] - 7150) < 1e-6 for p in pts):  # a designer drags only the course's right end
            e.set_points([(p[0] + 100 if abs(p[0] - 7150) < 1e-6 else p[0], *p[1:]) for p in pts], format="xyseb")
            moved += 1
    assert moved
    out = tmp_path / "dragged.dxf"
    doc.saveas(out)
    an = two_cell()
    prog = baseline(an)
    lesson = learn(str(src), str(out), prog)
    assert lesson["fit"]["unexplained"], lesson["fit"]
    assert any("does not" in r for r in lesson["rules"])


def test_holding_existing_work_splits_the_line_it_shares_with_the_proposed(tmp_path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (1000, 0), (1000, 500), (0, 500)], close=True)  # existing box
    msp.add_lwpolyline([(1500, 0), (2500, 0), (2500, 500), (1500, 500)], close=True)  # proposed box, same top line
    path = tmp_path / "pair.dxf"
    doc.saveas(path)

    def run(hold: bool):
        dr, _ = read_dxf(str(path))
        an = analyse(dr)
        regions = sorted(of(an).regions, key=lambda r: r.bbox[0])
        y0 = next(d.id for d in an.datums.values() if d.axis == "y" and abs(d.value) < 1e-6)
        y1 = next(d.id for d in an.datums.values() if d.axis == "y" and abs(d.value - 500) < 1e-6)
        ans = {"structure_type": "box extension", "family": "rcc_box", "views": [], "summary": "", "levels": [], "relations": [],
               "behaviours": [], "constraints": [], "questions": [],
               "components": [{"name": "ExistingBox", "type": "box", "existing": True, "regions": [regions[0].id]},
                              {"name": "ProposedBox", "type": "box", "regions": [regions[1].id]}],
               "parameters": [{"name": "ClearHeight", "label": "", "component": "ProposedBox", "from_datum": y0, "to_datum": y1, "value": 500}],
               "datum_formulas": [{"datum": y1, "expr": f"{y0} + ClearHeight"}]}
        prog, rep = apply(an, ans, hold_existing=hold)
        r = regenerate_program(prog, {"ClearHeight": 700})
        tops = {i: max(p[1] for p in r.pts[i]) for i in (0, 1)}
        return prog, rep, tops

    prog, rep, tops = run(False)
    assert tops == {0: pytest.approx(700), 1: pytest.approx(700)}  # one line: both grow
    assert any(f.code == "V15" for f in rep.findings)  # and a person is told
    prog, rep, tops = run(True)
    assert tops == {0: pytest.approx(500), 1: pytest.approx(700)}  # the existing box stays as built
    assert "grows y" in prog.intent["impact"]["ClearHeight"]["ProposedBox"] and "ExistingBox" not in prog.intent["impact"]["ClearHeight"]
