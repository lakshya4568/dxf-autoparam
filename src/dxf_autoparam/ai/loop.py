"""The agent loop — a model turn, the tool calls it makes, the engine's verdict on each, the next turn — with budgets
that PAUSE a run instead of cutting it.

The loop used to stop after a fixed 30 turns, whatever had been done, and the caller reported what it had as finished.
Here the reasons a run stops are named and different:

  finished      the model called `finish` and the engine's gate let it end
  wants_person  a decision only the person can make is open (a plan's question, an ask_person)
  soft_budget   one chunk of turns is used (only when the person asked for chunks): the run is PAUSED with everything it holds, and
                can be continued
  hard_budget   the most turns / tool calls one run may take, whatever the chunks: it stops, incomplete, and says so
  tokens        the most tokens (output + thinking) the run may spend
  time          the most working time (time waiting for a person does not count)
  stopped       the person pressed Stop (a call in flight is abandoned; the turn it would have made does not happen)

Nothing here decides success: the caller reads the engine's own state afterwards.

    loop = AgentLoop(gem, system, tools, prefix_parts, prefix_key, history, bench, Budget(), emit, stop)
    reason = loop.run()          # one chunk
    loop.add_user("THE PERSON ANSWERS …")
    reason = loop.run()          # the next, from exactly where it stopped (nothing already done is done twice)
"""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import asdict, dataclass, field

from .narrate import shrink, summarise
from .vertex import GeminiStopped


@dataclass
class Budget:
    """Limits of one run. `soft_turns` is the size of a chunk (the run pauses after it and may be continued); 0, the default, means
    the run is never paused for a chunk. The others are absolute for the run, across its chunks — safety nets against a model that
    loops, set high enough that a drawing of any size finishes inside them."""

    soft_turns: int = 0
    max_turns: int = 1000
    max_tool_calls: int = 6000
    wall_s: float = 14400.0
    max_tokens: int = 2_000_000
    call_s: float = 240.0  # one model call (the provider's own deadline is set from it)
    reads_without_edit: int = 6  # looking goes on this many turns without a single edit; then an edit (or a question) is asked for

    @classmethod
    def from_env(cls, **over) -> Budget:
        env = {"soft_turns": os.environ.get("AUTOPARAM_SOFT_TURNS") or os.environ.get("VERTEX_AGENT_MAX_STEPS"),
               "max_turns": os.environ.get("AUTOPARAM_MAX_TURNS"), "max_tool_calls": os.environ.get("AUTOPARAM_MAX_TOOL_CALLS"),
               "wall_s": os.environ.get("AUTOPARAM_WALL_S"), "max_tokens": os.environ.get("AUTOPARAM_MAX_TOKENS") or os.environ.get("VERTEX_AGENT_MAX_OUTPUT_TOKENS"),
               "call_s": os.environ.get("AUTOPARAM_CALL_S")}
        base = cls()
        for k, v in env.items():
            if v:
                setattr(base, k, type(getattr(base, k))(float(v)) if isinstance(getattr(base, k), float) else int(float(v)))
        return base.with_(**over)

    def with_(self, **over) -> Budget:
        out = copy.copy(self)
        for k, v in over.items():
            if v is not None and hasattr(out, k):
                setattr(out, k, type(getattr(out, k))(v))
        out.soft_turns = 0 if out.soft_turns <= 0 else min(out.soft_turns, out.max_turns)
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    def extended(self, s: LoopState, more_turns: int | None = None) -> Budget:
        """What a continued run is allowed. A limit the run has reached is lifted by another allowance of its own size (the turn limit by
        `more_turns` when that is given): a cap that stopped good work is lifted, not argued with. `more_turns` also raises a turn limit
        that was not reached, for a person who wants the run to go on for that many turns."""
        out = copy.copy(self)
        if s.turns >= out.max_turns:
            out.max_turns = s.turns + int(more_turns or out.max_turns)
        elif more_turns:
            out.max_turns = max(out.max_turns, s.turns + int(more_turns))
        if s.tool_calls >= out.max_tool_calls:
            out.max_tool_calls = s.tool_calls + out.max_tool_calls
        if s.tokens >= out.max_tokens:
            out.max_tokens = s.tokens + out.max_tokens
        if s.seconds >= out.wall_s:
            out.wall_s = s.seconds + out.wall_s
        return out.with_()


@dataclass
class LoopState:
    turns: int = 0
    chunk_turns: int = 0
    tool_calls: int = 0
    tokens: int = 0  # output + thinking tokens the provider billed (a free replay from cache is not counted)
    seconds: float = 0.0  # working time
    reads_only: int = 0
    done: bool = False
    usages: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"turns": self.turns, "tool_calls": self.tool_calls, "tokens": self.tokens, "seconds": round(self.seconds, 1), "done": self.done}


def _args(call) -> dict:
    a = getattr(call, "args", None) or {}
    return dict(a) if not isinstance(a, dict) else a


def short(a: dict) -> str:
    s = json.dumps(a, separators=(",", ":"), default=str)
    return s if len(s) <= 140 else s[:137] + "…"


def keep_pictures(history: list, keep: int = 3) -> None:
    """Every request re-sends the conversation: an old picture is paid for again each turn. Only the last `keep` pictures a
    tool returned stay in it; older ones become a line saying so (the model can ask for the picture again)."""
    from google.genai import types

    idx = [k for k, c in enumerate(history) if c.role == "user" and any(getattr(getattr(p, "function_response", None), "parts", None) for p in c.parts or [])]
    for k in idx[:-keep]:
        parts = []
        for p in history[k].parts:
            fr = getattr(p, "function_response", None)
            if fr is not None and getattr(fr, "parts", None):
                res = dict((fr.response or {}).get("result") or {}) if isinstance(fr.response.get("result"), dict) else {"result": fr.response.get("result")}
                res["picture"] = "removed to save tokens: call zoom_view again to see it"
                parts.append(types.Part.from_function_response(name=fr.name, response={"result": res}))
            else:
                parts.append(p)
        history[k] = types.Content(role="user", parts=parts)


def trim(history: list, keep: int = 8) -> None:
    """Tool results older than the last `keep` turns are cut to their verdict: a long inspect result from ten turns ago is
    paid for again every turn, and the model can always ask again."""
    from google.genai import types

    answers = [k for k, c in enumerate(history) if c.role == "user" and c.parts and getattr(c.parts[0], "function_response", None)]
    for k in answers[:-keep]:
        parts = []
        for p in history[k].parts:
            fr = p.function_response
            res = (fr.response or {}).get("result")
            if len(json.dumps(res, default=str)) <= 400:
                parts.append(p)
                continue
            short_ = {"trimmed": "older result; call the tool again if you need it"}
            if isinstance(res, dict):
                short_.update({x: res[x] for x in ("ok", "rejected", "done") if x in res})
            parts.append(types.Part.from_function_response(name=fr.name, response={"result": short_}))
        history[k] = types.Content(role="user", parts=parts)


def compact(history: list, state_text: str, keep: int = 6) -> int:
    """Older turns → ONE plain-text WORKING STATE message (built from the sheet and the bench, never from the model's prose), followed by the
    last `keep` exchanges verbatim. Returns how many model turns were folded in.

    Why this is safe with Gemini 3: thought signatures are validated strictly only for the CURRENT turn — every model function call and
    function response since the last plain user TEXT message. The working state is such a message, so what came before it is no longer
    part of the current turn; the exchanges kept after it carry their own signatures unchanged."""
    from google.genai import types

    model_idx = [k for k, c in enumerate(history) if c.role == "model"]
    if len(model_idx) <= keep:
        return 0
    cut = model_idx[-keep]
    folded = sum(1 for k in model_idx if k < cut)
    history[:] = [types.Content(role="user", parts=[types.Part.from_text(text=state_text)]), *history[cut:]]
    return folded


def history_size(history: list) -> dict:
    """What a request re-sends besides its cached prefix: characters of text and function payloads, pictures — measured on the contents."""
    chars, pictures, turns = 0, 0, 0
    for c in history:
        if c.role == "model":
            turns += 1
        for p in c.parts or []:
            if getattr(p, "text", None):
                chars += len(p.text)
            fc = getattr(p, "function_call", None)
            if fc is not None:
                chars += len(json.dumps(dict(fc.args or {}), default=str)) + len(fc.name or "")
            fr = getattr(p, "function_response", None)
            if fr is not None:
                chars += len(json.dumps(fr.response or {}, default=str))
                pictures += len(getattr(fr, "parts", None) or [])
            if getattr(p, "inline_data", None) is not None:
                pictures += 1
    return {"chars": chars, "pictures": pictures, "model_turns": turns, "contents": len(history)}


def pack(call, res) -> object:
    """The function response for one call. A result may carry a picture (`_image`: {"png": bytes, …}) — sent to the model as an
    image part of the response, so the model sees it next to the metadata that says what it shows."""
    from google.genai import types

    image = res.pop("_image", None) if isinstance(res, dict) else None
    if image:
        part = types.FunctionResponsePart(inline_data=types.FunctionResponseBlob(mime_type="image/png", data=image["png"]))
        return types.Part.from_function_response(name=call.name, response={"result": res}, parts=[part])
    return types.Part.from_function_response(name=call.name, response={"result": res})


class AgentLoop:
    """One model + one bench (anything with the small protocol below), with a conversation that survives pauses."""

    def __init__(self, gem, system: str, tools, prefix_parts: list, prefix_key: str, history: list, bench, budget: Budget, emit=None, stop=None,
                 thinking: str | None = None, step_thinking: str | None = None, label_prefix: str = "step", compactor=None,
                 keep_turns: int = 6, compact_every: int = 6):
        self.gem, self.system, self.tools = gem, system, tools
        self.prefix_parts, self.prefix_key, self.history = prefix_parts, prefix_key, history
        self.bench, self.budget = bench, budget
        self.emit = emit or (lambda e: None)
        self.stop = stop or (lambda: False)
        cfg = getattr(gem, "cfg", None)
        self.plan_thinking = thinking or getattr(cfg, "thinking", "high")
        self.step_thinking = step_thinking or os.environ.get("VERTEX_AGENT_STEP_THINKING") or self.plan_thinking
        self.label_prefix = label_prefix
        self.state = LoopState()
        # Bounded context: once the conversation holds keep_turns + compact_every model turns, the older ones are folded into one working
        # state (compactor(folded so far) → its text). None keeps the whole conversation (trimmed tool results, last pictures only).
        self.compactor = compactor
        self.keep_turns, self.compact_every = keep_turns, compact_every
        # tool results kept in full for this many turns (older ones are cut to their verdict; the model asks again if it needs them):
        # with a working state carrying what matters, the recent few are enough
        self.trim_keep = max(2, keep_turns // 2 + 1) if compactor is not None else 8
        self.compacted = 0
        self.sizes: list[dict] = []  # what each request re-sent besides the cached prefix (measured on the contents)

    # ── conversation ────────────────────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        from google.genai import types

        self.history.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))

    # ── budgets ─────────────────────────────────────────────────────────────────

    def _limit(self) -> str | None:
        b, s = self.budget, self.state
        if s.turns >= b.max_turns:
            return "hard_budget"
        if s.tool_calls >= b.max_tool_calls:
            return "hard_budget"
        if s.tokens >= b.max_tokens:
            return "tokens"
        if s.seconds >= b.wall_s:
            return "time"
        if b.soft_turns and s.chunk_turns >= b.soft_turns:
            return "soft_budget"
        return None

    def turns_left(self) -> dict:
        b, s = self.budget, self.state
        in_run = max(0, b.max_turns - s.turns)
        return {"in_chunk": max(0, b.soft_turns - s.chunk_turns) if b.soft_turns else in_run, "in_run": in_run}

    # ── one chunk ───────────────────────────────────────────────────────────────

    def run(self) -> str:
        s, b = self.state, self.budget
        s.chunk_turns = 0
        t0 = time.perf_counter()
        if hasattr(self.gem, "step_timeout_s"):
            self.gem.step_timeout_s = b.call_s
        try:
            while True:
                if self.stop():
                    return "stopped"
                if s.done:
                    return "finished"
                why = self._limit()
                if why:
                    return why
                s.turns += 1
                s.chunk_turns += 1
                label = f"{self.label_prefix} {s.turns}"
                self.emit({"kind": "turn", "turn": s.turns, "label": label, "turns_left": self.turns_left()})
                self.sizes.append({"turn": s.turns, **history_size(self.history)})
                try:
                    content, usage = self.gem.step(self.system, self.tools, self.prefix_parts, self.prefix_key, self.history, label,
                                                   self.plan_thinking if s.turns == 1 else self.step_thinking,
                                                   max_out=32768 if s.turns == 1 else 16384, stop=self.stop, on_event=self.emit)
                except GeminiStopped:
                    s.turns -= 1  # that turn never happened: nothing was executed, the conversation is as it was
                    s.chunk_turns -= 1
                    return "stopped"
                usage["thoughts"] = [p.text for p in content.parts or [] if getattr(p, "thought", False) and p.text]
                s.usages.append(usage)
                if not usage.get("cached"):
                    s.tokens += usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)
                self.history.append(content)
                calls = [p.function_call for p in content.parts or [] if getattr(p, "function_call", None)]
                if not calls:
                    self.add_user("Use the tools (one small edit at a time); call finish when done.")
                    continue
                s.tool_calls += len(calls)
                parts, done = execute_calls(self.bench, calls, self.emit, s, self.budget, self.turns_left())
                from google.genai import types

                self.history.append(types.Content(role="user", parts=parts))
                trim(self.history, keep=self.trim_keep)
                keep_pictures(self.history, keep=3)
                if self.compactor is not None and sum(1 for c in self.history if c.role == "model") >= self.keep_turns + self.compact_every:
                    folded = compact(self.history, self.compactor(self.compacted + 1), self.keep_turns)
                    if folded:
                        self.compacted += folded
                        self.emit({"kind": "note", "text": f"context compacted: {folded} older turn(s) folded into the working state "
                                                           f"(the conversation keeps the last {self.keep_turns})"})
                if done:
                    s.done = True
                    return "finished"
                if hasattr(self.bench, "wants_person") and self.bench.wants_person():
                    return "wants_person"
        finally:
            s.seconds += time.perf_counter() - t0


# ── one turn's calls ────────────────────────────────────────────────────────────


def execute_calls(bench, calls: list, emit, state: LoopState, budget: Budget, turns_left: dict) -> tuple[list, bool]:
    """Run one turn's tool calls on the bench; returns (function-response parts for the model, whether the run is done).

    A read answers at once. An edit is written, and after ALL the turn's edits the engine validates once: each edit then reads
    its own verdict (accepted, or refused with the reason and who can fix it), and a batch that broke the drawing is taken back.
    A call that does not parse comes back as an error the model can correct; nothing a call does can break the loop."""
    results: list[list] = []  # [call, result, args, t0]
    wrote, pending, done = False, [], False
    before = bench.snapshot()
    for n, call in enumerate(calls):
        a = _args(call)
        emit({"kind": "tool_start", "id": f"c{state.tool_calls - len(calls) + n + 1}", "name": call.name, "args": short(a),
              "unit": bench.unit_label() if hasattr(bench, "unit_label") else None})
    for n, call in enumerate(calls):
        a = _args(call)
        t0 = time.perf_counter()
        cid = f"c{state.tool_calls - len(calls) + n + 1}"
        try:
            if bench.is_read(call.name):
                if state.reads_only >= budget.reads_without_edit and call.name != "ask_person":
                    res = {"refused": f"you have looked for {state.reads_only} turns without an edit: make your edits now (define_parts / "
                                      "define_parameters / set_formulas, in batches), or ask_person / finish; looking is open again after an edit"}
                    emit(_tool_event(cid, call.name, a, False, "refused: edit first", res, t0, bench))
                else:
                    res = bench.read(call.name, a)
                    image = res.get("_image") if isinstance(res, dict) else None
                    emit(_tool_event(cid, call.name, a, not (isinstance(res, dict) and res.get("error")), "", res, t0, bench, image=image))
            elif call.name == "finish":
                res, done = bench.finish(a)
                ev = _tool_event(cid, "finish", a, done, "" if done else str(res.get("hint") or res.get("waiting_for") or "")[:200], res, t0, bench)
                if not done and res.get("waiting_for"):
                    ev["waiting"] = True  # not a failure: the person has to decide first
                emit(ev)
            elif (single := bench.single_of(call.name)) is not None:
                items = [(*bench.write(single, it), it) for it in (a.get("items") or [])]
                pending.append((len(results), items, call.name))
                res = None
                wrote = True
            else:
                item, note = bench.write(call.name, a)
                pending.append((len(results), [(item, note, a)], call.name))
                res = None
                wrote = True
        except (KeyError, TypeError, ValueError) as exc:  # a malformed call: the model reads why and corrects it
            res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            emit(_tool_event(cid, call.name, a, False, res["error"], res, t0, bench))
        results.append([call, res, a, t0, cid])
    if wrote:
        emit({"kind": "stage", "stage": "validating", "text": "the engine checks the edits against the drawing"})
        bench.validate()  # one check for the whole batch of edits; each edit reads its own verdict
        taken_back = bench.check_batch([(name, item) for _k, items, name in pending for item, _n, _a in items], before)
        for k, items, name in pending:
            verdicts = []
            for item, note, a in items:
                if item in taken_back:
                    f = taken_back[item]
                    v = {"item": item, "ok": False, "rejected": [f"{f['code']}: {f['cause']} — {f['measured']}"[:300]], "failure": f, "taken_back": True}
                else:
                    v = {"item": item, **bench.verdict(item, name)}
                if note:
                    v["engine"] = note
                bench.decorate(name, item, v)
                verdicts.append(v)
            results[k][1] = verdicts if bench.single_of(name) is not None else verdicts[0]
            call_, _r, a_, t0_, cid_ = results[k]
            ok_all = all(v["ok"] for v in verdicts)
            emit(_tool_event(cid_, call_.name, a_, ok_all, "; ".join(w for v in verdicts for w in v.get("rejected", []))[:240], results[k][1], t0_, bench))
        st = {**bench.status(), "turns_left": turns_left}
        emit({"kind": "status", **st})
        results[-1][1] = {"result": results[-1][1], "status": st}
        state.reads_only = 0
    else:
        state.reads_only += 1
        if state.reads_only >= 4 and not done and hasattr(bench, "nudge"):
            nudge = bench.nudge()
            if nudge and results:
                results[-1][1] = {"result": results[-1][1], "nudge": nudge, "turns_left": turns_left}
    parts = [pack(c, r) for c, r, *_ in results]
    return parts, done


def _tool_event(cid: str, name: str, a: dict, ok: bool, why: str, res, t0: float, bench, image: dict | None = None) -> dict:
    ev = {"kind": "tool", "id": cid, "name": name, "args": short(a), "args_full": shrink(a), "ok": bool(ok), "why": why,
          "result": shrink(res), "summary": summarise(name, a, res), "ms": int((time.perf_counter() - t0) * 1000),
          "unit": bench.unit_label() if hasattr(bench, "unit_label") else None}
    why_text = a.get("why") if isinstance(a, dict) else None
    if isinstance(why_text, str) and why_text.strip():
        ev["said"] = why_text.strip()[:240]
    if image:
        ev["image"] = {k: v for k, v in (image.get("meta") or {}).items() if k in ("id", "revision", "unit", "view_ids", "box", "ids", "state")}
        ev["image"]["id"] = image.get("id")
    return ev
