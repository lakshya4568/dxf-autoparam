"""Token Harbor as a second OpenAI-compatible gateway: its catalogue (which models, which are free), the picker, and the transport's handling of what
a model refuses — all on mock transports, never the network and never the person's real key (`conftest.py` empties it for every test)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest
from google.genai import types

from dxf_autoparam.ai import gateway, tokenharbor, vertex
from dxf_autoparam.ai.usage import summary

KEY = "thk_test_key"  # a stand-in: the real key lives only in the person's .env
FREE = {"input_usd_per_1m": 0, "output_usd_per_1m": 0, "cache_read_usd_per_1m": 0, "cache_write_usd_per_1m": 0}
CATALOG = [
    {"id": "deepseek-v4-flash:free", "label": "DeepSeek V4 Flash", "tier": "free", "pricing": FREE, "context_length": 128000, "tool_call": True},
    {"id": "mimo-v2.5:free", "label": "MiMo V2.5", "tier": "free", "pricing": FREE, "context_length": None, "tool_call": True},
    {"id": "big-model", "label": "Big", "tier": "premium", "pricing": {"input_usd_per_1m": 3.0, "output_usd_per_1m": 15.0, "cache_read_usd_per_1m": 0.3}},
    {"id": "no-price", "label": "Unpriced"},
]
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def serve(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def harbor(monkeypatch, tmp_path):
    """The key set, the .env out of the way, the ledger and cache in tmp, no waiting between retries (the waits are recorded)."""
    monkeypatch.setenv("TOKENHARBOR_API_KEY", KEY)
    for mod in (vertex, tokenharbor, gateway):
        monkeypatch.setattr(mod, "load_env_file", lambda *a, **k: None)
    monkeypatch.setattr(vertex, "CACHE", tmp_path)
    monkeypatch.setattr(gateway, "CACHE", tmp_path)
    sleeps: list[float] = []
    monkeypatch.setattr(gateway.time, "sleep", sleeps.append)
    return sleeps


def listed(monkeypatch, models=CATALOG) -> None:
    monkeypatch.setattr(tokenharbor, "catalog", lambda client=None, fresh=False: models)


# ── the catalogue ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_catalogue_is_asked_with_the_key_and_free_means_priced_at_zero(harbor):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        return httpx.Response(200, json={"object": "list", "data": CATALOG})

    got = tokenharbor.fetch(serve(handler))
    assert seen == {"url": "https://tokenharbor.ai/v1/models", "auth": f"Bearer {KEY}"} and [m["id"] for m in got] == [m["id"] for m in CATALOG]
    assert [m["id"] for m in tokenharbor.wanted(CATALOG)] == ["deepseek-v4-flash:free", "mimo-v2.5:free"], "free is the default, and an unpriced model is not free"
    assert [m["id"] for m in tokenharbor.wanted(CATALOG, "all")] == [m["id"] for m in CATALOG]
    assert [m["id"] for m in tokenharbor.wanted(CATALOG, "big-model, nope")] == ["big-model"]
    shuffled = [CATALOG[3], CATALOG[2], CATALOG[1], CATALOG[0]]
    assert [m["id"] for m in tokenharbor.wanted(shuffled, "all")] == [m["id"] for m in CATALOG], "free first, then by price, an unpriced model last"


def test_a_catalogue_that_cannot_be_had_is_said_and_then_left_alone_for_a_minute(harbor):
    asked = []

    def down(req: httpx.Request) -> httpx.Response:
        asked.append(1)
        return httpx.Response(503, text="maintenance")

    assert tokenharbor.catalog(serve(down)) == [] and "HTTP 503" in tokenharbor.last_error()
    tokenharbor.catalog(serve(down))
    assert len(asked) == 1, "a gateway that is down is not asked again at every page load"
    tokenharbor.catalog(serve(down), fresh=True)
    assert len(asked) == 2
    assert KEY not in tokenharbor.last_error()


def test_the_last_good_catalogue_serves_while_the_gateway_is_down_in_memory_and_then_from_disk(harbor):
    up = serve(lambda req: httpx.Response(200, json={"data": CATALOG}))
    down = serve(lambda req: httpx.Response(500))
    assert len(tokenharbor.catalog(up)) == 4 and tokenharbor.FILE.exists()
    tokenharbor._memo["at"] = 0.0  # a quarter of an hour on
    assert len(tokenharbor.catalog(down)) == 4, "from memory"
    tokenharbor.forget()  # the page's server restarted
    assert len(tokenharbor.catalog(down)) == 4, "from disk"


def test_no_key_means_no_models_and_no_call(harbor, monkeypatch):
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "")
    asked = []
    assert tokenharbor.picker_entries(serve(lambda req: asked.append(1) or httpx.Response(200, json={"data": CATALOG}))) == [] and not asked
    with pytest.raises(RuntimeError, match="TOKENHARBOR_API_KEY"):
        tokenharbor.fetch()


def test_a_model_is_an_entry_of_the_pickers_table_with_its_price_and_no_fallback():
    free, big = (tokenharbor.entry(m) for m in CATALOG[:1] + CATALOG[2:3])
    assert free["id"] == "tokenharbor:deepseek-v4-flash:free" and free["gateway_model"] == "deepseek-v4-flash:free" and free["free"] is True
    assert free["label"] == "DeepSeek V4 Flash · free (Token Harbor)" and free["fallback"] == "" and free["provider"] == "tokenharbor"
    assert tokenharbor.entry({**CATALOG[0], "label": "DeepSeek V4 Flash (Free)"})["label"] == free["label"], "the catalogue's own '(Free)' is said once"
    assert big["free"] is False and big["price"] == {"input": 3.0, "output": 15.0, "cached": 0.3} and "$3 / $15 per M" in big["label"]


# ── the picker and the run's model ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_picker_lists_the_free_models_when_the_key_is_set_and_never_the_key(harbor, monkeypatch):
    listed(monkeypatch)
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "")
    assert not [m for m in vertex.model_choices()["models"] if m["id"].startswith("tokenharbor:")]
    monkeypatch.setenv("TOKENHARBOR_API_KEY", KEY)
    got = vertex.model_choices()
    mine = [m for m in got["models"] if m["id"].startswith("tokenharbor:")]
    assert [m["id"] for m in mine] == ["tokenharbor:deepseek-v4-flash:free", "tokenharbor:mimo-v2.5:free"] and all(m["free"] and m["thinking"] == "high" for m in mine)
    assert got["default"] == "gemini-3.8-flash" and got["models"][0]["id"] == "gemini-3.8-flash", "Vertex stays the default"
    assert KEY not in json.dumps(got)
    monkeypatch.setenv("TOKENHARBOR_MODELS", "all")
    assert len([m for m in vertex.model_choices()["models"] if m["id"].startswith("tokenharbor:")]) == 4


def test_choice_for_finds_a_model_by_its_picker_id_even_one_the_catalogue_dropped(monkeypatch):
    listed(monkeypatch)
    free = vertex.choice_for("tokenharbor:deepseek-v4-flash:free")
    assert (free["provider"], free["gateway_model"], free["free"], free["price"]["input"]) == ("tokenharbor", "deepseek-v4-flash:free", True, 0)
    gone = vertex.choice_for("tokenharbor:not-listed")
    assert gone["gateway_model"] == "not-listed" and gone["free"] is False, "reachable while the gateway serves it, and never assumed free"
    assert vertex.choice_for("gemini-4-argon")["price"]["input"] == 2.0 and vertex.choice_for("nope") is None


def test_a_run_on_a_token_harbor_model_gets_a_gateway_with_that_provider_and_price(harbor, monkeypatch):
    from dxf_autoparam.workspace import SheetSession

    listed(monkeypatch)
    gem = SheetSession().get_gem("tokenharbor:big-model")
    try:
        assert isinstance(gem, gateway.Gateway) and gem.provider.name == "tokenharbor" and gem.base == "https://tokenharbor.ai/v1" and gem._key == KEY
        assert gem.cfg.model == "big-model" and gem.cfg.price == {"input": 3.0, "output": 15.0, "cached": 0.3}
    finally:
        gem.close()


# ── the transport ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def answer(usage: dict | None = None, **message) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "ok", **message}, "finish_reason": "stop"}],
                                     "usage": usage or {"prompt_tokens": 10, "completion_tokens": 2}})


def turn(text: str, picture: bool = False) -> list:
    parts = [types.Part.from_text(text=text)] + ([types.Part.from_bytes(data=PNG, mime_type="image/png")] if picture else [])
    return [types.Content(role="user", parts=parts)]


def has_picture(body: dict) -> bool:
    return any(isinstance(m.get("content"), list) and any(x.get("type") == "image_url" for x in m["content"]) for m in body["messages"])


def harbor_gateway(handler, price: dict | None = None, model: str = "deepseek-v4-flash:free") -> gateway.Gateway:
    return gateway.Gateway(gateway.GatewayConfig(model=model, provider="tokenharbor", price=price), client=serve(handler))


def test_a_call_goes_to_token_harbor_with_its_key_and_the_ledger_names_the_provider(harbor, tmp_path):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        return answer()

    free = {"input": 0, "output": 0, "cached": 0}
    _c, usage = harbor_gateway(handler, free).step("S", [], [], "k", turn("a"), "t", "high")
    assert seen == {"url": "https://tokenharbor.ai/v1/chat/completions", "auth": f"Bearer {KEY}"}
    assert (usage["model"], usage["provider"], usage["cost_usd"]) == ("tokenharbor:deepseek-v4-flash:free", "tokenharbor", 0.0)
    ledger = summary("all", tmp_path / "usage.jsonl")
    assert ledger["models"][0]["cost"] == 0.0 and ledger["unpriced"] == [], "a free model is priced at zero, not 'no price'"


def test_the_cost_is_the_gateways_when_it_reports_one_else_the_listed_price_else_none(harbor):
    listed_price = {"input": 3.0, "output": 15.0, "cached": 0.3}
    used = {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 400}}
    assert harbor_gateway(lambda r: answer(used), listed_price).step("S", [], [], "k", turn("a"), "t", "high")[1]["cost_usd"] == pytest.approx((600 * 3 + 400 * 0.3 + 200 * 15) / 1e6)
    assert harbor_gateway(lambda r: answer({**used, "cost": 0.5}), listed_price).step("S", [], [], "k", turn("b"), "t", "high")[1]["cost_usd"] == 0.5
    assert harbor_gateway(lambda r: answer(used), None).step("S", [], [], "k", turn("c"), "t", "high")[1]["cost_usd"] is None, "no price: nothing is guessed"
    assert harbor_gateway(lambda r: answer(used), {"input": None, "output": None, "cached": None}).step("S", [], [], "k", turn("d"), "t", "high")[1]["cost_usd"] is None


def test_a_model_that_does_not_read_pictures_goes_on_without_them_and_is_not_asked_twice(harbor):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        b = json.loads(req.content)
        bodies.append(b)
        return httpx.Response(400, json={"error": {"message": "this model does not accept image input"}}) if has_picture(b) else answer()

    gw, notes = harbor_gateway(handler), []
    _c, usage = gw.step("S", [], [], "k", turn("first", picture=True), "t1", "high", on_event=notes.append)
    assert len(bodies) == 2 and has_picture(bodies[0]) and not has_picture(bodies[1]), "refused once, then the same turn without the picture"
    assert "this model does not read pictures" in json.dumps(bodies[1]["messages"]) and usage["dropped"] == ["1 picture(s)"] and gw.text_only
    assert [n["kind"] for n in notes] == ["note"] and "does not read pictures" in notes[0]["text"]
    _c, usage = gw.step("S", [], [], "k", turn("second", picture=True), "t2", "high", on_event=notes.append)
    assert len(bodies) == 3 and not has_picture(bodies[2]) and "dropped" not in usage and len(notes) == 1, "remembered: one request, and nothing more said"


def test_a_model_that_will_not_take_a_required_tool_call_is_asked_to_choose(harbor):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        b = json.loads(req.content)
        bodies.append(b)
        return httpx.Response(400, json={"error": "tool_choice 'required' is not supported by this model"}) if b.get("tool_choice") == "required" else answer()

    tools = [types.Tool(function_declarations=[types.FunctionDeclaration(name="finish", description="end", parameters_json_schema={"type": "object", "properties": {}})])]
    gw, notes = harbor_gateway(handler), []
    _c, usage = gw.step("S", tools, [], "k", turn("a"), "t", "high", on_event=notes.append)
    assert [b["tool_choice"] for b in bodies] == ["required", "auto"] and usage["dropped"] == ["tool_choice"] and gw.free_choice
    assert {"reasoning_effort", "temperature", "max_tokens", "tools"} <= set(bodies[1]), "only the refused thing is given up"
    gw.step("S", tools, [], "k", turn("b"), "t", "high", on_event=notes.append)
    assert [b["tool_choice"] for b in bodies] == ["required", "auto", "auto"] and len(notes) == 1


def test_optional_fields_a_model_refused_are_not_sent_again(harbor):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        b = json.loads(req.content)
        bodies.append(b)
        return httpx.Response(400, json={"error": "unsupported field"}) if "reasoning_effort" in b else answer()

    gw = harbor_gateway(handler)
    _c, usage = gw.step("S", [], [], "k", turn("a"), "t", "high")
    assert usage["dropped"] == ["reasoning_effort", "temperature", "max_tokens"] and len(bodies) == 2
    gw.step("S", [], [], "k", turn("b"), "t", "high")
    assert len(bodies) == 3 and set(bodies[2]) == {"model", "messages"}


def test_a_rate_limit_waits_as_long_as_it_asks_and_a_gateway_that_stays_down_is_named(harbor):
    calls = []

    def limited(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "7"}, text="slow down") if len(calls) == 1 else answer()

    notes: list[dict] = []
    harbor_gateway(limited).step("S", [], [], "k", turn("a"), "t", "high", on_event=notes.append)
    assert sum(harbor) == 7 and calls == [1, 1], "the wait it asked for, not the default"
    assert len(notes) == 1 and "slowing requests down (HTTP 429): waiting 7 s" in notes[0]["text"]
    harbor.clear()
    with pytest.raises(vertex.GeminiUnavailable, match=r"Token Harbor did not answer \(m\): HTTP 500") as err:
        harbor_gateway(lambda r: httpx.Response(500, text="boom"), model="m").step("S", [], [], "k", turn("b"), "t", "high")
    assert sum(harbor) == 2 + 6 and KEY not in str(err.value), "three tries, the backoff between them, and no key in the message"


def test_an_answer_that_is_not_json_is_tried_again_and_then_named_not_a_crash(harbor):
    # a free model's run ended "failed" on its second turn: Token Harbor, under heavy load, answered 200 with a body that was not JSON, and the
    # JSONDecodeError went straight through the loop
    calls = []

    def cut_short(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text='{"choices": ') if len(calls) == 1 else answer()

    harbor_gateway(cut_short).step("S", [], [], "k", turn("a"), "t", "high")
    assert calls == [1, 1] and sum(harbor) == 2, "tried again after the first backoff"
    harbor.clear()
    with pytest.raises(vertex.GeminiUnavailable, match=r"Token Harbor did not answer \(m\): HTTP 200 with a body that is not JSON") as err:
        harbor_gateway(lambda r: httpx.Response(200, text="<html>busy</html>"), model="m").step("S", [], [], "k", turn("b"), "t", "high")
    assert sum(harbor) == 2 + 6 and KEY not in str(err.value), "three tries, then the provider is named as not answering"


def test_a_rate_limit_that_lasts_is_waited_out_with_a_note_each_time_and_then_named(harbor):
    asked = []
    busy = lambda req: asked.append(1) or httpx.Response(429, json={"error": {"code": "server_busy", "message": "under heavy load"}})
    notes: list[dict] = []
    with pytest.raises(vertex.GeminiUnavailable, match=r"HTTP 429.*server_busy") as err:
        harbor_gateway(busy).step("S", [], [], "k", turn("a"), "t", "high", on_event=notes.append)
    assert len(asked) == gateway.RATE_TRIES and sum(harbor) == sum(gateway.RATE_WAIT_S), "six tries, 10 s growing to 60 s between them"
    assert len(notes) == gateway.RATE_TRIES - 1 and "(5 of 5)" in notes[-1]["text"] and KEY not in str(err.value)


def test_stop_is_heard_while_a_rate_limit_is_waited_out(harbor):
    asked, heard = [], []

    def stop() -> bool:
        heard.append(1)
        return len(asked) >= 1 and len(heard) > 4  # pressed a few seconds into the first wait

    with pytest.raises(vertex.GeminiStopped):
        harbor_gateway(lambda req: asked.append(1) or httpx.Response(429, text="slow")).step("S", [], [], "k", turn("a"), "t", "high", stop=stop)
    assert len(asked) == 1 and sum(harbor) < gateway.RATE_WAIT_S[0], "it stopped inside the first wait, not after it"


def test_a_missing_key_names_the_variable_to_set(harbor, monkeypatch):
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "")
    with pytest.raises(vertex.GeminiUnavailable, match="TOKENHARBOR_API_KEY is not set"):
        harbor_gateway(lambda r: answer()).step("S", [], [], "k", turn("a"), "t", "high")


def test_the_other_gateway_is_unchanged_by_the_provider_table(harbor, monkeypatch):
    monkeypatch.setenv("EXPLABS_API_KEY", "xpl_test")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        return answer()

    gw = gateway.Gateway(gateway.GatewayConfig(model="gemini-4-argon"), client=serve(handler))
    usage = gw.step("S", [], [], "k", turn("a"), "t", "high")[1]
    assert seen == {"url": "https://api.experientiallabs.ai/v1/chat/completions", "auth": "Bearer xpl_test"} and usage["model"] == "gateway:gemini-4-argon"


# ── no secret in the repository ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_token_harbor_key_is_in_a_file_that_git_would_track():
    root = Path(__file__).resolve().parent.parent
    try:
        files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    key = re.compile(rb"thk_(live|test)_[A-Za-z0-9_-]{20,}")
    leaked = [f for f in files if f and (root / f).is_file() and (root / f).stat().st_size < 5_000_000 and key.search((root / f).read_bytes())]
    assert leaked == [], f"a Token Harbor key is in {leaked}: keys live in .env only"
