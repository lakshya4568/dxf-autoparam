"""Token Harbor, checked: list its models and, on request, make ONE tiny call to a free one through the adapter the agent itself uses.

    uv run python tools/tokenharbor_check.py                                 # the catalogue: every model, its price per million tokens, free or not (spends nothing)
    uv run python tools/tokenharbor_check.py --test                          # one tool-call round trip on the first free model
    uv run python tools/tokenharbor_check.py --test mimo-v2.5:free --picture # a named model, with a tiny picture in the message

A model that is not free is refused unless --paid is given: the check is meant to cost nothing. The key comes from .env / the environment (run it
from the repository root) and is never printed. The call is made against a scratch cache and ledger, so it leaves nothing in the person's own
cost ledger. Exit code 0 when the model answered with the tool call it was asked for."""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
from pathlib import Path

from google.genai import types

from dxf_autoparam.ai import gateway, tokenharbor, vertex

PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")  # one red pixel


def price_of(m: dict) -> str:
    pi, po = tokenharbor.prices(m)
    if tokenharbor.is_free(m):
        return "free"
    return f"${pi:g} / ${po:g}" if pi is not None and po is not None else "no price"


def listing(models: list[dict]) -> None:
    free = [m for m in models if tokenharbor.is_free(m)]
    print(f"{len(models)} models, {len(free)} free (price per million tokens, input / output)")
    for m in sorted(models, key=lambda m: (not tokenharbor.is_free(m), tokenharbor.prices(m)[0] or 0.0, m["id"])):
        print(f"  {m['id']:<46} {price_of(m):<18} context {m.get('context_length') or '?':>8}  tool calls {'yes' if m.get('tool_call') else 'no'}")


def test_call(m: dict, picture: bool) -> int:
    """One turn through the adapter: the model is asked to call a `report` tool (and, with a picture, to name its colour)."""
    tools = [types.Tool(function_declarations=[types.FunctionDeclaration(
        name="report", description="Report the result of the check.",
        parameters_json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}}, "required": ["ok", "note"]})])]
    text = "Call the report tool with ok=true and a one-word note." + (" The note is the colour of the picture." if picture else "")
    parts = [types.Part.from_text(text=text)] + ([types.Part.from_bytes(data=PIXEL, mime_type="image/png")] if picture else [])
    with tempfile.TemporaryDirectory() as scratch:
        vertex.CACHE = gateway.CACHE = Path(scratch)
        gw = gateway.Gateway(gateway.GatewayConfig(model=m["id"], thinking="low", provider="tokenharbor", price=tokenharbor.entry(m)["price"]))
        notes: list[str] = []
        try:
            content, usage = gw.step("You are a connectivity check.", tools, [], "check", [types.Content(role="user", parts=parts)], "check", "low", max_out=512,
                                     on_event=lambda e: notes.append(e["text"]) if e.get("kind") == "note" else None)
        except vertex.GeminiUnavailable as exc:
            print(f"FAIL  {m['id']}: {exc}")
            return 1
        finally:
            gw.close()
    calls = [p.function_call for p in content.parts or [] if getattr(p, "function_call", None)]
    cost = f", cost ${usage['cost_usd']:.6f}" if usage["cost_usd"] is not None else ""
    print(f"{'PASS' if calls else 'FAIL'}  {m['id']}: {usage['seconds']} s, {usage['input_tokens']} in / {usage['output_tokens']} out ({usage['thinking_tokens']} thinking){cost}")
    for c in calls:
        print(f"      tool call: {c.name}({dict(c.args or {})})")
    if not calls:
        print(f"      no tool call came back; the model said: {' '.join(p.text for p in content.parts or [] if getattr(p, 'text', None) and not p.thought)[:200]!r}")
    for what in usage.get("dropped", []):
        print(f"      the model refused {what}; the adapter went on without it")
    for n in notes:
        print(f"      note: {n}")
    if picture:
        print(f"      pictures: {'left out (this model is text-only)' if gw.text_only else 'accepted'}")
    return 0 if calls else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test", nargs="?", const="", metavar="MODEL", help="make one tiny call (default: the first free model)")
    ap.add_argument("--picture", action="store_true", help="with --test: put a one-pixel picture in the message")
    ap.add_argument("--paid", action="store_true", help="with --test: allow a model that is not free")
    a = ap.parse_args()
    key = tokenharbor.key()
    if not key:
        print("TOKENHARBOR_API_KEY is not set: put it in .env (and run this from the repository root)")
        return 2
    print(f"key: set ({len(key)} characters, not shown) · {tokenharbor.base_url()}")
    try:
        models = tokenharbor.fetch(timeout=20.0)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"the catalogue could not be had: {exc}")
        return 1
    listing(models)
    if a.test is None:
        return 0
    free = sorted((m for m in models if tokenharbor.is_free(m)), key=lambda m: m["id"])
    target = next((m for m in models if m["id"] == a.test), None) if a.test else (free[0] if free else None)
    if target is None:
        print(f"\nno such model: {a.test!r}" if a.test else "\nno free model in the catalogue")
        return 1
    if not tokenharbor.is_free(target) and not a.paid:
        print(f"\n{target['id']} is not free ({price_of(target)}): --paid to call it anyway")
        return 1
    print()
    return test_call(target, a.picture)


if __name__ == "__main__":
    sys.exit(main())
