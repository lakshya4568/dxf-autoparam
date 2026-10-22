"""Token Harbor (https://tokenharbor.ai): an OpenAI-compatible gateway to many models, some of them free — the models the picker offers
when Vertex is not an option (its credits are out, or its capacity is).

The transport is `ai/gateway.py` (the same `step` the agent loop speaks to Vertex); this module is the catalogue: which models the gateway
has, which of them cost nothing, and how each becomes an entry of the page's model picker.

    TOKENHARBOR_API_KEY   the key (a secret: environment / .env only, never logged, never sent to the page)
    TOKENHARBOR_BASE_URL  default https://tokenharbor.ai/v1
    TOKENHARBOR_MODELS    which models the picker offers: `free` (default: those priced at zero), `all`, or a comma-separated list of ids

The catalogue is `GET /v1/models` (no tokens are spent by asking): per model its id, label, tier, price per million tokens (input, output, cache),
context length and whether it takes tool calls. It does not say whether a model reads images: the picture-carrying agent session is
the first thing a model that cannot is found out by (the gateway answers 400 to an image it cannot take). The list is kept for a quarter of
an hour in memory and, as the last good copy, on disk, so a gateway that is slow or down never stops the page from loading.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import httpx

from .vertex import CACHE, load_env_file

BASE_URL = "https://tokenharbor.ai/v1"
PREFIX = "tokenharbor:"  # a picker id is "tokenharbor:<gateway id>" (the gateway's own ids may contain a colon: "…:free")
TTL_S = 900.0
ASK_S = 8.0  # how long the page waits for the catalogue before it shows the models without it
FAIL_S = 60.0  # after a failed ask, how long before the next one: a gateway that is down must not slow every page load
FILE = CACHE / "tokenharbor_models.json"

_lock = threading.Lock()
_memo: dict = {"at": 0.0, "models": None, "failed": 0.0, "error": ""}


def key() -> str:
    load_env_file()
    return os.environ.get("TOKENHARBOR_API_KEY", "").strip()


def base_url() -> str:
    load_env_file()
    return (os.environ.get("TOKENHARBOR_BASE_URL") or BASE_URL).rstrip("/")


def fetch(client: httpx.Client | None = None, timeout: float = ASK_S) -> list[dict]:
    """The gateway's catalogue, as it answers now. Raises when it cannot be had (no key, no answer, an answer that is not a catalogue)."""
    if not key():
        raise RuntimeError("TOKENHARBOR_API_KEY is not set: put it in .env")
    own = client is None
    c = client or httpx.Client(timeout=timeout)
    try:
        r = c.get(f"{base_url()}/models", headers={"Authorization": f"Bearer {key()}"}, timeout=timeout)
    finally:
        if own:
            c.close()
    if r.status_code != 200:
        raise RuntimeError(f"Token Harbor answered HTTP {r.status_code} to the model list: {r.text[:200]}")
    body = r.json()
    rows = body.get("data") if isinstance(body, dict) else body
    if not isinstance(rows, list) or not all(isinstance(m, dict) and m.get("id") for m in rows):
        raise RuntimeError("Token Harbor's model list is not a list of models")
    return rows


def _last_good() -> list[dict]:
    """The copy kept from the last answer: in memory, else on disk, else nothing."""
    if _memo["models"] is not None:
        return _memo["models"]
    try:
        return json.loads(FILE.read_text()) if FILE.exists() else []
    except (OSError, ValueError):
        return []


def catalog(client: httpx.Client | None = None, fresh: bool = False) -> list[dict]:
    """The catalogue, kept for a quarter of an hour; a gateway that does not answer gives the last good copy (memory, then disk), else nothing,
    and is not asked again for a minute (`last_error` says why)."""
    with _lock:
        now = time.time()
        if not fresh and _memo["models"] is not None and now - _memo["at"] < TTL_S:
            return _memo["models"]
        if not fresh and now - _memo["failed"] < FAIL_S:
            return _last_good()
        try:
            models = fetch(client)
        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
            _memo.update(failed=now, error=f"{type(exc).__name__}: {exc}")
            return _last_good()
        _memo.update(at=now, models=models, failed=0.0, error="")
        try:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            FILE.write_text(json.dumps(models))
        except OSError:
            pass  # the copy on disk is a convenience; the catalogue in memory is what serves
        return models


def last_error() -> str:
    """Why the last ask for the catalogue failed ("" when it did not)."""
    return _memo["error"]


def forget() -> None:
    """Drop what is remembered (a test, or a key that changed)."""
    with _lock:
        _memo.update(at=0.0, models=None, failed=0.0, error="")


def prices(m: dict) -> tuple[float | None, float | None]:
    p = m.get("pricing") or {}
    return p.get("input_usd_per_1m"), p.get("output_usd_per_1m")


def is_free(m: dict) -> bool:
    """Priced at zero for what goes in and what comes out (a price the catalogue does not give is not zero)."""
    pi, po = prices(m)
    return pi is not None and po is not None and float(pi) == 0.0 and float(po) == 0.0


def label_of(m: dict) -> str:
    name = re.sub(r"\s*\((free)\)\s*$", "", m.get("label") or m["id"], flags=re.IGNORECASE)  # the catalogue says "(Free)" itself; the label says it once
    if is_free(m):
        return f"{name} · free (Token Harbor)"
    pi, po = prices(m)
    return f"{name} · ${pi:g} / ${po:g} per M (Token Harbor)" if pi is not None and po is not None else f"{name} (Token Harbor)"


def wanted(models: list[dict], mode: str | None = None) -> list[dict]:
    """The models the picker offers: `free` (the default), `all`, or the ids named — free ones first, then by price and name."""
    load_env_file()
    mode = (mode or os.environ.get("TOKENHARBOR_MODELS") or "free").strip()
    if mode == "all":
        chosen = list(models)
    elif mode in ("", "free"):
        chosen = [m for m in models if is_free(m)]
    else:
        ids = {x.strip() for x in mode.split(",") if x.strip()}
        chosen = [m for m in models if m["id"] in ids]
    return sorted(chosen, key=lambda m: (not is_free(m), float("inf") if prices(m)[0] is None else float(prices(m)[0]), m.get("label") or m["id"]))


def entry(m: dict) -> dict:
    """One model as the picker's table has it (see `vertex.MODEL_CHOICES`): run through the gateway adapter, no fallback (a model chosen on purpose
    is not swapped behind the person's back), no explicit cache, and its price as the gateway lists it (USD per million tokens)."""
    p = m.get("pricing") or {}
    return {"id": PREFIX + m["id"], "label": label_of(m), "thinking": "high", "fallback": "", "provider": "tokenharbor", "gateway_model": m["id"],
            "explicit_cache": False, "free": is_free(m),
            "price": {"input": p.get("input_usd_per_1m"), "output": p.get("output_usd_per_1m"), "cached": p.get("cache_read_usd_per_1m")}}


def picker_entries(client: httpx.Client | None = None) -> list[dict]:
    """The Token Harbor models for the picker — none without a key or without a catalogue."""
    if not key():
        return []
    return [entry(m) for m in wanted(catalog(client))]


def choice(model_id: str) -> dict | None:
    """The picker entry for an id like `tokenharbor:deepseek-v4-flash:free`, whether or not the picker lists it now (a run may have been started
    with a model the catalogue has since dropped from the list: it is still reachable by its id while the gateway serves it)."""
    if not model_id.startswith(PREFIX):
        return None
    gid = model_id[len(PREFIX):]
    m = next((x for x in catalog() if x["id"] == gid), None)
    return entry(m) if m is not None else {**entry({"id": gid}), "free": False}
