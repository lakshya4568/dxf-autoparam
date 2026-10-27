"""The architecture is generic: nothing the model reads asks for a particular name, a family or a kind of structure — unless a person switched a
domain pack on for the run. The model names parts, values and levels the way a designer of THIS drawing would, from what it sees; the engine
checks them (every name is data it keeps as written)."""

from __future__ import annotations

import json
import re

import pytest
from test_agent import XX

from dxf_autoparam.ai import domain
from dxf_autoparam.ai.agent import AGENT_SYSTEM, TOOL_SPECS, Workbench, agent_system, overview, tools
from dxf_autoparam.ai.parametrize import prepare
from dxf_autoparam.ai.prompt import SYSTEM, knowledge_text
from dxf_autoparam.ai.run import SHEET_TOOL_SPECS, UNIFIED_SYSTEM, unified_system, unified_tools
from dxf_autoparam.ai.schema import AIAnswer

# names of one kind of structure (and what such a kind is called): none of them is a word the model is handed by default
DOMAIN_NAMES = ["ClearSpan", "ClearHeight", "TopSlab", "BottomSlab", "OuterWall", "MidWall", "WingLength", "WingWall", "Haunch", "WearingCourse",
                "FootingProjection", "RailLevel", "FormationLevel", "BedLevel", "rcc_box", "PipeDiameter", "EffectiveSpan"]
DOMAIN_WORDS = ["bridge", "culvert"]


def spec_text(specs) -> str:
    return json.dumps([(n, d, p) for n, d, p in specs], default=str)


def model_visible_texts() -> dict[str, str]:
    an, base, *_ = prepare(XX)
    return {"one-shot system prompt": SYSTEM, "agent system prompt": AGENT_SYSTEM, "session system prompt": UNIFIED_SYSTEM, "knowledge block": knowledge_text(),
            "unit tool specs": spec_text(TOOL_SPECS), "sheet tool specs": spec_text(SHEET_TOOL_SPECS), "answer schema": json.dumps(AIAnswer.model_json_schema()),
            "overview": json.dumps(overview(an, base), default=str), "session prompt, pack off": unified_system(None)}


def test_nothing_the_model_reads_by_default_names_a_kind_of_structure_or_a_value(monkeypatch):
    monkeypatch.delenv("AUTOPARAM_DOMAIN", raising=False)
    for where, text in model_visible_texts().items():
        for name in DOMAIN_NAMES:
            assert name not in text, f"{name} is offered to the model in the {where}"
        for word in DOMAIN_WORDS:
            assert not re.search(rf"\b{word}", text, re.IGNORECASE), f"{word!r} is said to the model in the {where}"


def test_the_knowledge_tool_exists_only_with_a_pack_and_answers_what_is_on():
    pack = domain.active("bridge")
    names = lambda t: {d.name for tool in t for d in tool.function_declarations}
    assert "knowledge" not in names(tools()) and "knowledge" not in names(unified_tools())
    assert "knowledge" in names(tools(pack=pack)) and "knowledge" not in names(unified_tools(pack)), "a session declares it once the agent opens its group"
    assert "knowledge" in names(unified_tools(pack, {"knowledge"})) and "knowledge" not in names(unified_tools(None, {"knowledge"}))
    assert "no domain pack" in Workbench(XX).knowledge("span")[0]
    assert any("ClearSpan" in h for h in Workbench(XX, pack=pack).knowledge("clear span"))


def test_a_pack_a_person_switches_on_is_offered_not_required():
    pack = domain.active("bridge")
    an, base, *_ = prepare(XX)
    ov = overview(an, base, None, pack)
    assert any(k.startswith("concept names") for k in ov) and "ClearSpan" in json.dumps(ov, default=str)
    guide = unified_system(pack)
    assert "DOMAIN PACK (on for this run: bridge)" in guide and "ClearSpan" in guide and "offered, not required" in guide
    assert agent_system(pack).startswith(AGENT_SYSTEM) and "ClearSpan" not in AGENT_SYSTEM
    assert not any(k.startswith("concept names") for k in overview(an, base))


def test_a_pack_comes_from_a_run_option_or_the_process_and_an_unknown_one_is_no_pack(monkeypatch):
    monkeypatch.delenv("AUTOPARAM_DOMAIN", raising=False)
    assert domain.active() is None and domain.active("nonsense") is None and domain.active("drafting") is None  # drafting conventions are not a domain
    assert domain.available() == ["bridge"] and domain.active("bridge")["name"] == "bridge"
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "Bridge")
    assert domain.active()["name"] == "bridge"


@pytest.mark.parametrize("name", ["WidthA", "Ç", "MainOpening"])
def test_a_name_nobody_listed_is_a_name_like_any_other(tmp_path, name):
    """The engine keeps the model's names as written (PascalCase); nothing checks them against a list."""
    from test_crossview import two_views, view

    from dxf_autoparam.crossview import EMPTY_ANSWER, SheetError, SheetModel

    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    uid = sm.unit_of_view[view(sm, "SECTION A-A")]
    if name == "Ç":
        with pytest.raises(SheetError):
            sm.share(name, [(uid, "c3")])
        return
    p = sm.share(name, [(uid, "c3")])
    assert p.name == name and sm.current()[name] == 3000
    assert EMPTY_ANSWER["family"] == "other"  # no structure family unless the model says one
