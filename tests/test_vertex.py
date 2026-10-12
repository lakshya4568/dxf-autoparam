"""The Vertex client's caching and fallback, against a fake Vertex — no network, no cost."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from dxf_autoparam.ai import vertex
from dxf_autoparam.ai.vertex import Gemini, GeminiStopped, GeminiUnavailable, VertexConfig


class Answer(BaseModel):
    ok: bool


class FakeVertex:
    """Records what is sent; answers {"ok": true}."""

    def __init__(self, refuse_cache: bool = False, fail: list[int] | None = None, truncate: int = 0):
        self.created, self.deleted, self.calls = [], [], []
        self.truncate = truncate  # this many replies are cut off at the output budget first
        self.refuse_cache = refuse_cache
        self.fail = list(fail or [])  # error codes to raise on the next calls, in order
        self.caches = SimpleNamespace(create=self._create, delete=self._delete)
        self.models = SimpleNamespace(generate_content_stream=self._stream)

    def _create(self, model, config):
        if self.refuse_cache:
            raise genai_errors.ClientError(400, {"error": {"code": 400, "message": "explicit caching is not supported", "status": "INVALID_ARGUMENT"}})
        name = f"cachedContents/{len(self.created)}"
        self.created.append({"model": model, "name": name, "parts": len(config.contents[0].parts), "system": config.system_instruction})
        return SimpleNamespace(name=name)

    def _delete(self, name):
        self.deleted.append(name)

    def _stream(self, model, contents, config):
        level = config.thinking_config.thinking_level if config.thinking_config else None
        self.calls.append({"model": model, "contents": len(contents), "cached": config.cached_content, "system": config.system_instruction,
                           "thinking": str(getattr(level, "value", level)).lower(), "max_out": config.max_output_tokens,
                           "include_thoughts": bool(config.thinking_config and config.thinking_config.include_thoughts)})
        if self.fail:
            code = self.fail.pop(0)
            raise (genai_errors.ServerError if code >= 500 else genai_errors.ClientError)(code, {"error": {"code": code, "message": "cached content not found" if code == 404 else "Deadline expired", "status": "X"}})
        um = SimpleNamespace(prompt_token_count=100, candidates_token_count=5, thoughts_token_count=7,
                             cached_content_token_count=90 if config.cached_content else 0)

        def chunk(parts, finish=None, usage=None):
            cand = SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason=SimpleNamespace(name=finish) if finish else None)
            return SimpleNamespace(candidates=[cand], usage_metadata=usage)

        self.closed_streams = getattr(self, "closed_streams", 0)
        try:
            yield from self._parts(chunk, um)
        finally:
            self.closed_streams += 1

    def _parts(self, chunk, um):
        yield chunk([SimpleNamespace(text="**Reading the regions** R1 is the box.", thought=True)])
        if self.truncate:
            self.truncate -= 1
            yield chunk([SimpleNamespace(text='{"ok": tr', thought=False)], "MAX_TOKENS", um)
            return
        yield chunk([SimpleNamespace(text='{"ok": ', thought=False)])
        yield chunk([SimpleNamespace(text="true}", thought=False)], "STOP", um)


@pytest.fixture
def gem(tmp_path, monkeypatch):
    monkeypatch.setattr(vertex, "CACHE", tmp_path / "ai")
    monkeypatch.setattr(vertex.time, "sleep", lambda s: None)

    def make(**kw):
        fake = FakeVertex(**kw)
        cfg = VertexConfig(project="p", location="global", model="m-primary", thinking="high", fallback_model="m-fallback")
        return Gemini(cfg, client=fake), fake

    return make


BIG = "x" * 40000  # a prefix long enough to cache (~10k tokens)


def test_the_shared_prefix_is_cached_once_and_each_round_sends_only_its_own_text(gem):
    g, fake = gem()
    a1, u1 = g.ask("system", [BIG, BIG, "round 1"], [b"png1", b"png2"], Answer, shared=2)
    a2, u2 = g.ask("system", [BIG, BIG, "repair: these were rejected"], [b"png1", b"png2"], Answer, shared=2)
    assert a1 == a2 == {"ok": True}
    assert len(fake.created) == 1 and fake.created[0]["parts"] == 4 and fake.created[0]["system"] == "system"  # 2 images + 2 texts
    assert [c["contents"] for c in fake.calls] == [1, 1]  # only the last text is sent each time
    assert all(c["cached"] == "cachedContents/0" and c["system"] is None for c in fake.calls)  # system lives in the cache
    assert (u1["prompt_cache"], u2["prompt_cache"]) == ("created", "reused") and u2["vertex_cached_tokens"] == 90
    assert all(c["thinking"] == "high" and c["max_out"] == 65536 for c in fake.calls)
    assert g.close() == [] and fake.deleted == ["cachedContents/0"]


def test_answers_on_disk_are_free_and_keyed_by_the_thinking_level(gem):
    g, fake = gem()
    g.ask("system", [BIG, BIG, "q"], [b"png"], Answer, shared=2)
    _, again = g.ask("system", [BIG, BIG, "q"], [b"png"], Answer, shared=2)
    assert again["cached"] is True and len(fake.calls) == 1
    g.cfg.thinking = "medium"
    _, other = g.ask("system", [BIG, BIG, "q"], [b"png"], Answer, shared=2)
    assert other["cached"] is False and len(fake.calls) == 2


def test_a_refused_or_short_prefix_is_sent_whole(gem):
    g, fake = gem(refuse_cache=True)
    _, u = g.ask("system", [BIG, BIG, "q"], [b"png"], Answer, shared=2)
    assert u["prompt_cache"].startswith("unavailable") and fake.calls[0]["contents"] == 4 and fake.calls[0]["system"] == "system"
    g2, fake2 = gem()
    _, u2 = g2.ask("system", ["short", "short", "q"], [], Answer, shared=2)
    assert u2["prompt_cache"].startswith("prefix too short") and not fake2.created


def test_an_expired_cache_is_recreated_and_a_504_moves_to_the_fallback(gem):
    g, fake = gem(fail=[404])  # the cache expired between rounds
    _, u = g.ask("system", [BIG, BIG, "q"], [b"png"], Answer, shared=2)
    assert len(fake.created) == 2 and u["model"] == "m-primary" and u["prompt_cache"] == "created"
    g2, fake2 = gem(fail=[504, 504])  # the primary twice past its deadline
    _, u2 = g2.ask("system", [BIG, BIG, "q2"], [b"png"], Answer, shared=2)  # (each case its own question: answers are on disk)
    assert u2["model"] == "m-fallback" and u2["fallback"] is True
    assert {c["model"] for c in fake2.created} == {"m-primary", "m-fallback"}  # a cache belongs to one model
    g3, _ = gem(fail=[504, 504, 504, 504])
    with pytest.raises(GeminiUnavailable):
        g3.ask("system", [BIG, BIG, "q3"], [b"png"], Answer, shared=2)
    g4, _ = gem(fail=[400])  # a request Vertex rejects is a real error, not something to retry
    with pytest.raises(genai_errors.ClientError):
        g4.ask("system", [BIG, BIG, "q4"], [b"png"], Answer, shared=2)


def test_a_reply_cut_off_at_the_output_budget_is_logged_and_retried_with_less_thinking(gem):
    g, fake = gem(truncate=1)
    answer, u = g.ask("system", [BIG, BIG, "q5"], [b"png"], Answer, shared=2)
    assert answer == {"ok": True}
    assert [c["thinking"] for c in fake.calls] == ["high", "medium"]
    assert u["thinking"] == "medium" and u["wasted"]["thinking_tokens"] == 7  # the cut-off attempt was billed: it counts
    lines = [json.loads(x) for x in (vertex.CACHE / "usage.jsonl").read_text().splitlines()]
    assert "MAX_TOKENS" in lines[0]["error"] and lines[1]["finish"] == "STOP"
    g2, _ = gem(truncate=4)  # never a complete answer: a clear failure, not a JSON traceback
    with pytest.raises(GeminiUnavailable, match="no complete JSON"):
        g2.ask("system", [BIG, BIG, "q6"], [b"png"], Answer, shared=2)


def test_thought_summaries_stream_to_the_caller_and_are_kept_with_the_answer(gem):
    g, fake = gem()
    events = []
    answer, u = g.ask("system", [BIG, BIG, "q7"], [b"png"], Answer, shared=2, on_event=events.append)
    assert answer == {"ok": True} and fake.calls[0]["include_thoughts"]
    assert [e["kind"] for e in events] == ["call", "thought"] and "R1 is the box" in events[1]["text"]
    assert u["thoughts"] == ["**Reading the regions** R1 is the box."]
    replay = []
    _, u2 = g.ask("system", [BIG, BIG, "q7"], [b"png"], Answer, shared=2, on_event=replay.append)  # from disk: free
    assert u2["cached"] and [e["kind"] for e in replay] == ["call", "thought"]
    assert "thoughts" not in (vertex.CACHE / "usage.jsonl").read_text()  # the token log stays a token log


def test_stop_ends_the_call_at_the_next_streamed_message_and_closes_the_stream(gem):
    g, fake = gem()
    seen = []

    def on_event(e):
        seen.append(e["kind"])

    with pytest.raises(GeminiStopped):
        g.ask("system", [BIG, BIG, "q8"], [b"png"], Answer, shared=2, on_event=on_event, stop=lambda: "thought" in seen)
    assert fake.closed_streams == 1 and len(fake.calls) == 1  # one call, cut after its first thought, no retry
    lines = [json.loads(x) for x in (vertex.CACHE / "usage.jsonl").read_text().splitlines()]
    assert lines[-1]["stopped"] is True
    with pytest.raises(GeminiStopped):  # stopped before it even starts: no call at all
        g.ask("system", [BIG, BIG, "q9"], [b"png"], Answer, shared=2, stop=lambda: True)
    assert len(fake.calls) == 1


def test_a_stalled_call_is_cut_and_retried_not_waited_on_for_ten_minutes():
    """A shared pool that stops answering: the watchdog ends the attempt at its deadline (a retryable error), the
    person's Stop ends it at once, and a network read timeout counts as retryable (it used to end the whole run)."""
    import threading
    import time

    import httpx

    from dxf_autoparam.ai import vertex as V

    t = time.monotonic()
    with pytest.raises(V.Stalled) as exc:
        V._pumped(lambda put: time.sleep(5), lambda x: None, 0.5, None, "hang")
    assert time.monotonic() - t < 2 and V._transient(exc.value)
    flag = threading.Event()
    threading.Timer(0.3, flag.set).start()
    with pytest.raises(V.GeminiStopped):
        V._pumped(lambda put: time.sleep(5), lambda x: None, 60, flag.is_set, "stop")
    got: list = []
    V._pumped(lambda put: [put(i) for i in range(3)], got.append, 5, None, "ok")
    assert got == [0, 1, 2]
    assert V._transient(httpx.ReadTimeout("The read operation timed out"))
