"""What the drawing itself calls a part: the labels whose leader points at its outline — said where the region is inspected and where the part is
defined, and a part the drawing labels as something else is a doubt the run has to resolve.

Found on a real sheet: the agent named two height-gauge frames "ToeWalls" in a long section; the note "HEIGHT GAUGE (AS PER DWG. NO. …)" had its
leader on them and was readable on the tile the model was given. Nothing said so. Generated drawing, scripted model, real engine."""

from __future__ import annotations

import ezdxf
from test_agent import ScriptedGemini, call

from dxf_autoparam.ai import labels as L
from dxf_autoparam.ai.agent import agent_parametrize
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.topology import of


def two_members(path) -> str:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (300, 0), (300, 3000), (0, 3000)], close=True)  # a post
    msp.add_lwpolyline([(2000, 0), (2600, 0), (2600, 1200), (2000, 1200)], close=True)  # a low wall
    msp.add_line((-1000, 0), (4000, 0))  # the ground
    msp.add_leader([(300, 2500), (900, 3400), (1800, 3400)])
    msp.add_text("HEIGHT GAUGE (AS PER DWG. NO. X-0001)", height=120, dxfattribs={"insert": (950, 3450)})
    msp.add_leader([(2300, 1200), (2900, 2000), (3800, 2000)])
    msp.add_text("TOE WALL", height=120, dxfattribs={"insert": (2950, 2050)})
    doc.saveas(str(path))
    return str(path)


def regions(path):
    an, *_ = prepare(path)
    rs = of(an).regions
    post = next(r for r in rs if abs(r.bbox[2] - r.bbox[0] - 300 / an.drawing.units_mm) < 1e-6)
    wall = next(r for r in rs if abs(r.bbox[2] - r.bbox[0] - 600 / an.drawing.units_mm) < 1e-6)
    return post.id, wall.id


def test_the_words_of_a_name_and_of_a_label_are_compared_as_words():
    assert L.words("ToeWalls") == {"toe", "wall"} and L.words("HEIGHT GAUGE (AS PER DWG. NO. RDSO/M-0001)") == {"height", "gauge", "rdso"}
    assert L.words("150mm THK. PCC BASE COURSE") == {"pcc", "base", "course"} and L.words("boulder_backing") == {"boulder", "backing"}
    assert L.conflict({"name": "ToeWalls", "type": "toe_wall"}, [{"id": "T1", "text": "HEIGHT GAUGE"}])
    assert L.conflict({"name": "BoulderBacking", "type": "drainage_layer"}, [{"id": "T2", "text": "600 THK. BOULDER"}]) is None
    assert L.conflict({"name": "ToeWalls", "type": "toe_wall", "label_checked": "the gauge stands on the toe wall"}, [{"id": "T1", "text": "HEIGHT GAUGE"}]) is None


def test_a_part_the_drawing_labels_otherwise_is_said_where_it_is_defined_and_in_the_finish(tmp_path):
    path = two_members(tmp_path / "two.dxf")
    post, wall = regions(path)
    script = [
        [call("inspect_regions", ids=[post, wall])],
        [call("define_parts", items=[{"name": "ToeWall", "type": "toe_wall", "regions": [post]}, {"name": "HeightGauge", "type": "post", "regions": [wall]}])],
        [call("finish", summary="done")],
        [call("define_parts", items=[{"name": "HeightGauge", "type": "post", "regions": [post]}, {"name": "ToeWall", "type": "toe_wall", "regions": [wall]}])],
        [call("finish", summary="done")],
    ]
    gem = ScriptedGemini(script)
    agent_parametrize(path, gem=gem, log=lambda *a: None)
    seen_regions = gem.seen[0][0]
    assert any("HEIGHT GAUGE" in x for x in seen_regions[post]["labelled"]) and any("TOE WALL" in x for x in seen_regions[wall]["labelled"])
    first = {v["item"]: v for v in gem.seen[1][0]["result"]}
    assert "HEIGHT GAUGE" in first["ToeWall"]["label_doubt"] and "TOE WALL" in first["HeightGauge"]["label_doubt"]
    refused = gem.seen[2][0]
    assert refused["done"] is False and any("HEIGHT GAUGE" in d for d in refused["label_doubts"]), "the first finish says which parts the drawing labels otherwise"
    again = {v["item"]: v for v in gem.seen[3][0]["result"]}
    assert not any("label_doubt" in v for v in again.values()), "named as the drawing labels them: no doubt"
    assert any("HEIGHT GAUGE" in x for x in again["HeightGauge"]["drawing_says"])


def test_a_part_kept_against_its_label_says_why(tmp_path):
    path = two_members(tmp_path / "two.dxf")
    post, _wall = regions(path)
    script = [[call("define_parts", items=[{"name": "ToeWall", "type": "toe_wall", "regions": [post], "label_checked": "test: kept on purpose"}])],
              [call("finish", summary="done")]]
    gem = ScriptedGemini(script)
    agent_parametrize(path, gem=gem, log=lambda *a: None)
    v = gem.seen[0][0]["result"][0]
    assert v["ok"] and "label_doubt" not in v and "drawing_says" in v
