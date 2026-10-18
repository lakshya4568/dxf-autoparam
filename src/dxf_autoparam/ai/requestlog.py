"""What each model call was sent and what it cost — kept while the run goes on, so the person can look at any request, live.

A run's model calls are its money. For every call this keeps: how the request was built (the system prompt and the tools, then each content of the
conversation with its size and its pictures), how much of it was the SAME as the call before — a provider's prompt cache matches a request from its start,
content by content, and stops at the first difference, so this is the part it can serve cheaply — what the provider billed and how much of that it served from
its cache, and which thinking level the call was made at and why. The last few requests are also kept whole (the pictures' bytes left out) for a closer look.

`CacheWatch` reads the same records and says when the provider is NOT caching what the request shares with the one before it (a run is then better off
with an explicit cache), and when a change of thinking level seems to have cost the cache — the two ways a cost saving can quietly turn into a cost increase.
"""

from __future__ import annotations

import hashlib
import json
import time

KEEP = 800  # call records kept per run
FULL_KEEP = 3  # requests kept whole (an answer to "what exactly was sent?" for the last few calls)
IMAGE_TOKENS = 1120  # the provider's fixed cost of one picture at its default resolution (documented): for the estimate only


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _dump(obj) -> dict:
    return obj.model_dump(mode="json", exclude_none=True)


def _blank(o):
    """A serialized request without the pictures' bytes: each is replaced by its size and a short digest."""
    if isinstance(o, dict):
        out = {k: _blank(v) for k, v in o.items() if k != "inline_data"}
        blob = o.get("inline_data")
        if isinstance(blob, dict):
            data = str(blob.get("data") or "")
            out["inline_data"] = {"mime_type": blob.get("mime_type"), "bytes": len(data) * 3 // 4, "sha256": _sha(data)[:12], "elided": True}
        return out
    if isinstance(o, list):
        return [_blank(x) for x in o]
    return o


def _part_view(p) -> dict:
    """One part of a content, said without its bytes."""
    if getattr(p, "text", None):
        return {"t": "thought" if getattr(p, "thought", False) else "text", "chars": len(p.text)}
    fc = getattr(p, "function_call", None)
    if fc is not None:
        return {"t": "call", "name": fc.name, "chars": len(json.dumps(dict(fc.args or {}), default=str))}
    fr = getattr(p, "function_response", None)
    if fr is not None:
        return {"t": "result", "name": fr.name, "chars": len(json.dumps(fr.response or {}, default=str)), "images": len(getattr(fr, "parts", None) or [])}
    if getattr(p, "inline_data", None) is not None:
        return {"t": "image", "images": 1}
    return {"t": "other", "chars": 0}


def _view(i: int, role: str, parts: list, kind: str = "") -> dict:
    views = [_part_view(p) for p in parts or []]
    chars = sum(v.get("chars", 0) for v in views)
    images = sum(v.get("images", 0) for v in views)
    return {"i": i, "role": role, **({"kind": kind} if kind else {}), "parts": views, "chars": chars, "images": images, "tokens_est": chars // 4 + images * IMAGE_TOKENS}


class RequestLog:
    """The record of one run's model calls (see the module doc)."""

    def __init__(self) -> None:
        self.records: list[dict] = []
        self.n = 0
        self._prev: dict | None = None  # the previous request's head digest and per-content digests, to find what is shared
        self._full: dict[int, str] = {}  # call number → the request as JSON text (the last FULL_KEEP)

    def record(self, *, turn: int, label: str, model: str, thinking: str, why: str, system: str, tools: list, prefix_parts: list, history: list,
               explicit: bool, pruned: dict | None = None) -> dict:
        """Describe the request about to be sent (and keep it whole for a moment). Returns the record; `finish` adds what the provider says of it."""
        self.n += 1
        tools_dump = [_dump(t) for t in tools]
        tools_json = json.dumps(tools_dump, sort_keys=True)
        head = _sha(system + tools_json)
        prefix_dump = [_dump(p) for p in prefix_parts]
        history_dump = [_dump(c) for c in history]
        contents = [_view(0, "user", prefix_parts, "prefix"), *[_view(k, c.role, c.parts, "") for k, c in enumerate(history, 1)]]
        contents[0]["tokens_est"] += (len(system) + len(tools_json)) // 4  # the system prompt and the tools come first, in front of the prefix
        digests = [_sha(json.dumps(prefix_dump, sort_keys=True))[:16]] + [_sha(json.dumps(c, sort_keys=True))[:16] for c in history_dump]
        total = sum(c["tokens_est"] for c in contents)
        rec = {"n": self.n, "turn": turn, "label": label, "at": round(time.time(), 1), "model": model, "thinking": thinking, "thinking_why": why,
               "cache": {"explicit": explicit}, "system_chars": len(system), "tools": len(tools),
               "totals": {"contents": len(contents), "chars": sum(c["chars"] for c in contents) + len(system) + len(tools_json), "images": sum(c["images"] for c in contents),
                          "tokens_est": total},
               "contents": contents, "prefix_reuse": self._reuse(head, digests, contents, total, pruned or {})}
        if pruned and any(pruned.values()):
            rec["pruned"] = {k: v for k, v in pruned.items() if v}
        self._prev = {"n": self.n, "head": head, "digests": digests}
        self.records.append(rec)
        del self.records[:-KEEP]
        self._full[self.n] = json.dumps({"model": model, "thinking": thinking, "explicit_prefix_cache": explicit, "system": system, "tools": tools_dump,
                                         "prefix": _blank(prefix_dump), "contents": _blank(history_dump)}, default=str)
        for old in sorted(self._full)[:-FULL_KEEP]:
            del self._full[old]
        return rec

    def _reuse(self, head: str, digests: list[str], contents: list[dict], total: int, pruned: dict) -> dict:
        prev = self._prev
        if prev is None:
            return {"with": None}
        if prev["head"] != head:
            k = 0  # a different system prompt or tool list: nothing before the conversation can be reused either
        else:
            k = 0
            while k < min(len(digests), len(prev["digests"])) and digests[k] == prev["digests"][k]:
                k += 1
        same = sum(c["tokens_est"] for c in contents[:k])
        out = {"with": prev["n"], "contents_same": k, "contents": len(digests), "tokens_est_same": same, "tokens_est": total, "share": round(same / total, 3) if total else 0.0}
        if prev["head"] != head:
            out["broke_because"] = "the system prompt or the tools changed"
        elif k < len(prev["digests"]):  # the earlier request had content that this one does not carry as it was: something old was changed
            why = []
            if pruned.get("compacted"):
                why.append(f"{pruned['compacted']} older turn(s) were folded into the working state")
            if pruned.get("trimmed"):
                why.append(f"{pruned['trimmed']} older tool result(s) were cut to their verdicts")
            if pruned.get("pictures"):
                why.append(f"the pictures of {pruned['pictures']} older result(s) were dropped")
            out["broke_because"] = "; ".join(why) or f"the conversation was changed at content {k}"
            out["broke_at"] = k
        return out

    def finish(self, rec: dict, usage: dict) -> None:
        """What the provider billed for the call, and how much of the input it served from a cache (an answer replayed from disk costs nothing)."""
        inp = int(usage.get("input_tokens") or 0)
        cached = int(usage.get("vertex_cached_tokens") or 0)
        rec["usage"] = {"model": usage.get("model"), "input_tokens": inp, "cached_tokens": cached, "uncached_tokens": max(0, inp - cached),
                        "cached_share": round(cached / inp, 3) if inp else None, "output_tokens": int(usage.get("output_tokens") or 0),
                        "thinking_tokens": int(usage.get("thinking_tokens") or 0), "seconds": usage.get("seconds"), "finish": usage.get("finish"),
                        "prompt_cache": usage.get("prompt_cache"), "replayed": bool(usage.get("cached"))}
        if inp and rec["totals"]["tokens_est"]:
            rec["usage"]["estimate_vs_billed"] = round(rec["totals"]["tokens_est"] / inp, 2)  # how far the page's own estimate is from what was billed

    def listing(self, since: int = 0, limit: int = 50, brief: bool = False) -> dict:
        """The latest `limit` calls (or, with `since`, the calls after that number, oldest first — for a page that follows the run). `brief`: without each
        request's list of contents, which is most of it."""
        rows = self.records[-limit:] if since <= 0 else [r for r in self.records if r["n"] > since][:limit]
        if brief:
            rows = [{k: v for k, v in r.items() if k != "contents"} for r in rows]
        return {"requests": rows, "next": rows[-1]["n"] if rows else max(since, 0), "totals": self.totals()}

    def totals(self) -> dict:
        billed = [r["usage"] for r in self.records if r.get("usage") and not r["usage"]["replayed"] and r["usage"]["input_tokens"]]
        inp = sum(u["input_tokens"] for u in billed)
        cached = sum(u["cached_tokens"] for u in billed)
        levels: dict[str, int] = {}
        for r in self.records:
            levels[r["thinking"]] = levels.get(r["thinking"], 0) + 1
        shares = [r["prefix_reuse"]["share"] for r in self.records if r["prefix_reuse"].get("with") is not None]
        return {"calls": self.n, "billed_calls": len(billed), "input_tokens": inp, "cached_tokens": cached, "uncached_tokens": inp - cached,
                "cached_share": round(cached / inp, 3) if inp else None, "output_tokens": sum(u["output_tokens"] for u in billed),
                "thinking_tokens": sum(u["thinking_tokens"] for u in billed), "seconds": round(sum(u["seconds"] or 0 for u in billed), 1),
                "thinking_levels": levels, "mean_prefix_share": round(sum(shares) / len(shares), 3) if shares else None}

    def payload(self, n: int) -> str | None:
        """The request of call `n` as it was sent (JSON text, pictures' bytes left out) — kept for the last few calls only."""
        return self._full.get(n)


def _billed(rec: dict | None, min_input: int) -> bool:
    """A call the provider billed (not replayed from disk), big enough to be cached at all."""
    return bool(rec and rec.get("usage") and not rec["usage"]["replayed"] and rec["usage"]["input_tokens"] >= min_input)


def _informative(rec: dict | None, min_input: int, min_share: float) -> bool:
    """A billed call that says something about caching: mostly the same as the call before, so a cache had something to serve."""
    if not _billed(rec, min_input):
        return False
    share = (rec.get("prefix_reuse") or {}).get("share")
    return share is not None and share >= min_share


class CacheWatch:
    """Reads the records and says when a saving has turned into a cost.

    silent()       the provider cached next to nothing of what each of the last `need` requests shared with the one before it
    level_broke()  a change of thinking level was followed by a collapse of the cached tokens (to under half of the call before, which had
                   them) at least twice and more often than not — while the request itself was mostly unchanged, so pruning cannot be the reason
    """

    def __init__(self, min_input: int = 8000, min_share: float = 0.8, low: float = 0.30, need: int = 3, floor: int = 4096):
        self.min_input, self.min_share, self.low, self.need, self.floor = min_input, min_share, low, need, floor
        self.bad = 0
        self.level_breaks = 0
        self.level_ok = 0
        self._last: dict | None = None

    def observe(self, rec: dict) -> None:
        informative = _informative(rec, self.min_input, self.min_share)
        if informative:
            self.bad = self.bad + 1 if float(rec["usage"]["cached_share"] or 0.0) < self.low else 0
        prev, self._last = self._last, rec
        if informative and prev is not None and rec["thinking"] != prev["thinking"] and _billed(prev, self.min_input) and prev["usage"]["cached_tokens"] >= self.floor:
            if rec["usage"]["cached_tokens"] < 0.5 * prev["usage"]["cached_tokens"]:
                self.level_breaks += 1
            else:
                self.level_ok += 1

    def silent(self) -> bool:
        return self.bad >= self.need

    def level_broke(self) -> bool:
        return self.level_breaks >= 2 and self.level_breaks > self.level_ok
