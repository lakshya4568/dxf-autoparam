"""What the model calls cost, read from the usage ledger (`.cache/ai/usage.jsonl`, one line per call) — per model, so two models can be compared.

Tokens are the API's own counts. Billing: the input price applies to the prompt tokens that were not served from a cache, the cached price to
those that were, and the output price to the answer plus the thinking (Vertex bills thought tokens as output). A price is data, not code: it
lives with the model in `vertex.MODEL_CHOICES` (`price`, USD per million tokens) and can be set or corrected with the environment
(`VERTEX_PRICES='{"model-id": {"input": 2, "cached": 0.1, "output": 10}}'`). A model with no price shows tokens and no amount: nothing is guessed.
Only calls made through this app are in the ledger; the cloud console's billing report is the authority for the whole project.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import vertex


def prices() -> dict[str, dict]:
    out = {m["id"]: m["price"] for m in vertex.MODEL_CHOICES if m.get("price")}
    try:
        extra = json.loads(os.environ.get("VERTEX_PRICES") or "{}")
    except ValueError:
        extra = {}
    for k, v in (extra.items() if isinstance(extra, dict) else []):
        if isinstance(v, dict):
            out[k] = {**out.get(k, {}), **v}
    return out


def _cost(p: dict | None, uncached: int, cached: int, output: int) -> float | None:
    if not p or "input" not in p or "output" not in p:
        return None
    return (uncached * p["input"] + cached * p.get("cached", p["input"]) + output * p["output"]) / 1e6


def summary(period: str = "all", ledger: Path | None = None, recent: int = 15) -> dict:
    """Per model: calls, tokens, cost — for `period` "today" or "all" — and the latest calls."""
    path = ledger or (vertex.CACHE / "usage.jsonl")
    today = time.strftime("%Y-%m-%d")
    price = prices()
    rows: dict[str, dict] = {}
    last: list[dict] = []
    for line in (path.read_text().splitlines() if path.exists() else []):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or not e.get("model") or (period == "today" and not str(e.get("at", "")).startswith(today)):
            continue
        r = rows.setdefault(e["model"], {"model": e["model"], "calls": 0, "errors": 0, "input": 0, "cached": 0, "output": 0, "thinking": 0, "seconds": 0.0})
        if e.get("error"):
            r["errors"] += 1
            continue
        inp, cac = int(e.get("input_tokens") or 0), int(e.get("vertex_cached_tokens") or 0)
        out, think = int(e.get("output_tokens") or 0), int(e.get("thinking_tokens") or 0)
        r["calls"] += 1
        r["input"] += max(inp - cac, 0)
        r["cached"] += cac
        r["output"] += out + think
        r["thinking"] += think
        r["seconds"] += float(e.get("seconds") or 0)
        last.append({"at": e.get("at"), "model": e["model"], "label": e.get("label"), "input": max(inp - cac, 0), "cached": cac, "output": out + think,
                     "cost": _cost(price.get(e["model"]), max(inp - cac, 0), cac, out + think)})
    models = []
    for r in rows.values():
        p = price.get(r["model"])
        models.append({**r, "seconds": round(r["seconds"], 1), "cost": _cost(p, r["input"], r["cached"], r["output"]), "price": p})
    return {"period": period, "models": sorted(models, key=lambda m: m["model"]), "recent": last[-recent:][::-1],
            "total_cost": sum(m["cost"] for m in models if m["cost"] is not None), "unpriced": [m["model"] for m in models if m["cost"] is None]}
