# 173A — component inventory of the parametrization the run left (saved work, revision 338)

Measured on a copy of the saved work (`out/agent-logs/20261022-before-restart/`) by the engine — nothing taken from what the agent said.
Reproduce: `uv run python tools/component_inventory.py ~/Downloads/173A.dxf <copy> --domain bridge`. A part's dimensions are the DIMENSION entities
of the drawing whose measured lines carry the part next to the dimension (`coverage.py`): **driven** = a value somebody named changes it.

## Findings, with evidence

| # | Finding | Kind | Evidence |
|---|---|---|---|
| F1 | **The return walls in the longitudinal section are not parametrized.** 19 of the unit's dimensions measure them; 6 are driven, and only by `BarrelLength`, which moves them as a whole: none of their own sizes (stem, footing, toe, heel, depths, height 4680) is an input | unparametrized | coverage of U03_05: `ReturnWalls 6 / 19`, "named values on it: BarrelLength"; D369/D370 (4680) are `fixed` (`y12 = y11 + 4680.0` in the set-out) |
| F2 | **Why they could not be reached:** 29 of the 33 undriven dimensions of U03_05 measure gaps NO value sets — the set-out holds them as constant offsets (`x52 − 4000.0`, `x131 − 7150.0`, `x155 − 3925.0`, `y99 + 225`) once the agent's answer replaced the engine's generic values. Renaming cannot reach them, and the candidate list the agent read (`inspect_candidates`, 9 shown) never lists them | harness gap | `tools/sweep_sides.py`-era trace; `out/agent-logs/20261022-bridge-audit/undriven.py` |
| F3 | **The agent spent least on the unit that needed most**: 13 tool calls and one `define_parameters` batch on U03_05 (219 regions, 50 dimensions) against 35 on U01 (12 dimensions); nothing told it which dimensions were left | harness gap | events.jsonl of run R1: calls per open unit |
| F4 | **The C/S of the return wall (U02) is parametrized, but one size is named wrongly**: `ReturnWallTopWidth = 450` measures the stem where it meets the footing (D38 between x4 and x13 at the footing level); the stem's polyline is 300 wide at its top and 450 at its bottom (27540→27840 at y 65378; 27540→27990 at y 60948). Its top width (300) has no dimension and is not bound | incorrectly bound | `out/agent-logs/20261022-bridge-audit/check_u02.py`; production builds the same stem: top `rw_stem_top_thick` 0.300 + batter 0.150 = 0.450 (`rcc-box.constants.ts:26-28`) |
| F5 | **Nothing links the two drawings of the return wall**: U02 (C/S, 10 named values) and U03_05 (L-section) share no value; production draws both from one set of parameters | unlinked | `sm.shared` has no binding between U02 and U03_05 for any return-wall size; `rcc-box-longitudinal-view.ts:1497-1700` and `rcc-box-retaining-wall-view.ts:96-260` read the same `RW_PARAMS` |
| F6 | **"ToeWalls" in U03_05 are the two height gauges** (the drawing's label on their outline: "HEIGHT GAUGE (AS PER DWG. NO. RDSO/M-0001)"); its 4 dimensions are undriven | wrong part | the inventory's "the drawing labels it" column; INVESTIGATION_173A RC-8 |
| F7 | **The earth retainer in the L-section**: 13 dimensions, 5 driven (by `BarrelLength`), its own height 225 (D235) `fixed`; the earth retainer's own detail (U06) is parametrized 7 / 7 — again not linked | partial, unlinked | coverage of U03_05 and U06 |
| F8 | **The shear key** is parametrized in its detail (U07: `ShearKeyToeWidth` 225, `ShearKeySlopeRun` 450 — production's 0.225 and 0.675 − 0.225); its depth was refused by the validator; in the L-section the `ShearKey` part has no dimension | partial | audit-before.md (U07 "refused: ShearKeyDepth"); `rcc-box-shear-key-view.ts:173-211` |
| F9 | **The box's relations production writes are absent**: ClearHeight and BarrelLength are independent inputs in U03_05; production derives the barrel length from the formation widths and the earth cushion (`+ 4 × cushion`) and the clear height from the box height and the wearing course — the drawing's own slopes (2H:1V) carry the first | relation missing | `rcc-box-params.ts:375-444`; U03_05 `BarrelLength` source `ai` |
| F10 | **The drainage arrangement (U09)** has 6 parts and no named value (no dimension of its own is stated) | no dimension | inventory U09 |

## The inventory

| unit | part | type | the drawing labels it | library component | dimensions (driven / total) | status | named values on it |
|---|---|---|---|---|---|---|---|
| U01 | TopSlab | slab |  | box_barrel | 0 / 0 | no dimension |  |
| U01 | BottomSlab | slab |  | box_barrel | 0 / 0 | no dimension |  |
| U01 | SideWalls | wall | TOP SLAB; BOTTOM SLAB | box_barrel | 7 / 8 | partial | BottomSlabThickness, ClearHeight, ClearSpan, SideWallThickness, TopSlabThickness |
| U01 | Haunches | haunch |  | box_barrel | 0 / 0 | no dimension |  |
| U01 | ClearOpening | void |  |  | 1 / 1 | parametrized | ClearHeight |
| U01 | WearingCourse | wearing_course |  | deck_layers | 1 / 1 | parametrized | ClearHeight |
| U01 | PccBaseCourse | footing |  | deck_layers | 1 / 1 | parametrized | GranularFillingDepth |
| U01 | GranularFilling | fill | TOP SLAB | box_barrel | 4 / 5 | partial | ClearHeight, ClearSpan, ExistingFormationLevel, GranularFillingDepth, ProposedRoadLevel, S |
| U01 | BoulderBacking | drainage_layer |  |  | 0 / 0 | no dimension |  |
| U02 | ReturnWall | wing_wall |  | return_wall | 3 / 3 | parametrized | ReturnWallEmbedment, ReturnWallHeightAboveRoad, ReturnWallTopWidth |
| U02 | Foundation | footing |  |  | 5 / 5 | parametrized | FootingFrontProjection, FootingRearProjection, FootingToeThickness, ReturnWallTopWidth |
| U02 | PccBaseCourse | footing |  | deck_layers | 2 / 2 | parametrized | FootingToeThickness, ReturnWallEmbedment |
| U02 | BoulderBacking | drainage_layer |  |  | 0 / 0 | no dimension |  |
| U03_05 | TopSlab | top_slab | TOP SLAB | box_barrel | 3 / 6 | partial | BarrelLength, TopSlabThickness |
| U03_05 | BottomSlab | bottom_slab | BOTTOM SLAB | box_barrel | 2 / 6 | partial | BarrelLength, BottomSlabThickness |
| U03_05 | SideWalls | side_wall | SIDE WALL; SIDE WALL | box_barrel | 2 / 2 | parametrized | SideWallThickness |
| U03_05 | WearingCourse | wearing_course |  | deck_layers | 1 / 4 | partial | BarrelLength |
| U03_05 | GranularFilling | drainage_layer |  | deck_layers | 0 / 2 | unparametrized |  |
| U03_05 | ShearKey | shear_key |  | shear_key | 0 / 0 | no dimension |  |
| U03_05 | EarthRetainer | earth_retainer |  | earth_retainer | 5 / 13 | partial | BarrelLength |
| U03_05 | ReturnWalls | wing_wall | TOP OF WALL; TOP OF WALL | return_wall | 6 / 19 | partial | BarrelLength |
| U03_05 | ToeWalls | toe_wall | HEIGHT GAUGE (AS PER DWG. NO. RDSO/M-0001); HEIGHT GAUGE (AS | toe_wall | 0 / 4 | unparametrized |  |
| U03_05 | PccBaseCourse | footing |  | deck_layers | 2 / 2 | parametrized | BarrelLength |
| U04 | ToeWalls | substructure |  | toe_wall | 3 / 4 | partial | ToeWallEmbedment, ToeWallFoundationWidth, ToeWallHeightAboveRoad, ToeWallTopWidth |
| U04 | Foundation | substructure |  |  | 4 / 5 | partial | ToeWallEmbedment, ToeWallFoundationThickness, ToeWallFoundationWidth, ToeWallHeightAboveRo |
| U04 | PCCBaseCourse | foundation |  |  | 0 / 0 | no dimension |  |
| U04 | StonePitching | protection |  |  | 1 / 1 | parametrized | ToeWallHeightAboveRoad |
| U06 | EarthRetainer | superstructure |  | earth_retainer | 7 / 7 | parametrized | EarthRetainerHeight, EarthRetainerTopWidth, TopSlabThickness |
| U07 | WearingCourse | wearing_course |  | deck_layers | 2 / 2 | parametrized | BottomSlabThickness, GranularFillingDepth, PccBaseCourseThickness, WearingCourseThickness |
| U07 | ShearKey | shear_key |  | shear_key | 2 / 2 | parametrized | BottomSlabThickness, GranularFillingDepth, PccBaseCourseThickness |
| U07 | PccBaseCourse | pcc_base_course |  | deck_layers | 5 / 5 | parametrized | BottomSlabThickness, GranularFillingDepth, PccBaseCourseThickness, ShearKeySlopeRun, Shear |
| U07 | GranularFilling | granular_filling |  | deck_layers | 4 / 4 | parametrized | BottomSlabThickness, GranularFillingDepth, PccBaseCourseThickness, ShearKeySlopeRun, Shear |
| U08 | Sump1 | structure | COVER FOR INSPECTION |  | 1 / 1 | parametrized | Sump1Depth |
| U08 | Sump2 | structure |  |  | 1 / 1 | parametrized | Sump2Depth |
| U08 | SoakPit | structure |  |  | 2 / 2 | parametrized | FilterLayerDepth1, FilterLayerDepth2 |
| U08 | DischargePipe | structure |  |  | 0 / 0 | no dimension |  |
| U09 | Sump1 | structure |  |  | 0 / 0 | no dimension |  |
| U09 | Sump2 | structure | COLLECTION TANK-2 AT GL (1MX1M) |  | 0 / 0 | no dimension |  |
| U09 | SoakPit | structure |  |  | 0 / 0 | no dimension |  |
| U09 | InspectionChamber | structure |  |  | 0 / 0 | no dimension |  |
| U09 | DischargePipeNaturalDrain | structure |  |  | 0 / 0 | no dimension |  |
| U09 | PumpingPipe | structure |  |  | 0 / 0 | no dimension |  |

Parts: parametrized 17, partial 9, unparametrized 2, no dimension 14

Dimensions on no part:
- U03_05: 6 dimension(s) nothing named drives on no part — D48 600, D49 58.7, D86 2000, D118 600, D119 58.7, D156 2000

Sheet: 55 of 95 dimensions are driven by a named value (`coverage.sheet_coverage`); U03_05 13 of 50.
