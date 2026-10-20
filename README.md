# dxf-autoparam

Turn an **existing 2D DXF/GAD** into a **parametric model** automatically — no redrawing, no per-structure rule
engine — then change a value and get the regenerated DXF back.

Standalone prototype (Python, `uv`, `ezdxf`). Not connected to `aagento-bridge`; it only *reads* that repo's kernel
library once, to generate test drawings with known ground truth.

## Two layers

1. **Geometry engine (deterministic, no AI):** reads any DXF — views stored as blocks, nested/mirrored blocks,
   malformed old exports (rebuilt), hidden layers skipped — finds every set-out line and every size between them,
   and builds an exact parametric program (every line = formula of named values). Generic names (`OpenX1`, `ThkY2`).
2. **CAD JSON + regions (deterministic):** the drawing as data a model can reason about — every entity with its
   geometry, properties, connections and the set-out lines it sits on; the closed **regions** its lines bound (the
   atomic parts: area, nesting, which regions touch on which side, the hatch that fills them); dimensions and notes tied
   to what they measure / say; relationship candidates (thickness, opening, pitch, symmetry, repeats, rests-on …).
3. **Gemini as a tool-using agent + validator** (`ai/agent.py`, the app's default): Gemini inspects regions and lines, then
   defines parts, parameters, formulas, constraints and behaviours in small batched edits; the engine checks each edit at
   once and answers accepted / rejected with the reason, so a mistake costs one small correction, not a rewrite. The
   one-big-answer path below remains (`dxf-autoparam ai --oneshot`).
   **Gemini + validator (one-shot):** Gemini 3.8 Flash on your Vertex project reads three pictures (faithful, labelled set-out
   lines, region map) + the CAD JSON + the project's bridge knowledge and says what it IS and what it is MEANT to do:
   a parts tree (assembly → component → subcomponent, built from regions), engineering names (`ClearSpan`, `TopSlab`,
   `BedLevel` …) with evidence and confidence, which levels are site inputs, set-out formulas, relations, **behaviours**
   (when a value grows: what grows, moves, stays fixed, keeps its thickness / level / slope / connection) and
   **constraints**. **Every claim is checked by the deterministic engine**: values = measured, formulas reproduce their
   line, behaviours and constraints are MEASURED by changing each value; a constraint the model does not keep is
   enforced in closed form where possible; failures go back to Gemini with the reasons. Coordinates never come from the AI.
4. **A person chooses** what to parametrize (hold parts as drawn, keep values, drop constraints), previews each value,
   exports — or **tells Gemini** in words (Gemini tab): which parts / views to parametrize, which to keep as drawn, which
   values will change, how to group parts (click region labels on the drawing to name them; **Tell Gemini…** turns the
   Structure ticks into an instruction). **Revise current answer** asks Gemini to change its answer as you say, on the
   cached prompt. Gemini's **thinking** streams live in the Gemini tab and is kept with each answer; **■ Stop Gemini**
   ends a run at its next streamed message (a stopped first call changes nothing; a stopped repair keeps the best
   validated round; tokens generated before the stop are billed).
   Design notes: **[docs/DESIGN_INTENT.md](docs/DESIGN_INTENT.md)**.

```bash
uv sync
uv run dxf-autoparam serve [sheet.dxf]                        # the sheet workspace → http://127.0.0.1:8765 (views, linked
                                                              # views, shared sizes, preview / apply / undo, the agent session, original / reset, export)
                                                              # the single-view page with its Gemini panel: /classic
uv run dxf-autoparam serve my.dxf --answer gemini-answer.json # re-open a saved, validated Gemini answer — no AI call
uv run python tools/serve_replay.py my.dxf gemini-answer.json # the app with Gemini REPLAYED (marked [replay]) — UI checks, no cost
uv run python tools/serve_scripted.py --port 8799              # the workspace with the AGENT SCRIPTED (generated two-view box) — then: node tools/ui_check.mjs
uv run dxf-autoparam agent-eval                               # the agent scored per category (offline scripted; --live --yes-spend for the real model)
uv run dxf-autoparam ai my.dxf --view 0 --json program.json --set ClearSpan=4000 -o my_4000.dxf
uv run dxf-autoparam analyse examples/two_cell_box_section.dxf --validate --json model.json
uv run dxf-autoparam regen examples/two_cell_box_section.dxf --set OpenX1=4000 -o box_4000.dxf
uv run dxf-autoparam json my.dxf --split out/my_json -o my_cad.json   # the CAD JSON (whole, and split into 6 files)
uv run dxf-autoparam learn my.dxf my_edited.dxf  # what an edit changed, what grew / stayed, what the program cannot explain
uv run dxf-autoparam views my_sheet.dxf          # list the views on a sheet; then --view N or --region x0,y0,x1,y1
uv run dxf-autoparam bench                       # intent recovery on 17 independent structure families
uv run dxf-autoparam production bench            # the production rule integration on generated drawings (needs node + `production build`)
uv run pytest -q                                 # 99 tests, no AI calls (Vertex faked; agent scripted; a real answer replayed)
uv run ruff check src tests tools                # ruff 0.16 rules, pinned
```

How it works, results, limitations and the plan for aagento-bridge: **[docs/AUTO_PARAMETRIZATION.md](docs/AUTO_PARAMETRIZATION.md)**.

| Folder | |
|---|---|
| `src/dxf_autoparam/` | the generic engine (`analyse`, `build`, `regen`, `dxf_read`, `dxf_write`, `views`, `pipeline`), `topology` (regions), `cadjson`, `intent` (behaviours, constraints, selection), `graph`, `learn`, `validator`, `ai/`, CLI, demo server |
| `sheet.py`, `crossview.py`, `workspace.py`, `ai/sheet_ai.py`, `static/workspace.html` | a whole sheet: views found and named, views drawn in projection analysed as one unit, sizes shared across views, the canvas workspace and its API — see `docs/MULTIVIEW.md`. **The agent is one session** (`ai/run.py`, `ai/loop.py`, `viewimg.py`, `baseline.py`, `status.py`): one instruction, the model decides the stages, the engine checks and measures — see `docs/AGENT_SESSION.md` |
| `src/dxf_autoparam/domains/` | optional semantic packs (`bridge.py`: site levels, names) — the only domain vocabulary |
| `ai/library.py`, `knowledge/library/`, `knowledge/agent_context/` | the **engineering library**: skills, definitions and rules the agent retrieves on demand when a domain pack is on (migrated, hash-verified source knowledge + authored recipes) — see `docs/KNOWLEDGE_LIBRARY.md`; `dxf-autoparam library list \| search \| show \| discover` |
| `production/`, `ai/production.py`, `tools/production/bridge_rules.ts`, `knowledge/production/` | the **production bridge rule engines**: aagento-bridge's `BRIDGE_REGISTRY` bundled and run through one boundary, its knowledge extracted (verified formulas, measured dependencies, views, findings) with provenance and freshness, bound to a drawing's own values and guarding every change — see `docs/PRODUCTION_RULES.md`; `dxf-autoparam production build \| extract \| status \| show \| bench` |
| `examples/` | drawings to try (box sections, RCC box half-section GAD, girder deck, deck slab, pier, retaining wall, well, a 3-cell box drawn as loose lines) |
| `fixtures/library/` | 17 kernel families as DXF + their single-parameter ground-truth variants |
| `tools/` | fixture/example generators (`export_library_oracle.ts` reads the aagento kernel read-only) |

Regenerating the fixtures (only needed if the aagento kernel library changes):

```bash
../aagento-bridge/node_modules/.bin/esbuild tools/export_library_oracle.ts --bundle --platform=node --format=esm \
  --outfile=.cache/oracle.mjs --tsconfig=../aagento-bridge/tsconfig.json --log-level=warning
node .cache/oracle.mjs fixtures/library && uv run python tools/json_to_dxf.py fixtures/library && uv run python tools/make_examples.py
```

## Gemini setup and cost

Uses Application Default Credentials and your gcloud project (see `.env.example`; nothing is hardcoded). Model:
**Gemini 3.8 Flash, thinking high**; fallback **3.7 Flash, thinking high** when 3.8 is out of capacity or past its
deadline (429 / 503 / 504). A model that could not answer a whole call is not asked first again for `VERTEX_BREAKER_S` (300 s, doubled for each
probe that fails again): a live run lost about two minutes a turn asking an overloaded primary twice before the fallback answered. The verdict says when
more than one model answered. `VERTEX_TIMEOUT_MS` (default 10 min) is also the server's deadline — the SDK sends it as
`X-Server-Timeout`, so a shorter value turns long thinking into 504s.

Two caches:
- **answers on disk** (`.cache/ai/`), keyed by everything sent including model and thinking level — re-opening a
  drawing, holding parts, changing the selection cost nothing;
- **Vertex explicit prompt cache** for what repeats within a run (system prompt, pictures, knowledge, CAD JSON —
  ~80k tokens on a 50-region view): created by the first call, reused by each repair round (which then sends only its
  rejection list), deleted at the end of the run (TTL 20 min otherwise). `VERTEX_EXPLICIT_CACHE=0` turns it off.

Every call's tokens — including `vertex_cached_tokens` and `prompt_cache` (created / reused / unavailable) — are logged
in `.cache/ai/usage.jsonl`.

## Rules the engine applies itself (whatever the AI proposes)

- **Growth direction is design intent, decided from the drawing:** when a size changes, which side stays — both sides equally about the line a
  structure mirrors about, away from what is fixed or existing, else the base (marked provisional) — is worked out per structure, tried for real, and
  shown under each value (*Left stays · Centred · Right stays*); a person's choice always replaces it (**[docs/DESIGN_INTENT.md](docs/DESIGN_INTENT.md)** §13).
- **Slopes keep their angle:** an inclined edge with a ratio the drawing states ("1(V):1.5(H)", "SLOPE 2:1") or a clean
  drafting ratio sets its toe out by ratio × height.
- **Annotations follow what they state:** level notes follow their line through the drawing's own level datum (found from
  the notes, so sheets not drawn at RL×1000 work); notes stating a size or a worked-out value ("4000 mm EARTH CUSHION")
  update; dimension text overrides that write the measurement update; dimensions re-render. Ratios and scales are never
  read as sizes.
- **Existing structures** (doubling / extension drawings) are parametric too; the app's **Hold existing fixed** switch
  keeps them exactly as drawn — re-applied instantly, no new AI call.
