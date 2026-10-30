"""What a drawing's own printed words say it is (identify.py, read with the bridge library's vocabulary), and what the graded knowledge holds for it.

Found on real sheets: the title block of one says "PROP. SPAN : 6.78 M, RAILWAY_RUB" over a box under a road with one existing track, and prints an inspection
chamber's "1800MM DIA RCC PIPE" (not a pipe culvert); another replaces an existing slab with a box under a doubling, naming the UP and DN main lines, some labels
broken over two lines; a note's sentence ends "... LINE AS PER APPROVED L SECTION" (not a track). The tests use texts of the same shapes, a generated sheet for a
whole scripted run, and the graded files' provenance. Nothing here asserts a standard value: none is held (the RDSO sheets are not in the library)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam.ai import library as L
from dxf_autoparam.identify import main_kind, read, relations_for

# these tests measure the engine within ONE unit made of a section and its plan (conftest.joined_units): local systems, each view its own,
# are test_local_systems.py
pytestmark = pytest.mark.usefixtures("joined_units")

ROOT = Path(__file__).resolve().parents[1]
VOCAB = L.open_domain("bridge").identify_vocab


def t(text: str, where: str = "notes", height: float = 200.0, unit: str | None = None, i: int = 0) -> dict:
    return {"text": text, "id": f"T{i or abs(hash(text)) % 100000}", "height": height, "view": "", "where": where, "unit": unit}


def kinds(r):
    return {k["id"]: k for k in r["kinds"]}


def test_a_kind_is_read_with_its_status_and_a_look_alike_is_set_aside():
    r = read([t("EXISTING : 1 X 3.66 m PSC SLAB\nPROPOSED : 1 X 4.00 X 2.56 m RCC BOX", "table"), t("C LINE OF PROP. RCC BOX"),
              t("300 DIA. PIPE FOR S&T CABLES"), t("INSPECTION CHAMBER 1800MM DIA RCC PIPE")], VOCAB)
    k = kinds(r)
    assert main_kind(r)["id"] == "rcc_box" and set(k["rcc_box"]["status"]) == {"proposed"}, k
    assert set(k["psc_slab"]["status"]) == {"existing"}, "the status word nearest before the kind on its own line"
    assert "pipe" not in k and {a["text"] for a in r["set_aside"]} == {"300 DIA. PIPE FOR S&T CABLES", "INSPECTION CHAMBER 1800MM DIA RCC PIPE"}, r["set_aside"]
    assert all(a["because"] in a["text"] for a in r["set_aside"]), "each says the word that set it aside"
    assert r["reading"].startswith("proposed RCC box 1 × 4 × 2.56 m; also existing PSC slab 1 × 3.66 m"), r["reading"]


@pytest.mark.parametrize("texts,count,by,conf", [
    (["C.L. OF EXIST. BG TRACK", "℄ OF EXIST. TRACK"], 1, {"existing": 1}, "single"),  # one line labelled twice is one
    (["C/L OF EXISTING\nUP MAIN LINE", "C/L OF PROPOSED\nDN MAIN LINE"], 2, {"existing": 1, "proposed": 1}, "double"),  # labels on two lines
    (["C/L OF UP MAIN LINE", "C/L OF PROP. UP MAIN LINE", "C/L OF EXIST. DN MAIN LINE", "C/L OF DN MAIN LINE"], 2, {"existing": 1, "proposed": 1}, "double"),
    (["℄ OF PROP. TRACK 1", "℄ OF PROP. TRACK 2", "℄ OF PROP. TRACK"], 2, {"proposed": 2}, "double"),  # the bare name stands for one of the two
    (["C/L OF EXISTING UP LINE", "C/L OF EXISTING DN LINE", "C/L OF PROPOSED 3RD LINE"], 3, {"existing": 2, "proposed": 1}, "triple"),
    (["C/L OF EXISTING LINE", "PROPOSED 4TH LINE BETWEEN KM 10 AND KM 14"], 4, {"existing": 1}, "quadruple"),  # the words count more than are drawn
])
def test_the_lines_named_on_the_sheet_are_counted_per_status(texts, count, by, conf):
    c = read([t(x, i=n + 1) for n, x in enumerate(texts)], VOCAB)["carried"]
    assert (c["count"], c["by_status"], c["configuration"]["id"]) == (count, by, conf), c


def test_a_sentence_that_mentions_a_line_names_none():
    c = read([t("C/L OF TRACK SHALL BE AS PER APPROVED L SECTION BEFORE EXECUTION OF WORK"), t("C/L OF BRIDGE"), t("C LINE OF PROP. RCC BOX")], VOCAB)["carried"]
    assert c["count"] == 0 and not c["lines"], c


def test_spans_loading_and_facts_are_read_and_the_specific_loading_wins():
    r = read([t("PROP. SPAN : 6.78 M, RAILWAY_RUB", "title_block", 600.0), t("STANDARD OF LOADING: 25T-2008", "title_block", 500.0),
              t("BR. No.: 173A", "title_block", 600.0), t("CHAINAGE : 115532", "title_block"), t("HAUNCH 300 x 300"),
              t("FOR DETAILS OF RCC BOX REFER DRG NO. RDSO/B-10152/2R OF SIZE 1X5X4.5M BOX WITH 1.00M FILL."), t("SUBWAY ROAD LEVEL 608.051")], VOCAB)
    assert [x["id"] for x in r["loading"]] == ["25t-2008"], "the bare '25 t' is the same statement, said less exactly"
    assert r["crossings"][0]["id"] == "road_under"
    spans = {(s["count"], s["span_m"], s.get("height_m")) for s in r["spans"]}
    assert {(1, 6.78, None), (1, 5.0, 4.5)} <= spans and not any(s["count"] == 300 for s in r["spans"]), "a haunch's 300 × 300 is no span"
    f = {k: [v["value"] for v in x["values"]] for k, x in r["facts"].items()}
    assert f["number"] == ["173A"] and f["chainage"] == ["115532"] and f["standard_drawing"] == ["RDSO/B-10152/2R"], f


def test_the_configuration_relations_read_with_the_count():
    rel = VOCAB["configuration_relations"]
    got = {n: relations_for(rel, n)[0]["for_this_drawing"] for n in (1, 2, 3, 4)}
    assert got[1] == "formation_width = 0 * track_centre + 2 * edge_distance" and got[4] == "formation_width = 3 * track_centre + 2 * edge_distance", got
    assert all("KC-13" in r.get("note", "") or "KC-2" in (r.get("conflict") or "") or r["id"] == "R-EXTENSION-FOR-A-TRACK" for r in rel), \
        "the relations say which open question keeps a standard value out"


def test_the_graded_knowledge_is_the_imported_one_and_holds_no_value_for_a_configuration():
    spec = importlib.util.spec_from_file_location("import_graded_knowledge", ROOT / "tools" / "import_graded_knowledge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.check() == [], "graded files are imported as they are, never edited here"
    lib = L.open_domain("bridge")
    assert lib.graded["provenance"]["commit"] and lib.graded["conflicts"]["KC-13"]["resolution"]["status"] == "OPEN"


def test_the_family_card_says_what_the_library_holds_each_with_its_status():
    lib = L.open_domain("bridge")
    card = lib.family_card("rcc_box", 2)
    assert card["capability"] == "SUPPORTED" and any(c["id"] == "box" for c in card["components"])
    assert all(f["status"] in ("DERIVED", "ASSUMPTION", "DISPUTED", "COMMON_PRACTICE", "UNKNOWN") for f in card["formulas"])
    assert any(r["status"] == "NORMATIVE" and r["cites"] for r in card["rules"]) and any(q["status"] == "OPEN" for q in card["open_questions"])
    assert card["configuration"][0]["for_this_drawing"] == "formation_width = 1 * track_centre + 2 * edge_distance"
    assert "never values" in card["trust"]
    assert lib.family_card("no_such_family") is None
    assert lib.resolves("graded:KC-13") and lib.resolves("graded:F-BOX-SOFFIT") and not lib.resolves("graded:NO-SUCH")


# ── a whole scripted run on a generated sheet ────────────────────────────────────


def labelled_box(tmp_path):
    """The library harness's single-cell box, parametrized, with the words of a doubling printed beside it."""
    from dxf_autoparam.crossview import SheetModel
    from dxf_autoparam.plan_bench import Box, box_answer, box_gad
    from dxf_autoparam.workspace import SheetSession

    g = box_gad(tmp_path / "box.dxf", Box(cells=1, span=2500.0, height=2500.0))
    doc = ezdxf.readfile(g["path"])
    msp = doc.modelspace()
    for k, words in enumerate(["C/L OF EXISTING UP LINE", "C/L OF PROPOSED DN LINE", "PROPOSED : 1 X 2.50 X 2.50 m RCC BOX", "BR. NO. 12"]):
        msp.add_text(words, height=150, dxfattribs={"insert": (-9000, -3000 - 400 * k)})
    doc.saveas(g["path"])
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sm.commit_answer(uid, box_answer(sm, uid, g["box"], g["handles"]))
    sheet = SheetSession()
    sheet.sm = sm
    return sheet, uid


def response(gem, turn: int, k: int = 0):
    r = gem.seen[turn][k].response
    return r.get("result", r) if isinstance(r, dict) else r


def test_a_run_reads_what_the_words_say_and_checks_a_graded_relation_on_its_own_values(tmp_path):
    from test_library_harness import READING, run_script

    from dxf_autoparam.ai.scripted import call

    sheet, uid = labelled_box(tmp_path)
    u = sheet.sm.unit(uid)
    script = [
        [READING],
        [call("identify_structure")],
        [call("open_unit", unit=uid)],
        [call("check_rule", rule="graded:R-FORMATION-WIDTH-N", bind={"formation_width": "ClearSpan", "track_centre": "ClearSpan", "edge_distance": "OuterWall"}),
         call("check_rule", rule="graded:F-NO-SUCH", bind={"x": "ClearSpan"})],
        [call("record_finding", findings=[{"kind": "gap", "text": "no standard formation width is held", "evidence": ["graded:KC-13"]}])],
        [call("finish", summary="read, checked, nothing edited")],
    ]
    gem, p = run_script(sheet, script)
    assert p["status"] == "completed", p["verdict"]
    assert "identify_structure" in gem.requests[0]["tools"]
    got = response(gem, 1)
    assert "2 tracks" in got["reading"] and got["carried"]["configuration"]["id"] == "double", got.get("reading")
    assert got["library"]["family"] == "rcc_box" and got["library"]["configuration"][0]["for_this_drawing"].startswith("formation_width = 1 * track_centre")
    rel, missing = response(gem, 3, 0), response(gem, 3, 1)
    want = u.prog.params["ClearSpan"].value + 2 * u.prog.params["OuterWall"].value
    assert rel["result"] == "differs" and rel["expected_mm"] == pytest.approx(want), rel
    assert "no record" in str(missing), missing
    assert p["verdict"]["knowledge"]["findings"]["by_kind"] == {"gap": 1}, "a graded id is a library id"
