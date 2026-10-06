# dxf-autoparam

Turn an **existing 2D DXF/GAD** into a **parametric model** automatically — no redrawing, no per-structure rule
engine — then change a value and get the regenerated DXF back.

Standalone prototype (Python, `uv`, `ezdxf`). Not connected to `aagento-bridge`; it only *reads* that repo's kernel
library once, to generate test drawings with known ground truth.

```bash
uv sync
uv run dxf-autoparam serve examples/three_cell_box_lines.dxf --domain bridge   # demo UI → http://127.0.0.1:8765
uv run dxf-autoparam analyse examples/two_cell_box_section.dxf --validate --json model.json
uv run dxf-autoparam regen examples/two_cell_box_section.dxf --set OpenX1=4000 -o box_4000.dxf
uv run dxf-autoparam views my_sheet.dxf          # list the views on a sheet; then --view N or --region x0,y0,x1,y1
uv run dxf-autoparam bench                       # intent recovery on 17 independent structure families
uv run pytest -q                                 # 34 tests
```

How it works, results, limitations and the plan for aagento-bridge: **[docs/AUTO_PARAMETRIZATION.md](docs/AUTO_PARAMETRIZATION.md)**.

| Folder | |
|---|---|
| `src/dxf_autoparam/` | the generic engine (`analyse`, `build`, `regen`, `dxf_read`, `dxf_write`, `views`, `pipeline`), CLI, demo server |
| `src/dxf_autoparam/domains/` | optional semantic packs (`bridge.py`: site levels, names) — the only domain vocabulary |
| `examples/` | drawings to try (box sections, RCC box half-section GAD, girder deck, deck slab, pier, retaining wall, well, a 3-cell box drawn as loose lines) |
| `fixtures/library/` | 17 kernel families as DXF + their single-parameter ground-truth variants |
| `tools/` | fixture/example generators (`export_library_oracle.ts` reads the aagento kernel read-only) |

Regenerating the fixtures (only needed if the aagento kernel library changes):

```bash
../aagento-bridge/node_modules/.bin/esbuild tools/export_library_oracle.ts --bundle --platform=node --format=esm \
  --outfile=.cache/oracle.mjs --tsconfig=../aagento-bridge/tsconfig.json --log-level=warning
node .cache/oracle.mjs fixtures/library && uv run python tools/json_to_dxf.py fixtures/library && uv run python tools/make_examples.py
```
