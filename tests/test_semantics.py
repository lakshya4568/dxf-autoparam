"""What the drawing's words and colours MEAN, from evidence: notes tied to what their leaders touch (or left unresolved),
level notes to their lines, titles to their views; existing / proposed from the drawing's own conventions, never from a
colour alone; duplicates found and never merged; and each annotation behaving as it should when the geometry changes."""

from __future__ import annotations

import ezdxf
import pytest

from dxf_autoparam.annotations import associate, classify_text, text_states
from dxf_autoparam.behaviour import behaviour_report
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.duplicates import find_duplicates
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.layers import classify_status, layer_report
from dxf_autoparam.understanding import duplicates, layers, sheet_annotations, statuses


def section(path) -> str:
    """A box: walls and slabs as loose lines, a 150 mm course under it; notes the way GADs write them."""
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("PROPOSED_BOX", color=1)
    doc.layers.add("EXISTING_GROUND", color=3)
    doc.layers.add("NOTES", color=7)
    msp = doc.modelspace()
    P = {"layer": "PROPOSED_BOX"}
    for a, b in [((0, 0), (7200, 0)), ((7200, 0), (7200, 6200)), ((7200, 6200), (0, 6200)), ((0, 6200), (0, 0)),
                 ((600, 600), (6600, 600)), ((6600, 600), (6600, 5600)), ((6600, 5600), (600, 5600)), ((600, 5600), (600, 600)),
                 ((0, -150), (7200, -150)), ((0, -150), (0, 0)), ((7200, -150), (7200, 0))]:
        msp.add_line(a, b, dxfattribs=P)
    msp.add_line((-3000, 6200), (-500, 6200), dxfattribs={"layer": "EXISTING_GROUND"})  # a ground line, existing
    N = {"layer": "NOTES"}
    # a leader note on the top slab
    msp.add_leader([(3600, 5900), (4200, 7000), (5600, 7000)], dxfattribs=N)
    msp.add_text("TOP SLAB", height=200, dxfattribs={**N, "insert": (4250, 7050)})
    # a material note whose leader points between the two faces of the 150 mm course
    msp.add_leader([(2000, -75), (1500, -900), (300, -900)], dxfattribs=N)
    msp.add_text("150 THK. PCC BASE COURSE", height=150, dxfattribs={**N, "insert": (300, -870)})
    # a level note beside the top line
    msp.add_text("TOP OF SLAB 101.500", height=150, dxfattribs={**N, "insert": (-2900, 6250)})
    msp.add_text("BOTTOM OF BASE 95.150", height=150, dxfattribs={**N, "insert": (-2900, -100)})
    msp.add_line((-3000, -150), (-500, -150), dxfattribs=N)
    # a note far from everything, and one half way between two walls' faces
    msp.add_text("SEE NOTES FOR MATERIALS", height=150, dxfattribs={**N, "insert": (12000, 3000)})
    msp.add_text("VOID", height=150, dxfattribs={**N, "insert": (3480, 3100)})
    # the view title (with its scale line), a reference dimension and a chain with its total
    msp.add_text("SECTION A-A", height=300, dxfattribs={**N, "insert": (2600, -2400)})
    msp.add_text("SCALE 1:100", height=200, dxfattribs={**N, "insert": (2800, -2900)})
    for p1, p2, base, txt in [((0, 6200), (600, 6200), 7400, "<>"), ((600, 6200), (6600, 6200), 7400, "<>"),
                              ((6600, 6200), (7200, 6200), 7400, "<>"), ((0, 6200), (7200, 6200), 8000, "<>"), ((0, 0), (0, 6200), -1200, "(6200)")]:
        if p1[0] == p2[0]:
            d = msp.add_linear_dim(base=(base, 3000), p1=p1, p2=p2, angle=90, text=txt, dxfattribs=N)
        else:
            d = msp.add_linear_dim(base=(3600, base), p1=p1, p2=p2, text=txt, dxfattribs=N)
        d.render()
    doc.saveas(path)
    return str(path)


@pytest.fixture
def sm(tmp_path):
    return SheetModel.open(section(tmp_path / "section.dxf"))


def ann(sm, text):
    return next(a for a in sheet_annotations(sm) if a["text"].startswith(text))


def test_notes_are_classified_by_what_they_say_never_by_holding_a_number():
    assert classify_text("150mm THK. PCC BASE COURSE")[0] == "material"
    assert text_states("150mm THK. PCC BASE COURSE")["thickness_mm"] == 150
    assert classify_text("TOP OF SLAB 748.159")[0] == "level"
    assert classify_text("SLOPE 2(H) : 1(V)")[0] == "slope"
    assert classify_text("SUITABLE SOLING TO BE PROVIDED AS PER SITE REQUIREMENTS")[0] == "construction_note"
    assert classify_text("C.L. OF EXIST. BG TRACK")[0] == "status"
    assert classify_text("SECTION B-B")[0] == "section_label"
    assert classify_text("HAUNCH 300 x 300")[0] == "component_label"


def test_a_leader_note_names_what_its_tip_touches_and_follows_it(sm):
    a = ann(sm, "TOP SLAB")
    assert a["kind"] == "component_label" and a["attachment"] == "geometry" and a["status"] == "resolved"
    assert "points at it" in " ".join(a["evidence"])
    tgt = sm.dr.items[a["targets"][0]["index"]]
    assert tgt.pts[0][1] == tgt.pts[1][1] and tgt.pts[0][1] in (pytest.approx(5600), pytest.approx(6200)), "a face of the top slab"
    assert "band they bound" in " ".join(a["evidence"]), "the tip is inside the slab: it names the slab between its faces"


def test_a_tip_between_the_faces_of_a_thin_layer_names_the_layer(sm):
    a = ann(sm, "150 THK. PCC")
    assert a["kind"] == "material" and a["status"] == "resolved" and a["attachment"] == "geometry"
    assert "band they bound" in " ".join(a["evidence"])
    assert a["states"]["thickness_mm"] == 150


def test_level_notes_follow_their_lines_titles_stay_and_unclear_notes_stay_put(sm):
    top = ann(sm, "TOP OF SLAB 101.500")
    assert top["kind"] == "level" and top["attachment"] == "datum"
    title = ann(sm, "SECTION A-A")
    assert title["kind"] == "view_title" and title["attachment"] == "view"
    far = ann(sm, "SEE NOTES")
    assert far["attachment"] in ("view", "sheet", "fixed") and far["status"] in ("unassociated", "resolved")
    void = ann(sm, "VOID")
    assert void["status"] in ("ambiguous", "unassociated") and void["attachment"] == "fixed", "half way between two walls: not guessed"


def test_dimensions_are_driving_reference_or_worked_out(sm):
    dims = [a for a in sheet_annotations(sm) if a["kind"].startswith("dimension")]
    kinds = sorted(a["kind"] for a in dims)
    assert kinds.count("dimension_reference") == 1 and kinds.count("dimension_derived") == 1 and kinds.count("dimension_driving") == 3
    total = next(a for a in dims if a["kind"] == "dimension_derived")
    assert total["quantity"]["measured_mm"] == pytest.approx(7200) and len(total["quantity"]["chain"]) == 3


def test_annotations_behave_as_their_attachment_says_when_the_box_grows(sm):
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    height = next(n for n, p in u.prog.params.items() if abs(p.value - 6200) < 1 and p.kind != "level")
    rep = behaviour_report(sm, {f"{uid}.{height}": 6800})
    assert rep["categories"]["validity"]["status"] == "pass"
    rows = rep["categories"]["annotations"]["items"]
    assert not [r for r in rows if r["status"] == "fail"], rows
    sr = sm.preview({f"{uid}.{height}": 6800})
    title = next(i for i in u.items if (sm.dr.items[i].text or "").startswith("SECTION A-A"))
    assert sr.reg.pts.get(title, sm.dr.items[title].pts) == pytest.approx(sm.dr.items[title].pts), "the title stays with its view"


def test_existing_and_proposed_come_from_layer_names_and_accepted_decisions_never_colour_alone(tmp_path, sm):
    st = statuses(sm)
    box = next(it.index for it in sm.dr.items if it.layer == "PROPOSED_BOX")
    ground = next(it.index for it in sm.dr.items if it.layer == "EXISTING_GROUND")
    assert st["entities"][box]["status"] == "proposed" and st["entities"][ground]["status"] == "existing"
    notes = next(it.index for it in sm.dr.items if it.layer == "NOTES" and it.dxftype == "LINE")
    assert st["entities"].get(notes, {}).get("status", "unclassified") == "unclassified"
    # a person decides the NOTES layer's line is existing work: kept, with who and why; undo takes it back
    sm._push()
    sm.semantics["status"].append({"by": "layer", "key": "NOTES", "status": "existing", "who": "person", "why": "the old ground"})
    assert statuses(sm)["entities"][notes]["status"] == "existing"
    assert sm.undo()
    assert statuses(sm)["entities"].get(notes, {}).get("status", "unclassified") == "unclassified"


def test_a_colour_convention_is_learned_from_the_drawing_and_needs_a_second_sign(tmp_path):
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    red = {"color": 1}
    for k in range(3):
        msp.add_text(f"C.L. OF PROP. TRACK {k}", height=150, dxfattribs={**red, "insert": (k * 5000, 9000)})
    msp.add_line((0, 0), (4000, 0), dxfattribs=red)
    msp.add_line((0, 1000), (4000, 1000), dxfattribs={"color": 3})
    p = tmp_path / "colours.dxf"
    doc.saveas(p)
    dr, _ = read_dxf(str(p))
    st = classify_status(dr, None, [{"text": it.text, "items": [it.index], "states": text_states(it.text)} for it in dr.items if it.text])
    assert st["learned_colours"]["#ff0000"]["status"] == "proposed"
    red_line = next(it.index for it in dr.items if it.dxftype == "LINE" and it.extra["style"]["color"] == "#ff0000")
    assert st["entities"][red_line]["status"] == "unclassified", "red alone is not proof: 0.35 < 0.5"
    assert st["entities"][red_line]["candidates"]["proposed"] == pytest.approx(0.35)


def test_layers_are_reported_with_their_properties_and_character(sm):
    rows = {r["name"]: r for r in layers(sm)}
    assert rows["PROPOSED_BOX"]["character"] == "structure" and rows["PROPOSED_BOX"]["name_says"] == "proposed"
    assert rows["PROPOSED_BOX"]["colours_used"] == {"#ff0000": rows["PROPOSED_BOX"]["entities"]}
    assert rows["NOTES"]["character"] == "presentation"
    assert layer_report(sm.dr, sm.layout)


def test_duplicates_are_found_with_what_differs_and_never_merged(tmp_path):
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("EXIST", color=3)
    doc.layers.add("PROP", color=1)
    msp = doc.modelspace()
    msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "PROP"})
    msp.add_line((5000, 0), (0, 0), dxfattribs={"layer": "PROP"})  # the same line drawn back: exact
    msp.add_line((0, 1000), (5000, 1000), dxfattribs={"layer": "PROP"})
    msp.add_line((0, 1000), (5000, 1000), dxfattribs={"layer": "EXIST", "linetype": "DASHED"})  # same geometry, other style
    msp.add_line((0, 2000), (5000, 2000.8), dxfattribs={"layer": "PROP"})
    msp.add_line((0, 2000), (5000, 2000), dxfattribs={"layer": "PROP"})  # nearly the same
    msp.add_line((0, 3000), (3000, 3000), dxfattribs={"layer": "PROP"})
    msp.add_line((2000, 3000), (5000, 3000), dxfattribs={"layer": "EXIST"})  # overlapping on one line
    p = tmp_path / "dups.dxf"
    doc.saveas(p)
    dr, _ = read_dxf(str(p))
    n = len(dr.items)
    rep = find_duplicates(dr)
    rel = {g["relation"] for g in rep["groups"]}
    assert rel == {"exact", "restyled", "near", "overlap"}
    restyled = next(g for g in rep["groups"] if g["relation"] == "restyled")
    assert set(restyled["differs"]) >= {"layer", "colour", "linetype"}
    assert len(dr.items) == n, "nothing merged or removed"


def test_the_semantics_are_reused_until_their_inputs_change(sm):
    sheet_annotations(sm)
    layers(sm)
    duplicates(sm)
    hits = sm.memo.hits
    sheet_annotations(sm)
    layers(sm)
    duplicates(sm)
    assert sm.memo.hits == hits + 3
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    name = next(iter(u.prog.params))
    sm.apply({f"{uid}.{name}": u.prog.params[name].value + 50})
    misses = sm.memo.misses
    sheet_annotations(sm)  # a value change does not change what the notes refer to
    assert sm.memo.misses == misses
    sm._push()
    sm.semantics["status"].append({"by": "layer", "key": "NOTES", "status": "existing", "who": "person", "why": "test"})
    statuses(sm)
    assert sm.memo.misses == misses + 1, "a new decision recomputes the statuses"


def test_association_works_on_any_drawing_without_a_sheet(tmp_path):
    dr, _ = read_dxf(section(tmp_path / "s.dxf"))
    model = associate(dr)
    assert model.summary()["annotations"] >= 8
