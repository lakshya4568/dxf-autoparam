# TEMPORARY — remove the Experiential Labs gateway when `gemini-4-argon` leaves it

The gateway exists in this project only to reach `gemini-4-argon` through an OpenAI-compatible endpoint (the model is also reachable
directly on Vertex AI: "Gemini 4 Argon · high (premium)"). When the gateway stops serving it, delete everything below. Nothing else
depends on it.

## Remove
1. `src/dxf_autoparam/ai/gateway.py` — delete the file.
2. `src/dxf_autoparam/ai/vertex.py` — delete the `MODEL_CHOICES.append({"id": "gateway:gemini-4-argon", …})` block and the
   `gateway_ok` filter line in `model_choices()`.
3. `src/dxf_autoparam/workspace.py` — in `get_gem`, delete the `if choice and choice.get("provider") == "gateway":` branch (keep the Vertex branch).
4. `src/dxf_autoparam/ai/usage.py` — delete the `cost_usd` / `reported` handling (the `cost_source` field and the "gateway" source);
   the price table alone then decides the cost.
5. `tests/test_workspace_api.py` — delete `test_gateway_translates_the_loops_turns_and_reports_its_cost` and
   `test_gateway_drops_optional_fields_once_when_a_model_rejects_them`.
6. `.env` / `.env.example` — delete `EXPLABS_API_KEY` (and revoke the key at platform.experientiallabs.ai/settings).
7. This file.

## Check afterwards
`uv run pytest -q tests/test_workspace_api.py`, `uv run ruff check src tests`, and the page check (`tools/ui_check.mjs`): the picker lists
two models, not three. Ledger lines with model `gateway:gemini-4-argon` stay in `.cache/ai/usage.jsonl` and still show in the Cost tab as history.

## Notes
- Caching is not used or wanted on this path (the gateway reports `cached_tokens` and the ledger records it; nothing is created or managed).
- Sent on every turn: model, messages, temperature 0, max_tokens ≤ 32768, reasoning_effort (the picker's level), tools + tool_choice "required".
