# TEMPORARY — remove the Experiential Labs gateway when `gemini-4-argon` leaves it

The Experiential Labs gateway exists in this project only to reach `gemini-4-argon` through an OpenAI-compatible endpoint (the model is also reachable
directly on Vertex AI: "Gemini 4 Argon · high (premium)"). When the gateway stops serving it, delete the parts below. The adapter itself
(`ai/gateway.py`) is shared: it also serves Token Harbor (`provider="tokenharbor"`, see `ai/tokenharbor.py`), so it stays unless that goes too.

## Remove
1. `src/dxf_autoparam/ai/gateway.py` — delete the `"gateway"` entry of `PROVIDERS`, `BASE_URL`, and make `"tokenharbor"` the default `provider` of
   `GatewayConfig` (delete the whole file only when Token Harbor is removed as well, with `ai/tokenharbor.py`, `tools/tokenharbor_check.py`,
   `tests/test_tokenharbor.py` and the `_no_token_harbor` fixture of `tests/conftest.py`).
2. `src/dxf_autoparam/ai/vertex.py` — delete the `MODEL_CHOICES.append({"id": "gateway:gemini-4-argon", …})` block and the
   `gateway_ok` filter line in `model_choices()`.
3. `src/dxf_autoparam/workspace.py` — in `get_gem`, change `choice.get("provider") in ("gateway", "tokenharbor")` to `== "tokenharbor"`.
4. `src/dxf_autoparam/ai/usage.py` — keep: the `cost_usd` / `reported` handling also records Token Harbor's cost (its listed price × tokens).
5. Tests — delete `test_gateway_translates_the_loops_turns_and_reports_its_cost` and `test_gateway_drops_optional_fields_once_when_a_model_rejects_them`
   in `tests/test_workspace_api.py`, and `test_the_other_gateway_is_unchanged_by_the_provider_table` in `tests/test_tokenharbor.py`.
6. `.env` / `.env.example` — delete `EXPLABS_API_KEY` (and revoke the key at platform.experientiallabs.ai/settings).
7. This file.

## Check afterwards
`uv run pytest -q tests/test_workspace_api.py tests/test_tokenharbor.py`, `uv run ruff check src tests`, and the page check (`tools/ui_check.mjs`): the picker lists
the two Vertex models (plus Token Harbor's when its key is set), not three. Ledger lines with model `gateway:gemini-4-argon` stay in `.cache/ai/usage.jsonl` and
still show in the Cost tab as history.

## Notes
- Caching is not used or wanted on this path (the gateway reports `cached_tokens` and the ledger records it; nothing is created or managed).
- Sent on every turn: model, messages, temperature 0, max_tokens ≤ 32768, reasoning_effort (the picker's level), tools + tool_choice "required".
