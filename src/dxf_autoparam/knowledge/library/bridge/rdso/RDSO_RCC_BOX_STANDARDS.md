# RDSO RCC Box Standards Knowledge Sheet (five standards)

Built 2026-10-23T17:27:31Z by `tools/build_rdso_sheet.py` from the page extracts (read by eye from the RDSO PDFs; no OCR). Scope: RDSO/B-10151/R, RDSO/B-10152/R, RDSO/B-10153, RDSO/B-10155, RDSO/B-10157 series as extracted in Aagento-GAD-Foundation-Model; nothing else.

## How to read it

- **explicit**: Printed on the RDSO sheet and read from a displayed image of it (verification level says whether it was re-checked).
- **derived**: Follows mathematically from printed notations or tables (the derivation is written out); not printed as such.
- **unverified**: Printed, but the extraction marks it unclear, or it is on a page the extraction did not check, or the extraction says not to use it.
- **implementation**: A rule of an existing implementation (aagento-bridge production code, this template): not RDSO content; recorded in the template.
- **engineer**: A design choice an engineer makes and can change: not RDSO content; recorded in the template and in each bridge's config.

- A schedule value applies only to its own standard, fill height and span x height configuration; the five standards are NOT interchangeable (loading, track, construction and curvature differ: see each configuration).
- No interpolation: the sheets give discrete configurations. The notes allow the IMMEDIATELY HIGHER span/height configuration for intermediate spans/heights (the note is cited per standard). For an intermediate FILL height the sheets say nothing: taking the next higher tabulated fill is an engineer's choice, recorded as such by the template.
- RDSO guides geometry and validation; it never overrides an engineer's explicit input. A difference is reported with both values.
- Values marked unverified are shown but never used to pass or fail a check.

## The five standards at a glance

| Standard | Structure | Track | Loading | Fill heights tabulated (m) | Configurations | Extraction status |
|---|---|---|---|---|---|---|
| RDSO/B-10151/R | single-cell RCC box culvert | single line | DFC loading (32.5 t axle load) | 0, 1, 2, 3, 4, 5, 6, 8, 10 | up to 36 per sheet | p1 general arrangement (view level); p2 spot check of columns 2mX1.8m and 2mX2.0m and rows a1 and b (match); p3 to p10 schedules not checked |
| RDSO/B-10152/R | single-cell RCC box culvert | single line | 25t loading - 2008 | 0, 1, 2, 3, 4, 5, 6, 8, 10 | up to 36 per sheet | p1 general arrangement (view level; haunch table and callout checked earlier); p9 spot check of column 2mX1.8m (match); p2 to p8 and p10 schedules not checked |
| RDSO/B-10153 | segmental (pre-cast) RCC box culvert for limited height subway (LHS) | single or multiple lines (limited height subway) | 25t loading - 2008 | 0, 0.5, 1 | up to 6 per sheet | p1 general arrangement (view level); p2 to p6 schedules not checked; open: span height differs between p3 and p4; Table X row 3 unresolved |
| RDSO/B-10155 | single-cell RCC box culvert | double line | 25t loading - 2008 | 0, 1, 2, 3, 4, 5, 6 | up to 36 per sheet | p1 general arrangement (view level); p2 to p6 schedules verified cell by cell in a second pass (corrections applied); partly done: 2 of 5 pages saved, nothing checked; p1 row h digit clipped for 6mX4.0m and 6mX5.0m; p2 only column 2mX1.8m read |
| RDSO/B-10157 | single-cell RCC box culvert | double line | DFC loading (32.5 t axle load) | 0, 1, 2, 3, 4, 5 | up to 36 per sheet | p1 general arrangement (view level); p4 spot check of column 2mX1.8m (match); p2, p3, p5, p6 schedules not checked; partly done: page 1 values were never read from a displayed image; the extraction says: do not use page 1 until re-read |

## RDSO/B-10151/R (RDSO-RCC-BOX-10151)

Source: 10151R SERIES.pdf. Title: STANDARD DRAWING OF SINGLE BOX CULVERT (GENERAL ARRANGEMENT) DFC LOADING (32.5t AXLE LOAD). Date: 27.7.2016 (PROVISIONAL).

### Applicability (as printed)

- **structure**: single-cell RCC box culvert  (title)
- **track**: single line  (note 2)
- **loading**: DFC loading (32.5 t axle load)  (title)
- **curvature**:  — THIS DRAWING IS SUITABLE FOR SINGLE TRACK ONLY. (printed 'TRACK ONLY.' struck through in red; red 'LINE STRAIGHT TRACK ONLY.' added; ALT 3) (note 2)
- **skew**: no skew angle considered in the design — NO SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN. (red, added by ALT 3) (note 23)
- **ballast_cushion_mm**: 350.0 — BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN. (note 20)
- **clear_cover_mm**: 50.0 — CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm. (note 11)
- **config_label_meaning**:   (not stated on the sheets read)
- **intermediate_configuration_rule**:  — FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED. (note 18)
- **barrel_length_rule**:  — i) BARREL LENGTH OF BOX CULVERT SHOULD BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL, DESIGNED SUITABLY. (note 13)
- **concrete_grade_rule**:  — M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER. (note 16)

### Sheets

| Drawing | Page | Kind | Fill (m) | Verification | Usable |
|---|---|---|---|---|---|
| RDSO/B-10151/R | 1 (10151R SERIES.pdf) | general arrangement | - | checked against the displayed drawing | yes |
| RDSO/B-10151/1R | 2 (10151R SERIES.pdf) | structural design details | 0.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/2R | 3 (10151R SERIES.pdf) | structural design details | 1.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/3R | 4 (10151R SERIES.pdf) | structural design details | 2.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/4R | 5 (10151R SERIES.pdf) | structural design details | 3.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/5R | 6 (10151R SERIES.pdf) | structural design details | 4.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/6R | 7 (10151R SERIES.pdf) | structural design details | 5.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/7R | 8 (10151R SERIES.pdf) | structural design details | 6.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/8R | 9 (10151R SERIES.pdf) | structural design details | 8.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10151/9R | 10 (10151R SERIES.pdf) | structural design details | 10.0 | transcribed by eye from displayed tiles; not re-checked | yes |

### Haunch B x B (by CLS or cht)

| From (m) | To (m) | Size (mm) | Printed |
|---|---|---|---|
| - | 3.0 | 200 | LESS THAN 3 m -> 200 X200 mm |
| 3.0 | 3.5 | 300 | >= 3.0 m and < 3.5m -> 300 X300 mm |
| 3.5 | 4.0 | 350 | >= 3.5 m and < 4.0m -> 350 X350 mm |
| 4.0 | 4.5 | 400 | >= 4.0 m and < 4.5m -> 400X400 mm |
| 4.5 | 5.0 | 450 | >= 4.5 m and < 5.0m -> 450 X450 mm |
| 5.0 | 5.5 | 500 | >= 5.0 m and < 5.5m -> 500 X500 mm |
| 5.5 | 6.0 | 550 | >= 5.5 m and < 6.0m -> 550 X550 mm |
| 6.0 | - | 600 | >= 6.0m -> 600 X600 mm |

### Depth of key DK at bottom slab

- UPTO 900mm -> 1200mm
- GREATER THAN 900mm -> tsb + 300mm

### Relations from the notations (derived)

- `RDSO-RCC-BOX-10151:ht`: ht = cht + wearing course thickness (ht is the height of box including wearing course; cht the clear height above the wearing course)
- `RDSO-RCC-BOX-10151:tht`: tht = ht + tst + tsb
- `RDSO-RCC-BOX-10151:ols`: OLS = CLS + 2 x tsv (single cell)
- `RDSO-RCC-BOX-10151:tbl`: TBL = UBL + DBL

### Notes (verbatim, general arrangement)

1. ALL DIMENSIONS ARE IN MILLIMETER UNLESS OTHERWISE SPECIFIED.
2. THIS DRAWING IS SUITABLE FOR SINGLE TRACK ONLY. (printed 'TRACK ONLY.' struck through in red; red 'LINE STRAIGHT TRACK ONLY.' added; ALT 3)
3. PREPARATION OF BED BELOW 150MM THICK BASE COURSE SHOULD BE BASED ON ACTUAL SITE CONDITION IN ORDER TO ACHIEVE THE ADEQUATE BEARING CAPACITY REQUIRED TO WITHSTAND THE FOUNDATION PRESSURE GIVEN IN REFERRED DRAWINGS IN TABLE 'X'.
4. REINFORCEMENT DETAILS, SLAB THICKNESS DETAILS AND FOUNDATION PRESSURE FOR VARIOUS FILL HEIGHTS HAVE BEEN GIVEN IN REFERRED DRAWINGS AS GIVEN IN TABLE 'X'. THICKNESSES OF TOP SLAB, BOTTOM SLAB AND VERTICAL WALLS HAVE BEEN KEPT UNIFORM.
5. THIS DESIGN IS SUITABLE FOR DFC LOADING(32.5t AXLE LOAD).
6. ALL REINFORCEMENT STEEL SHALL BE OF HIGH STRENGTH DEFORMED (HSD)/TMT BARS, Fe415 AND HIGHER GRADE REINFORCEMENT CONFORMING TO IS:1786-2008. FOR SEISMIC ZONES III, IV AND V HYSD STEEL BARS HAVING MINIMUM ELONGATION OF 14.5 PERCENT AND CONFORMING TO OTHER REQUIREMENTS OF IS:1786 SHALL BE USED.
7. DESIGN CRITERIA IS BASED ON FOLLOWING IRS CODES: i) IRS BRIDGE RULES ii) IRS CONCRETE BRIDGE CODE iii) IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE
8. LAPPING OF BARS SHOULD BE MINIMISED AND STAGGERED WHEREVER NECESSARY. MINIMUM LENGTH OF LAP SHALL BE AS GIVEN IN IRS CONCRETE BRIDGE CODE FOR TOR STEEL.
9. BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE. (printed text struck through in red; the ALT 2 remark restores it: 'NOTE NO. 9 IS RESTORED AND ALTERATION IN CROSS SECTION OF R.C.C BOX'; the restoration in red reads 'BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE.')
10. ALL RCC SURFACES COMING IN CONTACT WITH SOIL SHOULD BE PAINTED WITH BITUMEN OR COALTAR OF APPROVED QUALITY @ 1.464 KG/SQM.
11. CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm.
12. SCHEMATIC WING WALL AND RETURN WALL ARE GIVEN. HOWEVER, WING WALL AND RETURN WALL SHOULD BE DESIGNED SUITABLY BY ZONAL RAILWAYS AS PER SITE CONDITIONS.
13. i) BARREL LENGTH OF BOX CULVERT SHOULD BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL, DESIGNED SUITABLY.
14. IN CASE OF ERODIBLE SOILS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS). SCHEMATIC CURTAIN/DROP WALL IS GIVEN.
15. TOLERANCE SHALL BE FOLLOWED AS PER IRS CONCRETE BRIDGE CODE.
16. M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER.
17. BED SLOPE SHALL BE ADJUSTED AS PER SITE CONDITIONS BY COMPETENT AUTHORITY.
18. FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED.
19. WEEP HOLES SHALL BE OF 75/100 DIA PVC/AC PIPES STAGGERED @ 1000 C/C ABOVE LOW WATER LEVEL IN BOTH WING WALL/RETURN WALL AND EARTH RETAINER OF BOX.
20. BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN.
21. DEPTH OF KEY AT BOTTOM SLAB, DK SHOULD BE PROVIDED AS GIVEN BELOW: (table: UPTO 900mm -> 1200mm; GREATER THAN 900mm -> tsb + 300mm)
22. THIS DRAWING SUPERSEDES DRAWING NO. RDSO/B-10151.
23. NO SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN. (red, added by ALT 3)

### Design basis (as printed)

- **Loading**: DFC LOADING (32.5t AXLE LOAD) (title block; note 5)
- **Concrete grade**: M-35 for span or height >= 4 m; M-30 for span or height < 4 m (note 16)
- **Steel grade**: HSD/TMT bars, Fe415 and higher, IS:1786-2008; seismic zones III, IV, V: minimum elongation 14.5 percent (note 6)
- **Clear cover**: 50mm (note 11)
- **Ballast cushion**: 350mm (note 20)
- **Base course**: 150mm TH. PCC BASE COURSE (sectional elevation; cross section; typical details)
- **Wearing course**: 150mm TH. WEARING COURSE (sectional elevation; cross section)
- **Bed slope**: 1 IN 100 (MIN.) (sectional elevation; note 17)
- **Embankment slope**: SLOPE 2:1 (sectional elevation)
- **Side slope at box**: SLOPE NOT STEEPER THAN 1:1 (cross section)
- **Stone pitching**: 300 TH. with cement grouting (sectional elevation)
- **Weep holes**: 75/100 DIA PVC/AC pipes @ 1000 c/c above low water level (typical details; note 19)
- **Haunch size**: 200X200 to 600X600 mm by CLS or cht (table) (TABLE FOR B X B HAUNCH)
- **Key depth DK**: UPTO 900mm: 1200mm; GREATER THAN 900mm: tsb + 300mm (note 21)
- **Fill heights in table X**: 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0 m (TABLE-'X' REFERENCE DRAWINGS)
- **Distributors**: 10mm DIA @ 300mm c/c MAXIMUM (typical details)

### Schedule RDSO/B-10151/1R — fill 0.0 m (page 2, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 115.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 118.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 124.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 132.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 139.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 147.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 98.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 100.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 106.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 113.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 119.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 126.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 136.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 143.0 | explicit | Mark c, 3mX5.0m column: first draft read 20mm DIA; the zoomed re-read z01_b2_45_50 and the displayed tile confirm 16mm DIA @ 200mm, which is transcribed. |
| 3mX6m | 500.0 | 500.0 | 500.0 | 163.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 97.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 103.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 109.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 118.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 124.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 131.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 137.0 | explicit |  |
| 4mX6m | 500.0 | 500.0 | 500.0 | 154.0 | explicit |  |
| 5mX2.5m | 500.0 | 500.0 | 500.0 | 106.0 | explicit |  |
| 5mX3m | 500.0 | 500.0 | 500.0 | 112.0 | explicit |  |
| 5mX3.5m | 500.0 | 500.0 | 500.0 | 119.0 | explicit |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 125.0 | explicit |  |
| 5mX4.5m | 500.0 | 500.0 | 500.0 | 131.0 | explicit |  |
| 5mX5m | 500.0 | 500.0 | 500.0 | 137.0 | explicit |  |
| 5mX6m | 550.0 | 550.0 | 550.0 | 153.0 | explicit |  |
| 6mX3m | 550.0 | 550.0 | 550.0 | 113.0 | explicit |  |
| 6mX3.5m | 550.0 | 550.0 | 550.0 | 119.0 | explicit |  |
| 6mX4m | 550.0 | 550.0 | 550.0 | 125.0 | explicit |  |
| 6mX4.5m | 550.0 | 550.0 | 550.0 | 131.0 | explicit |  |
| 6mX5m | 600.0 | 600.0 | 600.0 | 140.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 155.0 | explicit |  |

### Schedule RDSO/B-10151/2R — fill 1.0 m (page 3, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 102.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 103.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 109.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 116.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 124.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 131.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 91.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 93.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 99.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 105.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 112.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 119.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 129.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 136.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 157.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 92.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 98.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 104.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 113.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 120.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 126.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 133.0 | explicit |  |
| 4mX6m | 500.0 | 500.0 | 500.0 | 150.0 | explicit |  |
| 5mX2.5m | 500.0 | 500.0 | 500.0 | 103.0 | explicit |  |
| 5mX3m | 500.0 | 500.0 | 500.0 | 109.0 | explicit |  |
| 5mX3.5m | 500.0 | 500.0 | 500.0 | 115.0 | explicit |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 121.0 | explicit |  |
| 5mX4.5m | 500.0 | 500.0 | 500.0 | 127.0 | explicit |  |
| 5mX5m | 500.0 | 500.0 | 500.0 | 134.0 | explicit |  |
| 5mX6m | 550.0 | 550.0 | 550.0 | 150.0 | explicit |  |
| 6mX3m | 550.0 | 550.0 | 550.0 | 111.0 | explicit |  |
| 6mX3.5m | 550.0 | 550.0 | 550.0 | 117.0 | explicit |  |
| 6mX4m | 550.0 | 550.0 | 550.0 | 123.0 | explicit |  |
| 6mX4.5m | 550.0 | 550.0 | 550.0 | 129.0 | explicit |  |
| 6mX5m | 600.0 | 600.0 | 600.0 | 138.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 154.0 | explicit |  |

### Schedule RDSO/B-10151/3R — fill 2.0 m (page 4, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 113.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 115.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 119.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 125.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 130.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 137.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 104.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 106.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 111.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 115.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 121.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 128.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 138.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 148.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 167.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 105.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 110.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 115.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 124.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 130.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 137.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 143.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 164.0 | explicit |  |
| 5mX2.5m | 500.0 | 500.0 | 500.0 | 114.0 | explicit |  |
| 5mX3m | 500.0 | 500.0 | 500.0 | 119.0 | explicit |  |
| 5mX3.5m | 500.0 | 500.0 | 500.0 | 126.0 | explicit |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 132.0 | explicit |  |
| 5mX4.5m | 500.0 | 500.0 | 500.0 | 138.0 | explicit |  |
| 5mX5m | 500.0 | 500.0 | 500.0 | 144.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 164.0 | explicit |  |
| 6mX3m | 600.0 | 600.0 | 600.0 | 124.0 | explicit |  |
| 6mX3.5m | 600.0 | 600.0 | 600.0 | 130.0 | explicit |  |
| 6mX4m | 600.0 | 600.0 | 600.0 | 137.0 | explicit |  |
| 6mX4.5m | 600.0 | 600.0 | 600.0 | 143.0 | explicit |  |
| 6mX5m | 600.0 | 600.0 | 600.0 | 149.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 164.0 | explicit |  |

### Schedule RDSO/B-10151/4R — fill 3.0 m (page 5, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 126.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 128.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 133.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 139.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 145.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 151.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 119.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 121.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 126.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 131.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 136.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 148.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 155.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 162.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 184.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 121.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 128.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 133.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 139.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 144.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 150.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 161.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 178.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 132.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 138.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 143.0 | explicit |  |
| 5mX4m | 550.0 | 550.0 | 550.0 | 149.0 | explicit |  |
| 5mX4.5m | 550.0 | 550.0 | 550.0 | 155.0 | explicit |  |
| 5mX5m | 550.0 | 550.0 | 550.0 | 161.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 178.0 | explicit |  |
| 6mX3m | 650.0 | 650.0 | 650.0 | 142.0 | explicit |  |
| 6mX3.5m | 650.0 | 650.0 | 650.0 | 148.0 | explicit |  |
| 6mX4m | 650.0 | 650.0 | 650.0 | 154.0 | explicit |  |
| 6mX4.5m | 650.0 | 650.0 | 650.0 | 160.0 | explicit |  |
| 6mX5m | 650.0 | 650.0 | 650.0 | 166.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 179.0 | explicit |  |

### Schedule RDSO/B-10151/5R — fill 4.0 m (page 6, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 141.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 143.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 149.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 155.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 161.0 | explicit |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 171.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 135.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 137.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 142.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 147.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 156.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 165.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 172.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 179.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 140.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 145.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 150.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 156.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 162.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 171.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 177.0 | explicit |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 198.0 | explicit |  |
| 5mX2.5m | 600.0 | 600.0 | 600.0 | 152.0 | explicit |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 158.0 | explicit |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 163.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 169.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 175.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 181.0 | explicit |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 197.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 162.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 168.0 | explicit |  |
| 6mX4m | 700.0 | 700.0 | 700.0 | 174.0 | explicit |  |
| 6mX4.5m | 700.0 | 700.0 | 700.0 | 179.0 | explicit |  |
| 6mX5m | 700.0 | 700.0 | 700.0 | 185.0 | explicit |  |
| 6mX6m | 700.0 | 700.0 | 700.0 | 198.0 | explicit |  |

### Schedule RDSO/B-10151/6R — fill 5.0 m (page 7, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 158.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 160.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 166.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 172.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 179.0 | explicit |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 188.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 155.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 157.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 162.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 168.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 174.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 183.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 3mX5m | 500.0 | 500.0 | 500.0 | 200.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 218.0 | explicit |  |
| 4mX2m | 500.0 | 500.0 | 500.0 | 160.0 | explicit |  |
| 4mX2.5m | 500.0 | 500.0 | 500.0 | 166.0 | explicit |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 171.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 177.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 183.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 189.0 | explicit |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 199.0 | explicit |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 216.0 | explicit |  |
| 5mX2.5m | 650.0 | 650.0 | 650.0 | 173.0 | explicit |  |
| 5mX3m | 650.0 | 650.0 | 650.0 | 179.0 | explicit |  |
| 5mX3.5m | 650.0 | 650.0 | 650.0 | 184.0 | explicit |  |
| 5mX4m | 650.0 | 650.0 | 650.0 | 190.0 | explicit |  |
| 5mX4.5m | 650.0 | 650.0 | 650.0 | 196.0 | explicit |  |
| 5mX5m | 650.0 | 650.0 | 650.0 | 202.0 | explicit |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 215.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 180.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 186.0 | explicit |  |
| 6mX4m | 700.0 | 700.0 | 700.0 | 192.0 | explicit |  |
| 6mX4.5m | 700.0 | 700.0 | 700.0 | 198.0 | explicit |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 207.0 | explicit |  |
| 6mX6m | 800.0 | 800.0 | 800.0 | 222.0 | explicit |  |

### Schedule RDSO/B-10151/7R — fill 6.0 m (page 8, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 176.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 178.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 183.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 190.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 196.0 | explicit |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 206.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 172.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 174.0 | explicit |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 183.0 | explicit |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 189.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 195.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 202.0 | explicit |  |
| 3mX4.5m | 500.0 | 500.0 | 500.0 | 212.0 | explicit |  |
| 3mX5m | 500.0 | 500.0 | 500.0 | 218.0 | explicit |  |
| 3mX6m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 4mX2m | 500.0 | 500.0 | 500.0 | 178.0 | explicit |  |
| 4mX2.5m | 500.0 | 500.0 | 500.0 | 184.0 | explicit |  |
| 4mX3m | 550.0 | 550.0 | 550.0 | 192.0 | explicit |  |
| 4mX3.5m | 550.0 | 550.0 | 550.0 | 198.0 | explicit |  |
| 4mX4m | 550.0 | 550.0 | 550.0 | 204.0 | explicit |  |
| 4mX4.5m | 550.0 | 550.0 | 550.0 | 211.0 | explicit |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 217.0 | explicit |  |
| 4mX6m | 650.0 | 650.0 | 650.0 | 237.0 | explicit |  |
| 5mX2.5m | 650.0 | 650.0 | 650.0 | 191.0 | explicit |  |
| 5mX3m | 650.0 | 650.0 | 650.0 | 197.0 | explicit |  |
| 5mX3.5m | 700.0 | 700.0 | 700.0 | 205.0 | explicit |  |
| 5mX4m | 700.0 | 700.0 | 700.0 | 212.0 | explicit |  |
| 5mX4.5m | 700.0 | 700.0 | 700.0 | 218.0 | explicit |  |
| 5mX5m | 700.0 | 700.0 | 700.0 | 224.0 | explicit |  |
| 5mX6m | 700.0 | 700.0 | 700.0 | 237.0 | explicit |  |
| 6mX3m | 750.0 | 750.0 | 750.0 | 201.0 | explicit |  |
| 6mX3.5m | 800.0 | 800.0 | 800.0 | 210.0 | explicit |  |
| 6mX4m | 800.0 | 800.0 | 800.0 | 216.0 | explicit |  |
| 6mX4.5m | 800.0 | 800.0 | 800.0 | 222.0 | explicit |  |
| 6mX5m | 800.0 | 800.0 | 800.0 | 228.0 | explicit |  |
| 6mX6m | 800.0 | 800.0 | 800.0 | 240.0 | explicit |  |

### Schedule RDSO/B-10151/8R — fill 8.0 m (page 9, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 211.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 213.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 219.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 226.0 | explicit |  |
| 2mX3.5m | 450.0 | 450.0 | 450.0 | 238.0 | explicit |  |
| 2mX4m | 450.0 | 450.0 | 450.0 | 246.0 | explicit |  |
| 3mX1.8m | 450.0 | 450.0 | 450.0 | 210.0 | explicit |  |
| 3mX2m | 450.0 | 450.0 | 450.0 | 213.0 | explicit |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 219.0 | explicit |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 225.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 231.0 | explicit |  |
| 3mX4m | 500.0 | 500.0 | 500.0 | 241.0 | explicit |  |
| 3mX4.5m | 500.0 | 500.0 | 500.0 | 248.0 | explicit |  |
| 3mX5m | 550.0 | 550.0 | 550.0 | 258.0 | explicit |  |
| 3mX6m | 650.0 | 650.0 | 650.0 | 280.0 | explicit |  |
| 4mX2m | 550.0 | 550.0 | 550.0 | 216.0 | explicit |  |
| 4mX2.5m | 550.0 | 550.0 | 550.0 | 222.0 | explicit |  |
| 4mX3m | 600.0 | 600.0 | 600.0 | 231.0 | explicit |  |
| 4mX3.5m | 600.0 | 600.0 | 600.0 | 237.0 | explicit |  |
| 4mX4m | 600.0 | 600.0 | 600.0 | 244.0 | explicit |  |
| 4mX4.5m | 600.0 | 600.0 | 600.0 | 250.0 | explicit |  |
| 4mX5m | 600.0 | 600.0 | 600.0 | 257.0 | explicit |  |
| 4mX6m | 700.0 | 700.0 | 700.0 | 278.0 | explicit |  |
| 5mX2.5m | 750.0 | 750.0 | 750.0 | 232.0 | explicit |  |
| 5mX3m | 750.0 | 750.0 | 750.0 | 239.0 | explicit |  |
| 5mX3.5m | 750.0 | 750.0 | 750.0 | 245.0 | explicit |  |
| 5mX4m | 750.0 | 750.0 | 750.0 | 251.0 | explicit |  |
| 5mX4.5m | 750.0 | 750.0 | 750.0 | 257.0 | explicit |  |
| 5mX5m | 750.0 | 750.0 | 750.0 | 264.0 | explicit |  |
| 5mX6m | 750.0 | 750.0 | 750.0 | 277.0 | explicit |  |
| 6mX3m | 850.0 | 850.0 | 850.0 | 243.0 | explicit |  |
| 6mX3.5m | 900.0 | 900.0 | 900.0 | 252.0 | explicit |  |
| 6mX4m | 900.0 | 900.0 | 900.0 | 258.0 | explicit |  |
| 6mX4.5m | 900.0 | 900.0 | 900.0 | 264.0 | explicit |  |
| 6mX5m | 900.0 | 900.0 | 900.0 | 271.0 | explicit |  |
| 6mX6m | 900.0 | 900.0 | 900.0 | 284.0 | explicit |  |

### Schedule RDSO/B-10151/9R — fill 10.0 m (page 10, 10151R SERIES.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 246.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 248.0 | explicit |  |
| 2mX2.5m | 400.0 | 400.0 | 400.0 | 257.0 | explicit |  |
| 2mX3m | 450.0 | 450.0 | 450.0 | 267.0 | explicit |  |
| 2mX3.5m | 500.0 | 500.0 | 500.0 | 278.0 | explicit |  |
| 2mX4m | 550.0 | 550.0 | 550.0 | 288.0 | explicit |  |
| 3mX1.8m | 500.0 | 500.0 | 500.0 | 249.0 | explicit |  |
| 3mX2m | 500.0 | 500.0 | 500.0 | 252.0 | explicit |  |
| 3mX2.5m | 500.0 | 500.0 | 500.0 | 258.0 | explicit |  |
| 3mX3m | 500.0 | 500.0 | 500.0 | 264.0 | explicit |  |
| 3mX3.5m | 550.0 | 550.0 | 550.0 | 274.0 | explicit |  |
| 3mX4m | 600.0 | 600.0 | 600.0 | 284.0 | explicit |  |
| 3mX4.5m | 600.0 | 600.0 | 600.0 | 291.0 | explicit |  |
| 3mX5m | 700.0 | 700.0 | 700.0 | 305.0 | explicit |  |
| 3mX6m | 800.0 | 800.0 | 800.0 | 328.0 | explicit |  |
| 4mX2m | 650.0 | 650.0 | 650.0 | 258.0 | explicit |  |
| 4mX2.5m | 650.0 | 650.0 | 650.0 | 264.0 | explicit |  |
| 4mX3m | 650.0 | 650.0 | 650.0 | 271.0 | explicit |  |
| 4mX3.5m | 700.0 | 700.0 | 700.0 | 280.0 | explicit |  |
| 4mX4m | 700.0 | 700.0 | 700.0 | 287.0 | explicit |  |
| 4mX4.5m | 700.0 | 700.0 | 700.0 | 293.0 | explicit |  |
| 4mX5m | 750.0 | 750.0 | 750.0 | 304.0 | explicit |  |
| 4mX6m | 850.0 | 850.0 | 850.0 | 325.0 | explicit |  |
| 5mX2.5m | 800.0 | 800.0 | 800.0 | 272.0 | explicit |  |
| 5mX3m | 800.0 | 800.0 | 800.0 | 278.0 | explicit |  |
| 5mX3.5m | 800.0 | 800.0 | 800.0 | 284.0 | explicit |  |
| 5mX4m | 850.0 | 850.0 | 850.0 | 294.0 | explicit |  |
| 5mX4.5m | 850.0 | 850.0 | 850.0 | 300.0 | explicit |  |
| 5mX5m | 850.0 | 850.0 | 850.0 | 307.0 | explicit |  |
| 5mX6m | 900.0 | 900.0 | 900.0 | 324.0 | explicit |  |
| 6mX3m | 900.0 | 900.0 | 900.0 | 282.0 | explicit |  |
| 6mX3.5m | 900.0 | 900.0 | 900.0 | 289.0 | explicit |  |
| 6mX4m | 900.0 | 900.0 | 900.0 | 295.0 | explicit |  |
| 6mX4.5m | 900.0 | 900.0 | 900.0 | 301.0 | explicit |  |
| 6mX5m | 900.0 | 900.0 | 900.0 | 308.0 | explicit |  |
| 6mX6m | 1000.0 | 1000.0 | 1000.0 | 327.0 | explicit |  |

Unclear items recorded by the extraction: 20; not-read items: 14 (full list in the JSON).

## RDSO/B-10152/R (RDSO-RCC-BOX-10152-R-SERIES)

Source: 10152-R series.pdf. Title: STANDARD DRAWING OF SINGLE BOX CULVERT (GENERAL ARRANGEMENT) 25t LOADING - 2008. Date: DATE: 4.8.2015 (PROVISIONAL).

### Applicability (as printed)

- **structure**: single-cell RCC box culvert  (title)
- **track**: single line  (note 2)
- **loading**: 25t loading - 2008  (title)
- **curvature**:  — THIS DRAWING IS SUITABLE FOR SINGLE TRACK ONLY. [TRACK ONLY struck through in black]  Red alteration ALT. 3 added: LINE STRAIGHT TRACK ONLY. (note 2)
- **skew**: no skew angle considered in the design — No SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN. [red, added by ALT. 3] (note 23)
- **ballast_cushion_mm**: 350.0 — BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN. (note 20)
- **clear_cover_mm**: 50.0 — CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm. (note 11)
- **config_label_meaning**:   (not stated on the sheets read)
- **intermediate_configuration_rule**:  — FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED. (note 18)
- **barrel_length_rule**:  — i). BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii). IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL, DESIGNED SUITABLY. (note 13)
- **concrete_grade_rule**:  — M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER. (note 16)

### Sheets

| Drawing | Page | Kind | Fill (m) | Verification | Usable |
|---|---|---|---|---|---|
| RDSO/B-10152/R | 1 (10152-R series.pdf) | general arrangement | - | checked against the displayed drawing | yes |
| RDSO/B-10152/1R | 2 (10152-R series.pdf) | structural design details | 0.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/2R | 3 (10152-R series.pdf) | structural design details | 1.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/3R | 4 (10152-R series.pdf) | structural design details | 2.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/4R | 5 (10152-R series.pdf) | structural design details | 3.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/5R | 6 (10152-R series.pdf) | structural design details | 4.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/6R | 7 (10152-R series.pdf) | structural design details | 5.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/7R | 8 (10152-R series.pdf) | structural design details | 6.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/8R | 9 (10152-R series.pdf) | structural design details | 8.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10152/9R | 10 (10152-R series.pdf) | structural design details | 10.0 | transcribed by eye from displayed tiles; not re-checked | yes |

### Haunch B x B (by CLS or cht)

| From (m) | To (m) | Size (mm) | Printed |
|---|---|---|---|
| - | 3.0 | 200 | LESS THAN 3 m -> 200 X200 mm |
| 3.0 | 3.5 | 300 | ≥ 3.0 m and <3.5m -> 300 X300 mm |
| 3.5 | 4.0 | 350 | ≥ 3.5 m and <4.0m -> 350 X350 mm |
| 4.0 | 4.5 | 400 | ≥ 4.0 m and <4.5m -> 400X400 mm |
| 4.5 | 5.0 | 450 | ≥ 4.5 m and <5.0m -> 450 X450 mm |
| 5.0 | 5.5 | 500 | ≥ 5.0 m and <5.5m -> 500 X500 mm |
| 5.5 | 6.0 | 550 | ≥ 5.5 m and <6.0m -> 550 X550 mm |
| 6.0 | - | 600 | ≥ 6.0m -> 600 X600 mm |

### Depth of key DK at bottom slab

- UPTO 900mm -> 1200mm
- GREATER THAN 900mm -> tsb + 300mm

### Relations from the notations (derived)

- `RDSO-RCC-BOX-10152-R-SERIES:ht`: ht = cht + wearing course thickness (ht is the height of box including wearing course; cht the clear height above the wearing course)
- `RDSO-RCC-BOX-10152-R-SERIES:tht`: tht = ht + tst + tsb
- `RDSO-RCC-BOX-10152-R-SERIES:ols`: OLS = CLS + 2 x tsv (single cell)
- `RDSO-RCC-BOX-10152-R-SERIES:tbl`: TBL = UBL + DBL

### Notes (verbatim, general arrangement)

1. ALL DIMENSIONS ARE IN MILLIMETER UNLESS OTHERWISE SPECIFIED.
2. THIS DRAWING IS SUITABLE FOR SINGLE TRACK ONLY. [TRACK ONLY struck through in black]  Red alteration ALT. 3 added: LINE STRAIGHT TRACK ONLY.
3. PREPARATION OF BED BELOW 150mm THICK BASE COURSE SHOULD BE BASED ON ACTUAL SITE CONDITION IN ORDER TO ACHIEVE THE ADEQUATE BEARING CAPACITY REQUIRED TO WITHSTAND THE FOUNDATION PRESSURE GIVEN IN REFERRED DRAWINGS IN TABLE 'X'.
4. REINFORCEMENT DETAILS, SLAB THICKNESS DETAILS AND FOUNDATION PRESSURE FOR VARIOUS FILL HEIGHTS HAVE BEEN GIVEN IN REFERRED DRAWINGS AS GIVEN IN TABLE 'X'. THICKNESSES OF TOP SLAB, BOTTOM SLAB AND VERTICAL WALLS HAVE BEEN KEPT UNIFORM.
5. THIS DESIGN IS SUITABLE FOR 25t LOADING-2008.
6. ALL REINFORCEMENT STEEL SHALL BE OF HIGH STRENGTH DEFORMED (HSD)/TMT BARS, Fe415 AND HIGHER GRADE REINFORCEMENT CONFORMING TO IS:1786-2008. FOR SEISMIC ZONES III, IV AND V HYSD STEEL BARS HAVING MINIMUM ELONGATION OF 14.5 PERCENT AND CONFORMING TO OTHER REQUIREMENTS OF IS:1786 SHALL BE USED.
7. DESIGN CRITERIA IS BASED ON FOLLOWING IRS CODES: i) IRS BRIDGE RULES  ii) IRS CONCRETE BRIDGE CODE  iii) IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE
8. LAPPING OF BARS SHOULD BE MINIMISED AND STAGGERED WHEREVER NECESSARY. MINIMUM LENGTH OF LAP SHALL BE AS GIVEN IN IRS CONCRETE BRIDGE CODE FOR TOR STEEL.
9. BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE. [printed in black, struck through in red]  Restored in red by ALT. 2 (see revisions). Faded red lines below it are not legible.
10. ALL RCC SURFACES COMING IN CONTACT WITH SOIL SHOULD BE PAINTED WITH BITUMEN OR COALTAR OF APPROVED QUALITY @ 1.464 KG/SQM.
11. CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm.
12. SCHEMATIC WING WALL AND RETURN WALL ARE GIVEN. HOWEVER, WING WALL AND RETURN WALL SHOULD BE DESIGNED SUITABLY BY ZONAL RAILWAYS AS PER SITE CONDITIONS.
13. i). BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii). IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL, DESIGNED SUITABLY.
14. IN CASE OF ERODIBLE SOILS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS) . SCHEMATIC CURTAIN/DROP WALL IS GIVEN.
15. TOLERANCE SHALL BE FOLLOWED AS PER IRS CONCRETE BRIDGE CODE.
16. M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER.
17. BED SLOPE SHALL BE ADJUSTED AS PER SITE CONDITIONS BY COMPETENT AUTHORITY.
18. FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED.
19. WEEP HOLES SHALL BE OF 75/100 DIA PVC/AC PIPES STAGGERED @ 1000 C/C ABOVE LOW WATER LEVEL IN BOTH WING WALL/RETURN WALL AND EARTH RETAINER OF BOX.
20. BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN.
21. DEPTH OF KEY AT BOTTOM SLAB, DK SHOULD BE PROVIDED AS GIVEN BELOW: [table, see tables]
22. THIS DRAWING SUPERSEDES DRAWING NO. RDSO/B-10152.
23. No SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN. [red, added by ALT. 3]

### Design basis (as printed)

- **loading**: 25t LOADING - 2008 (title block; note 5)
- **steel**: HSD/TMT bars, Fe415 and higher, conforming to IS:1786-2008; seismic zones III, IV, V: HYSD bars, minimum elongation 14.5 percent (note 6)
- **concrete grade**: M-35 when span or height of box is greater than or equal to 4 METER; M-30 when less than 4 METER (note 16)
- **clear cover**: 50mm (note 11)
- **base course below bed**: below 150mm THICK BASE COURSE (note 3)
- **wearing course**: 150 TH. WEARING COURSE; 150mm TH. WEARING COURSE (M-20) (cross section; sectional elevation; typical details A)
- **PCC base course**: 150mm TH. PCC BASE COURSE (sectional elevation; cross section; typical details B)
- **stone pitching**: 300 TH. STONE PITCHING WITH CEMENT GROUTING (sectional elevation)
- **bed slope**: BED SLOPE 1 IN 100 (MIN.) (sectional elevation; note 17)
- **side slope**: SLOPE 2:1 (sectional elevation, both sides)
- **outside slope limit**: SLOPE NOT STEEPER THAN 1:1 (cross section, lower outside)
- **ballast cushion**: 350mm HAS BEEN CONSIDERED IN DESIGN (note 20)
- **weep holes**: 75/100 DIA PVC/AC PIPES STAGGERED @ 1000 C/C (note 19); WEEP HOLES OF 75 DIA PVC PIPES @ 1000c/c (typical details) (typical details A; note 19)
- **bars in typical details**: BARS OF 10mm DIA @ 300mm c/c MAXIMUM (typical details A and B)
- **stirrups p**: 10 Φ, bent at an angle of 135° (reinforcement table g1, g2, g3)
- **key depth DK**: UPTO 900mm -> 1200mm; GREATER THAN 900mm -> tsb + 300mm (note 21)
- **fill heights in Table X**: 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0 m FILL HEIGHT (table X)
- **bitumen/coaltar coat**: BITUMEN OR COALTAR OF APPROVED QUALITY @ 1.464 KG/SQM (note 10)
- **haunch**: 200 X200 mm to 600 X600 mm by CLS or cht (haunch table) (table for B X B haunch)

### Schedule RDSO/B-10152/1R — fill 0.0 m (page 2, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 100.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 103.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 110.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 117.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 124.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 132.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 88.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 91.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 97.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 103.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 110.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 117.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 126.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 133.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 155.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 91.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 97.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 103.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 112.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 119.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 125.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 132.0 | explicit |  |
| 4mX6m | 500.0 | 500.0 | 500.0 | 149.0 | explicit |  |
| 5mX2.5m | 500.0 | 500.0 | 500.0 | 100.0 | explicit |  |
| 5mX3m | 500.0 | 500.0 | 500.0 | 107.0 | explicit |  |
| 5mX3.5m | 500.0 | 500.0 | 500.0 | 113.0 | explicit |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 119.0 | explicit |  |
| 5mX4.5m | 500.0 | 500.0 | 500.0 | 125.0 | explicit |  |
| 5mX5m | 500.0 | 500.0 | 500.0 | 131.0 | explicit |  |
| 5mX6m | 550.0 | 550.0 | 550.0 | 147.0 | explicit |  |
| 6mX3m | 550.0 | 550.0 | 550.0 | 107.0 | explicit |  |
| 6mX3.5m | 550.0 | 550.0 | 550.0 | 113.0 | explicit |  |
| 6mX4m | 550.0 | 550.0 | 550.0 | 119.0 | explicit |  |
| 6mX4.5m | 550.0 | 550.0 | 550.0 | 125.0 | explicit |  |
| 6mX5m | 600.0 | 600.0 | 600.0 | 134.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 149.0 | explicit |  |

### Schedule RDSO/B-10152/2R — fill 1.0 m (page 3, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 94.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 95.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 101.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 109.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 116.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 124.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 86.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 88.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 94.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 100.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 107.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 114.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 124.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 131.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 153.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 89.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 95.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 102.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 111.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 117.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 124.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 130.0 | explicit |  |
| 4mX6m | 500.0 | 500.0 | 500.0 | 147.0 | explicit |  |
| 5mX2.5m | 500.0 | 500.0 | 500.0 | 100.0 | explicit |  |
| 5mX3m | 500.0 | 500.0 | 500.0 | 106.0 | explicit |  |
| 5mX3.5m | 500.0 | 500.0 | 500.0 | 112.0 | explicit |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 118.0 | explicit |  |
| 5mX4.5m | 500.0 | 500.0 | 500.0 | 124.0 | explicit |  |
| 5mX5m | 500.0 | 500.0 | 500.0 | 131.0 | explicit |  |
| 5mX6m | 550.0 | 550.0 | 550.0 | 147.0 | explicit |  |
| 6mX3m | 550.0 | 550.0 | 550.0 | 107.0 | explicit |  |
| 6mX3.5m | 550.0 | 550.0 | 550.0 | 113.0 | explicit |  |
| 6mX4m | 550.0 | 550.0 | 550.0 | 119.0 | explicit |  |
| 6mX4.5m | 550.0 | 550.0 | 550.0 | 125.0 | explicit |  |
| 6mX5m | 600.0 | 600.0 | 600.0 | 135.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 150.0 | explicit |  |

### Schedule RDSO/B-10152/3R — fill 2.0 m (page 4, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 107.0 | explicit | Block 1 2mX1.8m and 2mX2.0m column cells were read on a half-width crop before the second pass; the top-right tiles repeat the 2mX4.0m and 3mX1.8m columns and agree with the transcription. |
| 2mX2m | 350.0 | 350.0 | 350.0 | 109.0 | explicit | Block 1 2mX1.8m and 2mX2.0m column cells were read on a half-width crop before the second pass; the top-right tiles repeat the 2mX4.0m and 3mX1.8m columns and agree with the transcription. |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 114.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 120.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 126.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 132.0 | explicit | Block 1 2mX1.8m and 2mX2.0m column cells were read on a half-width crop before the second pass; the top-right tiles repeat the 2mX4.0m and 3mX1.8m columns and agree with the transcription. |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 100.0 | explicit | Block 1 2mX1.8m and 2mX2.0m column cells were read on a half-width crop before the second pass; the top-right tiles repeat the 2mX4.0m and 3mX1.8m columns and agree with the transcription. |
| 3mX2m | 350.0 | 350.0 | 350.0 | 102.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 107.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 112.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 118.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 124.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 135.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 145.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 164.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 103.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 108.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 113.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 122.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 128.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 135.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 141.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 162.0 | explicit |  |
| 5mX2.5m | 500.0 | 500.0 | 500.0 | 112.0 | explicit |  |
| 5mX3m | 500.0 | 500.0 | 500.0 | 117.0 | explicit |  |
| 5mX3.5m | 500.0 | 500.0 | 500.0 | 124.0 | explicit |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 130.0 | explicit |  |
| 5mX4.5m | 500.0 | 500.0 | 500.0 | 136.0 | explicit |  |
| 5mX5m | 500.0 | 500.0 | 500.0 | 142.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 162.0 | explicit |  |
| 6mX3m | 600.0 | 600.0 | 600.0 | 122.0 | explicit |  |
| 6mX3.5m | 600.0 | 600.0 | 600.0 | 128.0 | explicit |  |
| 6mX4m | 600.0 | 600.0 | 600.0 | 134.0 | explicit |  |
| 6mX4.5m | 600.0 | 600.0 | 600.0 | 140.0 | explicit |  |
| 6mX5m | 600.0 | 600.0 | 600.0 | 147.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 162.0 | explicit |  |

### Schedule RDSO/B-10152/4R — fill 3.0 m (page 5, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 121.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 123.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 128.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 135.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 141.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 147.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 115.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 117.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 123.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 128.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 134.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 146.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 153.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 160.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 182.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 119.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 127.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 132.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 137.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 143.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 149.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 159.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 177.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 131.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 136.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 142.0 | explicit |  |
| 5mX4m | 550.0 | 550.0 | 550.0 | 147.0 | explicit |  |
| 5mX4.5m | 550.0 | 550.0 | 550.0 | 154.0 | explicit |  |
| 5mX5m | 550.0 | 550.0 | 550.0 | 160.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 177.0 | explicit |  |
| 6mX3m | 650.0 | 650.0 | 650.0 | 140.0 | explicit |  |
| 6mX3.5m | 650.0 | 650.0 | 650.0 | 146.0 | explicit |  |
| 6mX4m | 650.0 | 650.0 | 650.0 | 152.0 | explicit |  |
| 6mX4.5m | 650.0 | 650.0 | 650.0 | 158.0 | explicit |  |
| 6mX5m | 650.0 | 650.0 | 650.0 | 164.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 177.0 | explicit |  |

### Schedule RDSO/B-10152/5R — fill 4.0 m (page 6, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 137.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 139.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 145.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 151.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 158.0 | explicit |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 168.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 132.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 134.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 139.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 145.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 154.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 164.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 170.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 177.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 198.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 138.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 144.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 149.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 155.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 160.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 170.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 176.0 | explicit |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 197.0 | explicit |  |
| 5mX2.5m | 600.0 | 600.0 | 600.0 | 151.0 | explicit |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 156.0 | explicit |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 162.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 168.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 174.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 180.0 | explicit |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 196.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 161.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 166.0 | explicit |  |
| 6mX4m | 700.0 | 700.0 | 700.0 | 172.0 | explicit |  |
| 6mX4.5m | 700.0 | 700.0 | 700.0 | 178.0 | explicit |  |
| 6mX5m | 700.0 | 700.0 | 700.0 | 184.0 | explicit |  |
| 6mX6m | 700.0 | 700.0 | 700.0 | 197.0 | explicit |  |

### Schedule RDSO/B-10152/6R — fill 5.0 m (page 7, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 154.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 156.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 162.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 169.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 175.0 | explicit |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 185.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 152.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 154.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 160.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 166.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 172.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 182.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 188.0 | explicit |  |
| 3mX5m | 500.0 | 500.0 | 500.0 | 199.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 216.0 | explicit |  |
| 4mX2m | 500.0 | 500.0 | 500.0 | 159.0 | explicit |  |
| 4mX2.5m | 500.0 | 500.0 | 500.0 | 164.0 | explicit | top_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; bottom_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; side_walls: printed '50m' (no 'c'); read as cm like every other cell of the row; Slab thickness cells of 4mX2.5m to 4mX4.0m (row group 2) read "50m" with no "c"; a zoom of the cell confirms the printed text, recorded as printed. |
| 4mX3m | 500.0 | 500.0 | 500.0 | 170.0 | explicit | top_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; bottom_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; side_walls: printed '50m' (no 'c'); read as cm like every other cell of the row; Slab thickness cells of 4mX2.5m to 4mX4.0m (row group 2) read "50m" with no "c"; a zoom of the cell confirms the printed text, recorded as printed. |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 176.0 | explicit | top_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; bottom_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; side_walls: printed '50m' (no 'c'); read as cm like every other cell of the row; Slab thickness cells of 4mX2.5m to 4mX4.0m (row group 2) read "50m" with no "c"; a zoom of the cell confirms the printed text, recorded as printed. |
| 4mX4m | 500.0 | 500.0 | 500.0 | 182.0 | explicit | top_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; bottom_slab: printed '50m' (no 'c'); read as cm like every other cell of the row; side_walls: printed '50m' (no 'c'); read as cm like every other cell of the row; Slab thickness cells of 4mX2.5m to 4mX4.0m (row group 2) read "50m" with no "c"; a zoom of the cell confirms the printed text, recorded as printed. |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 188.0 | explicit |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 198.0 | explicit |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 215.0 | explicit |  |
| 5mX2.5m | 650.0 | 650.0 | 650.0 | 171.0 | explicit |  |
| 5mX3m | 650.0 | 650.0 | 650.0 | 177.0 | explicit |  |
| 5mX3.5m | 650.0 | 650.0 | 650.0 | 183.0 | explicit |  |
| 5mX4m | 650.0 | 650.0 | 650.0 | 189.0 | explicit |  |
| 5mX4.5m | 650.0 | 650.0 | 650.0 | 195.0 | explicit |  |
| 5mX5m | 650.0 | 650.0 | 650.0 | 201.0 | explicit |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 214.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 179.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 185.0 | explicit |  |
| 6mX4m | 700.0 | 700.0 | 700.0 | 191.0 | explicit |  |
| 6mX4.5m | 700.0 | 700.0 | 700.0 | 196.0 | explicit |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 205.0 | explicit |  |
| 6mX6m | 800.0 | 800.0 | 800.0 | 221.0 | explicit |  |

### Schedule RDSO/B-10152/7R — fill 6.0 m (page 8, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 172.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 174.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 180.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 187.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 193.0 | explicit |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 203.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 170.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 172.0 | explicit |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 181.0 | explicit |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 187.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 193.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 3mX4.5m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 3mX5m | 500.0 | 500.0 | 500.0 | 217.0 | explicit |  |
| 3mX6m | 600.0 | 600.0 | 600.0 | 239.0 | explicit |  |
| 4mX2m | 500.0 | 500.0 | 500.0 | 177.0 | explicit |  |
| 4mX2.5m | 500.0 | 500.0 | 500.0 | 182.0 | explicit |  |
| 4mX3m | 550.0 | 550.0 | 550.0 | 191.0 | explicit |  |
| 4mX3.5m | 550.0 | 550.0 | 550.0 | 197.0 | explicit |  |
| 4mX4m | 550.0 | 550.0 | 550.0 | 203.0 | explicit |  |
| 4mX4.5m | 550.0 | 550.0 | 550.0 | 210.0 | explicit |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 216.0 | explicit |  |
| 4mX6m | 650.0 | 650.0 | 650.0 | 237.0 | explicit |  |
| 5mX2.5m | 650.0 | 650.0 | 650.0 | 189.0 | explicit |  |
| 5mX3m | 650.0 | 650.0 | 650.0 | 195.0 | explicit |  |
| 5mX3.5m | 700.0 | 700.0 | 700.0 | 204.0 | explicit |  |
| 5mX4m | 700.0 | 700.0 | 700.0 | 210.0 | explicit |  |
| 5mX4.5m | 700.0 | 700.0 | 700.0 | 217.0 | explicit |  |
| 5mX5m | 700.0 | 700.0 | 700.0 | 223.0 | explicit |  |
| 5mX6m | 700.0 | 700.0 | 700.0 | 236.0 | explicit |  |
| 6mX3m | 750.0 | 750.0 | 750.0 | 200.0 | explicit |  |
| 6mX3.5m | 800.0 | 800.0 | 800.0 | 208.0 | explicit |  |
| 6mX4m | 800.0 | 800.0 | 800.0 | 215.0 | explicit |  |
| 6mX4.5m | 800.0 | 800.0 | 800.0 | 221.0 | explicit |  |
| 6mX5m | 800.0 | 800.0 | 800.0 | 227.0 | explicit |  |
| 6mX6m | 800.0 | 800.0 | 800.0 | 239.0 | explicit |  |

### Schedule RDSO/B-10152/8R — fill 8.0 m (page 9, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 207.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 216.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 223.0 | explicit |  |
| 2mX3.5m | 450.0 | 450.0 | 450.0 | 236.0 | explicit |  |
| 2mX4m | 450.0 | 450.0 | 450.0 | 243.0 | explicit |  |
| 3mX1.8m | 450.0 | 450.0 | 450.0 | 209.0 | explicit |  |
| 3mX2m | 450.0 | 450.0 | 450.0 | 211.0 | explicit |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 217.0 | explicit |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 223.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 230.0 | explicit |  |
| 3mX4m | 500.0 | 500.0 | 500.0 | 240.0 | explicit |  |
| 3mX4.5m | 500.0 | 500.0 | 500.0 | 247.0 | explicit |  |
| 3mX5m | 550.0 | 550.0 | 550.0 | 257.0 | explicit |  |
| 3mX6m | 650.0 | 650.0 | 650.0 | 279.0 | explicit |  |
| 4mX2m | 550.0 | 550.0 | 550.0 | 215.0 | explicit |  |
| 4mX2.5m | 550.0 | 550.0 | 550.0 | 221.0 | explicit |  |
| 4mX3m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 4mX3.5m | 600.0 | 600.0 | 600.0 | 237.0 | explicit |  |
| 4mX4m | 600.0 | 600.0 | 600.0 | 243.0 | explicit |  |
| 4mX4.5m | 600.0 | 600.0 | 600.0 | 249.0 | explicit |  |
| 4mX5m | 600.0 | 600.0 | 600.0 | 256.0 | explicit |  |
| 4mX6m | 700.0 | 700.0 | 700.0 | 277.0 | explicit |  |
| 5mX2.5m | 750.0 | 750.0 | 750.0 | 231.0 | explicit |  |
| 5mX3m | 750.0 | 750.0 | 750.0 | 237.0 | explicit |  |
| 5mX3.5m | 750.0 | 750.0 | 750.0 | 244.0 | explicit |  |
| 5mX4m | 750.0 | 750.0 | 750.0 | 250.0 | explicit |  |
| 5mX4.5m | 750.0 | 750.0 | 750.0 | 256.0 | explicit |  |
| 5mX5m | 750.0 | 750.0 | 750.0 | 263.0 | explicit |  |
| 5mX6m | 750.0 | 750.0 | 750.0 | 276.0 | explicit |  |
| 6mX3m | 850.0 | 850.0 | 850.0 | 242.0 | explicit |  |
| 6mX3.5m | 900.0 | 900.0 | 900.0 | 251.0 | explicit |  |
| 6mX4m | 900.0 | 900.0 | 900.0 | 257.0 | explicit |  |
| 6mX4.5m | 900.0 | 900.0 | 900.0 | 263.0 | explicit |  |
| 6mX5m | 900.0 | 900.0 | 900.0 | 270.0 | explicit |  |
| 6mX6m | 900.0 | 900.0 | 900.0 | 283.0 | explicit |  |

### Schedule RDSO/B-10152/9R — fill 10.0 m (page 10, 10152-R series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 243.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 245.0 | explicit |  |
| 2mX2.5m | 400.0 | 400.0 | 400.0 | 255.0 | explicit |  |
| 2mX3m | 450.0 | 450.0 | 450.0 | 265.0 | explicit |  |
| 2mX3.5m | 500.0 | 500.0 | 500.0 | 275.0 | explicit |  |
| 2mX4m | 550.0 | 550.0 | 550.0 | 286.0 | explicit |  |
| 3mX1.8m | 500.0 | 500.0 | 500.0 | 248.0 | explicit |  |
| 3mX2m | 500.0 | 500.0 | 500.0 | 250.0 | explicit |  |
| 3mX2.5m | 500.0 | 500.0 | 500.0 | 256.0 | explicit |  |
| 3mX3m | 500.0 | 500.0 | 500.0 | 263.0 | explicit |  |
| 3mX3.5m | 550.0 | 550.0 | 550.0 | 273.0 | explicit |  |
| 3mX4m | 600.0 | 600.0 | 600.0 | 283.0 | explicit |  |
| 3mX4.5m | 600.0 | 600.0 | 600.0 | 290.0 | explicit |  |
| 3mX5m | 700.0 | 700.0 | 700.0 | 304.0 | explicit |  |
| 3mX6m | 800.0 | 800.0 | 800.0 | 327.0 | explicit |  |
| 4mX2m | 650.0 | 650.0 | 650.0 | 257.0 | explicit |  |
| 4mX2.5m | 650.0 | 650.0 | 650.0 | 263.0 | explicit |  |
| 4mX3m | 650.0 | 650.0 | 650.0 | 270.0 | explicit |  |
| 4mX3.5m | 700.0 | 700.0 | 700.0 | 279.0 | explicit |  |
| 4mX4m | 700.0 | 700.0 | 700.0 | 286.0 | explicit |  |
| 4mX4.5m | 700.0 | 700.0 | 700.0 | 293.0 | explicit |  |
| 4mX5m | 750.0 | 750.0 | 750.0 | 303.0 | explicit |  |
| 4mX6m | 850.0 | 850.0 | 850.0 | 324.0 | explicit |  |
| 5mX2.5m | 800.0 | 800.0 | 800.0 | 271.0 | explicit |  |
| 5mX3m | 800.0 | 800.0 | 800.0 | 277.0 | explicit |  |
| 5mX3.5m | 800.0 | 800.0 | 800.0 | 283.0 | explicit |  |
| 5mX4m | 850.0 | 850.0 | 850.0 | 293.0 | explicit |  |
| 5mX4.5m | 850.0 | 850.0 | 850.0 | 299.0 | explicit |  |
| 5mX5m | 850.0 | 850.0 | 850.0 | 306.0 | explicit |  |
| 5mX6m | 900.0 | 900.0 | 900.0 | 323.0 | explicit |  |
| 6mX3m | 900.0 | 900.0 | 900.0 | 281.0 | explicit |  |
| 6mX3.5m | 900.0 | 900.0 | 900.0 | 288.0 | explicit |  |
| 6mX4m | 900.0 | 900.0 | 900.0 | 294.0 | explicit |  |
| 6mX4.5m | 900.0 | 900.0 | 900.0 | 300.0 | explicit |  |
| 6mX5m | 900.0 | 900.0 | 900.0 | 307.0 | explicit |  |
| 6mX6m | 1000.0 | 1000.0 | 1000.0 | 326.0 | explicit |  |

Unclear items recorded by the extraction: 26; not-read items: 21 (full list in the JSON).

## RDSO/B-10153 (RDSO-RCC-BOX-10153)

Source: RDSO_B_10153_series.pdf. Title: STANDARD DRAWING OF SEGMENTAL RCC BOX CULVERT FOR LIMITED HEIGHT SUBWAY 25t LOADING - 2008 (GENERAL ARRANGEMENT PART-I). Date: DATE: 29.06.2012 (PROVISIONAL).

### Applicability (as printed)

- **structure**: segmental (pre-cast) RCC box culvert for limited height subway (LHS)  (title)
- **track**: single or multiple lines (limited height subway)  (note 2)
- **loading**: 25t loading - 2008  (title)
- **curvature**:  — THIS DRAWING IS SUITABLE FOR CONSTRUCTION OF LIMITED HEIGHT SUBWAYS (LHS) ON SINGLE AS WELL AS MULTIPLE LINES UPTO 1m FILL HEIGHT. [red added: FOR STRAIGHT TRACK ONLY.] [unclear at crop scale] (note 2)
- **skew**: no skew angle considered in the design — [red, ALT. 6] NO SKEW ANGLE HAS BEEN CONSIDERED IN THIS DESIGN. [overview scale only] (note 23)
- **ballast_cushion_mm**: 350.0 — BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN. [crop scale, end of line partly outside the crop] (note 20)
- **clear_cover_mm**: 50.0 — CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm AS PER CLAUSE NO. 15.9.2 OF IRS CONCRETE BRIDGE CODE. [overview scale only] (note 11)
- **config_label_meaning**: span x height = clear span (CLS) x height of box including wearing course (ht) — [red, ALT. 2] SPAN LENGTH x BOX HEIGHT CONFIGURATION MENTIONED IN ALL RELATED DRAWINGS INDICATE CLEAR SPAN (CLS) & HEIGHT OF BOX INCLUDING WEARING COURSE (ht). [crop scale] (note 21)
- **intermediate_configuration_rule**:  — FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED. [crop scale] (note 18)
- **barrel_length_rule**:  — i). BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL OF SUITABLE DESIGN. [overview scale only] (note 13)
- **concrete_grade_rule**:  — M-35 GRADE CONCRETE SHALL BE USED FOR THE CONSTRUCTION OF SEGMENTAL BOX. [struck through in part at crop scale] (note 15)

### Sheets

| Drawing | Page | Kind | Fill (m) | Verification | Usable |
|---|---|---|---|---|---|
| RDSO/B-10153 | 1 (RDSO_B_10153_series.pdf) | general arrangement | - | checked against the displayed drawing | yes |
| RDSO/B-10153/1 | 2 (RDSO_B_10153_series.pdf) | general arrangement | - | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10153/2 | 3 (RDSO_B_10153_series.pdf) | structural design details | 1.0 | the extraction says every number on this page is provisional (soft scan) | NO |
| RDSO/B-10153/2A | 4 (RDSO_B_10153_series.pdf) | structural design details | 1.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10153/3 | 5 (RDSO_B_10153_series.pdf) | structural design details | 0.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10153/3A | 6 (RDSO_B_10153_series.pdf) | structural design details | 0.0 | transcribed by eye from displayed tiles; not re-checked | yes |

### Haunch B x B (by CLS or cht)

| From (m) | To (m) | Size (mm) | Printed |
|---|---|---|---|
| 4.0 | 4.5 | 400 | > 4.0 m and < 4.5m -> 400 X 400 mm |
| 4.5 | 5.0 | 450 | > 4.5 m and < 5.0m -> 450 X 450 mm |
| 5.0 | 5.5 | 500 | > 5.0 m and < 5.5m -> 500 X 500 mm |
| 5.5 | 6.0 | 550 | > 5.5 m and < 6.0m -> 550 X 550 mm |

### Relations from the notations (derived)

- `RDSO-RCC-BOX-10153:ht`: ht = cht + wearing course thickness (ht is the height of box including wearing course; cht the clear height above the wearing course)
- `RDSO-RCC-BOX-10153:tht`: tht = ht + tst + tsb
- `RDSO-RCC-BOX-10153:ols`: OLS = CLS + 2 x tsv (single cell)
- `RDSO-RCC-BOX-10153:tbl`: TBL = UBL + DBL

### Notes (verbatim, general arrangement)

1. ALL DIMENSIONS ARE IN MILLIMETER UNLESS OTHERWISE SPECIFIED.
2. THIS DRAWING IS SUITABLE FOR CONSTRUCTION OF LIMITED HEIGHT SUBWAYS (LHS) ON SINGLE AS WELL AS MULTIPLE LINES UPTO 1m FILL HEIGHT. [red added: FOR STRAIGHT TRACK ONLY.] [unclear at crop scale]
3. PREPARATION OF BED BELOW BASE SLAB SHOULD BE AS PER ACTUAL SITE CONDITIONS IN ORDER TO ACHIEVE ADEQUATE BEARING CAPACITY REQUIRED TO WITHSTAND THE FOUNDATION PRESSURE GIVEN IN RELATED DRAWINGS INDICATED IN TABLE 'X'. A MINIMUM SAND LAYER OF 200mm THICK TO BE SPREAD BELOW THE RCC SLAB. [overview scale only]
4. REINFORCEMENT DETAILS, SLAB THICKNESS DETAILS AND FOUNDATION PRESSURE FOR VARIOUS FILL HEIGHTS HAVE BEEN GIVEN IN RELATED DRAWINGS AS INDICATED IN TABLE 'X'. THICKNESSES OF TOP SLAB, BOTTOM SLAB AND VERTICAL WALLS HAVE BEEN KEPT UNIFORM. [overview scale only]
5. THIS DESIGN IS SUITABLE FOR 25t LOADING - 2008. [overview scale only]
6. [struck through] HSD/TMT BARS (Fe415/Fe500D) CONFORMING TO IS:1786-2008 SHALL BE USED AS REINFORCEMENT. [replaced in red by ALT. 2:] ALL REINFORCEMENT STEEL SHALL BE OF HIGH STRENGTH DEFORMED (HSD)/TMT BARS, Fe415 AND HIGHER GRADE REINFORCEMENT CONFORMING TO IS:1786-2008. FOR SEISMIC ZONES III, IV AND V BARS HAVING MINIMUM ELONGATION OF 14.5 PERCENT AND CONFORMING TO OTHER REQUIREMENTS OF IS:1786 SHALL BE USED. [red text read at crop scale; the struck original digit group is unclear]
7. DESIGN CRITERIA IS BASED ON FOLLOWING IRS CODES: i) IRS BRIDGE RULES ii) IRS CONCRETE BRIDGE CODE iii) IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE. [overview scale only]
8. LAPPING OF BARS SHOULD BE MINIMISED AND STAGGERED WHEREVER NECESSARY. MINIMUM LENGTH OF LAP SHALL BE AS GIVEN IN IRS CONCRETE BRIDGE CODE FOR TOR STEEL. [overview scale only]
9. [struck through] BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE. [replaced in red, ALT. 5:] BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE. IN LIEU OF GRADED FILTER (IN THE FORM OF BOULDER/COBBLES) ON THE VERTICAL WALLS OF LHS, GEO-COMPOSITE DRAIN MAY BE USED FOR TRIAL PURPOSE AS PER GEO-TECH ENGINEERING DIRECTORATE, RDSO LETTER NO. GE/GEN/COMMENTS/GCD/185/VERTICAL(PART-1) DATED 13.09.2019 IN REFERENCE TO EDCE/B&S/RB EMAIL DATED 05.09.2019. [red text read at crop scale; the 13.09.2019 date reading is confirmed by the crop, the second date reading is 05.09.2019]
10. ALL RCC SURFACES COMING IN CONTACT WITH SOIL SHOULD BE PAINTED WITH BITUMEN OR COALTAR OF APPROVED QUALITY 1.484 KG/SQM. [overview scale only; the value 1.484 is unclear at crop scale]
11. CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm AS PER CLAUSE NO. 15.9.2 OF IRS CONCRETE BRIDGE CODE. [overview scale only]
12. SAMPLE DETAILS OF WING WALL AND RETURN WALL ARE GIVEN. HOWEVER, WING WALL AND RETURN WALL SHOULD BE DESIGNED SUITABLY BY ZONAL RAILWAYS AS PER SITE CONDITIONS. [overview scale only]
13. i). BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL OF SUITABLE DESIGN. [overview scale only]
14. [struck through] IN CASE OF ERODIBLE SOILS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS) WITH A MINIMUM DEPTH BELOW FLOOR LEVEL OF 2.0m FOR CURTAIN WALL AND 2.5m FOR DROP WALL. MINIMUM WIDTH OF FOUNDATION FOR CURTAIN WALL/DROP WALL SHOULD BE 900mm. [replaced in red by: IF POSSIBILITY OF SCOUR EXISTS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS). SCHEMATIC CURTAIN/DROP WALL IS GIVEN. (ALT. 3 / ALT. 4)] [the struck wording is partly read at crop scale; the red replacement is read at overview scale]
15. M-35 GRADE CONCRETE SHALL BE USED FOR THE CONSTRUCTION OF SEGMENTAL BOX. [struck through in part at crop scale]
16. BASE SLAB UNITS SHOULD BE OF M-25 GRADE CONCRETE. [struck through in part at crop scale]
17. [struck through] BED SLOPE SHALL BE DECIDED AS PER SITE CONDITIONS BY COMPETENT AUTHORITY. IT SHOULD BE KEPT MINIMUM 1 IN 100. [replaced in red: 17. BED SLOPE SHALL BE ADJUSTED AS PER SITE CONDITIONS BY COMPETENT AUTHORITY.]
18. FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED. [crop scale]
19. WEEP HOLES SHALL BE OF 75/100 DIA PVC/AC PIPES STAGGERED @ 1000 C/C ABOVE LOW WATER LEVEL IN BOTH WING WALL/RETURN WALL AND EARTH RETAINER OF BOX. [crop scale, end of line partly outside the crop]
20. BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN. [crop scale, end of line partly outside the crop]
21. [red, ALT. 2] SPAN LENGTH x BOX HEIGHT CONFIGURATION MENTIONED IN ALL RELATED DRAWINGS INDICATE CLEAR SPAN (CLS) & HEIGHT OF BOX INCLUDING WEARING COURSE (ht). [crop scale]
22. [red, ALT. 5 note] FOR DRAINAGE AND RELATED ARRANGEMENT, THE DRAWING NO. RDSO/B-10159 MAY BE REFERRED. [crop scale; the drawing number reads RDSO/B-10159 at crop scale]
23. [red, ALT. 6] NO SKEW ANGLE HAS BEEN CONSIDERED IN THIS DESIGN. [overview scale only]

### Design basis (as printed)

- **loading**: 25t LOADING - 2008 (title block; note 5)
- **fill height (limit for this configuration)**: UPTO 1m FILL HEIGHT (note 2)
- **concrete grade (box)**: M-35 (note 15)
- **concrete grade (base slab unit)**: M-25 (note 16)
- **reinforcement**: HSD/TMT Fe415 and higher, IS:1786-2008; seismic zones III, IV, V: minimum elongation 14.5 percent (note 6 (red))
- **cover for reinforcing bars**: 50mm (note 11)
- **sand layer below RCC slab**: 200mm THICK (note 3; 200mm SAND FILLING (A&B, X-X))
- **pre-cast base slab unit**: 250mm TH. (X-X; A&B; Y-Y)
- **wearing course**: 150mm TH. (X-X; A&B; Y-Y)
- **ballast cushion**: 350mm (note 20)
- **bed slope**: 1 IN 100 (MIN.) (X-X; note 17 (red: adjusted as per site conditions))
- **embankment slope**: SLOPE 2:1 (X-X)
- **slope not steeper than**: 1:1 (Y-Y, left (SLOPE NOT STEEPER THAN 1:1))
- **weep holes**: 75 DIA PVC PIPES @ 1000c/c (A&B; note 19 (75/100 dia PVC/AC))
- **stone pitching**: 300 TH. STONE PITCHING WITH CEMENT GROUTING (X-X)
- **wing wall angle**: 45 deg (PLAN; Y-Y section angle symbol)
- **skew**: NO SKEW ANGLE HAS BEEN CONSIDERED IN THIS DESIGN (note 23 (red, ALT. 6))
- **minimum width of foundation for curtain/drop wall (struck)**: 900mm (note 14 (struck through))
- **minimum depth below floor level (struck)**: 2.0m FOR CURTAIN WALL AND 2.5m FOR DROP WALL (note 14 (struck through))
- **haunch size by CLS or cht**: > 4.0 m and < 4.5m: 400 X 400 mm; > 4.5 m and < 5.0m: 450 X 450 mm; > 5.0 m and < 5.5m: 500 X 500 mm; > 5.5 m and < 6.0m: 550 X 550 mm (TABLE FOR B X B HAUNCH)
- **max. spacing of reinforcement (return wall, wing wall)**: 200mm C/C (SECTION OF RETURN WALL; WING WALL)
- **dimension 250 (curtain/drop wall stem)**: 250 (SECTION OF CURTAIN/DROP WALL)

### Schedule RDSO/B-10153/2 — fill 0.0 m (page 3, RDSO_B_10153_series.pdf) — NOT USABLE

Verification: the extraction says every number on this page is provisional (soft scan).

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX3.6m | 450.0 | 450.0 | 450.0 | 190.0 | unverified |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 200.0 | unverified |  |
| 5mX3.6m | 500.0 | 500.0 | 500.0 | 190.0 | unverified |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 190.0 | unverified |  |
| 5.5mX3.6m | 500.0 | 500.0 | 500.0 | 190.0 | unverified |  |
| 5.5mX4m | 500.0 | 500.0 | 500.0 | 190.0 | unverified |  |

### Schedule RDSO/B-10153/2A — fill 0.0 m (page 4, RDSO_B_10153_series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX3.75m | 450.0 | 450.0 | 450.0 | 19.0 | explicit |  |
| 4mX4.15m | 450.0 | 450.0 | 450.0 | 20.0 | explicit |  |
| 5mX3.75m | 550.0 | 550.0 | 550.0 | 19.0 | explicit |  |
| 5mX4.15m | 550.0 | 550.0 | 550.0 | 20.0 | explicit |  |
| 5.5mX3.75m | 600.0 | 600.0 | 600.0 | 19.0 | explicit |  |
| 5.5mX4.15m | 600.0 | 600.0 | 600.0 | 20.0 | explicit |  |

### Schedule RDSO/B-10153/3 — fill 0.0 m (page 5, RDSO_B_10153_series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 180.0 | explicit | The top block g3 text runs to the edge of its cell in the 4.0mX4.5m and 4.5mX4.5m columns; the words ALONG HEIGHT are read in full. |
| 4mX5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit | The top block column 2 (4.0mX5.0m) e row reads 12mm DIA @ 100mm, while the other columns read 12mm DIA @ 200mm; the 100mm reading was read at full scale and is stated as read. |
| 4.5mX4.5m | 500.0 | 500.0 | 500.0 | 180.0 | explicit | The top block g3 text runs to the edge of its cell in the 4.0mX4.5m and 4.5mX4.5m columns; the words ALONG HEIGHT are read in full. |
| 4.5mX5m | 500.0 | 500.0 | 500.0 | 190.0 | explicit |  |
| 5mX4.5m | 550.0 | 550.0 | 550.0 | 190.0 | explicit |  |
| 5mX5m | 550.0 | 550.0 | 550.0 | 190.0 | explicit |  |

### Schedule RDSO/B-10153/3A — fill 0.0 m (page 6, RDSO_B_10153_series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX4.65m | 450.0 | 450.0 | 450.0 | 21.0 | explicit |  |
| 4mX5.15m | 450.0 | 450.0 | 450.0 | 21.0 | explicit |  |
| 4.5mX4.65m | 500.0 | 500.0 | 500.0 | 21.0 | explicit |  |
| 4.5mX5.15m | 500.0 | 500.0 | 500.0 | 21.0 | explicit |  |
| 5mX4.65m | 550.0 | 550.0 | 550.0 | 20.0 | explicit |  |
| 5mX5.15m | 550.0 | 550.0 | 550.0 | 21.0 | explicit |  |

### Schedule RDSO/B-10153/2 — fill 0.5 m (page 3, RDSO_B_10153_series.pdf) — NOT USABLE

Verification: the extraction says every number on this page is provisional (soft scan).

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX3.6m | 450.0 | 450.0 | 450.0 | 170.0 | unverified |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 180.0 | unverified |  |
| 5mX3.6m | 500.0 | 500.0 | 550.0 | 170.0 | unverified | 0.5m block, side walls, 5m x 3.6m column (column 3) reads 55cm (soft); other side-wall cells read 45cm or 50cm.; 0.5m block, weight row, 5m x 3.6m column (column 3) reads 38.72 t on first reading (soft); the 0.0m and 1.0m equivalents read 36.72 t. The two readings should be checked against the scan. |
| 5mX4m | 500.0 | 500.0 | 500.0 | 180.0 | unverified |  |
| 5.5mX3.6m | 500.0 | 500.0 | 500.0 | 170.0 | unverified |  |
| 5.5mX4m | 500.0 | 500.0 | 500.0 | 170.0 | unverified |  |

### Schedule RDSO/B-10153/2A — fill 0.5 m (page 4, RDSO_B_10153_series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX3.75m | 450.0 | 450.0 | 450.0 | 18.0 | explicit |  |
| 4mX4.15m | 450.0 | 450.0 | 450.0 | 18.0 | explicit |  |
| 5mX3.75m | 550.0 | 550.0 | 550.0 | 18.0 | explicit |  |
| 5mX4.15m | 550.0 | 550.0 | 550.0 | 18.0 | explicit |  |
| 5.5mX3.75m | 600.0 | 600.0 | 600.0 | 18.0 | explicit |  |
| 5.5mX4.15m | 600.0 | 600.0 | 600.0 | 18.0 | explicit |  |

### Schedule RDSO/B-10153/2 — fill 1.0 m (page 3, RDSO_B_10153_series.pdf) — NOT USABLE

Verification: the extraction says every number on this page is provisional (soft scan).

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX3.6m | 450.0 | 450.0 | 450.0 | 170.0 | unverified |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 180.0 | unverified |  |
| 5mX3.6m | 500.0 | 500.0 | 500.0 | 170.0 | unverified |  |
| 5mX4m | 500.0 | 500.0 | 500.0 | 170.0 | unverified |  |
| 5.5mX3.6m | 500.0 | 500.0 | 500.0 | 160.0 | unverified | 1.0m block, foundation pressure column 5 (5.5m x 3.6m) reads 160 kN/m2 (soft; other columns 170 kN/m2 or 180 kN/m2). |
| 5.5mX4m | 500.0 | 500.0 | 500.0 | 170.0 | unverified |  |

### Schedule RDSO/B-10153/2A — fill 1.0 m (page 4, RDSO_B_10153_series.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 4mX3.75m | 450.0 | 450.0 | 450.0 | 17.0 | explicit |  |
| 4mX4.15m | 450.0 | 450.0 | 450.0 | 18.0 | explicit |  |
| 5mX3.75m | 550.0 | 550.0 | 550.0 | 17.0 | explicit |  |
| 5mX4.15m | 550.0 | 550.0 | 550.0 | 18.0 | explicit |  |
| 5.5mX3.75m | 600.0 | 600.0 | 600.0 | 17.0 | explicit |  |
| 5.5mX4.15m | 600.0 | 600.0 | 600.0 | 18.0 | explicit |  |

### Printed discrepancies within the set

- **10153-D1**: p3 (RDSO/B-10153/2) prints heights 3.6 m / 4.0 m where p4 (RDSO/B-10153/2A) prints 3.75 m / 4.15 m for the same 0.0 m fill configurations; note 21 (ALT 2) says the height in the labels includes the wearing course. Neither page is chosen.
- **10153-D2**: Table X row 3 lists six span-height configurations on p1 and five on p2 (4.5X5 missing); the p5/p6 headers use another form. Nothing chosen.
- **10153-D3**: Table X cites RDSO/B-10153/2 and /3; the later-dated /2A and /3A (8.02.2017) are in the file; no sheet says which is current.

Unclear items recorded by the extraction: 26; not-read items: 20 (full list in the JSON).

## RDSO/B-10155 (RDSO-RCC-BOX-10155)

Source: RDSO_B_10155 to 10155-5 .pdf, RDSO_B_10155_6 to 10155-10_.pdf. Title: R.D.S.O. / STANDARD DRAWING OF SINGLE BOX CULVERT FOR DOUBLE LINE TRACK CURVED UPTO 4 deg (GENERAL ARRANGEMENT) / 25t LOADING - 2008   (red "10 deg" written above the struck "4 deg", ALT 5). Date: DATE: 22.05.2013 (title block); approval 'ED/STRUCTURES' blue 22/5/13.

### Applicability (as printed)

- **structure**: single-cell RCC box culvert  (title)
- **track**: double line  (title / note 2)
- **loading**: 25t loading - 2008  (title)
- **curvature**:  — THIS DRAWING IS SUITABLE FOR DOUBLE LINE TRACK UPTO 4 DEGREE CURVATURE ONLY. [red: '10' written above, '4' struck; ALT 5] (note 2)
- **skew**: no skew angle considered in the design — [red, ALT 5] NO SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN. (note 23)
- **min_track_spacing_m**: 5.3 — MINIMUM SPACING OF TRACKS IS ASSUMED AS 5.3m IN DESIGN WHICH MAY BE SUITABLY INCREASED AS PER REQUIREMENTS OF CURVE. (note 3)
- **ballast_cushion_mm**: 350.0 — BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN. (note 21)
- **clear_cover_mm**: 50.0 — CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm. (note 12)
- **config_label_meaning**:   (not stated on the sheets read)
- **intermediate_configuration_rule**:  — FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED. (note 19)
- **barrel_length_rule**:  — i) BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL, DESIGNED SUITABLY. (note 14)
- **concrete_grade_rule**:  — M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER. (note 17)

### Sheets

| Drawing | Page | Kind | Fill (m) | Verification | Usable |
|---|---|---|---|---|---|
| RDSO/B-10155 | 1 (RDSO_B_10155 to 10155-5 .pdf) | general arrangement | - | checked against the displayed drawing | yes |
| RDSO/B-10155/1 | 2 (RDSO_B_10155 to 10155-5 .pdf) | structural design details | 0.0 | checked against the displayed drawing | yes |
| RDSO/B-10155/2 | 3 (RDSO_B_10155 to 10155-5 .pdf) | structural design details | 1.0 | checked against the displayed drawing | yes |
| RDSO/B-10155/3 | 4 (RDSO_B_10155 to 10155-5 .pdf) | structural design details | 2.0 | checked against the displayed drawing | yes |
| RDSO/B-10155/4 | 5 (RDSO_B_10155 to 10155-5 .pdf) | structural design details | 3.0 | checked against the displayed drawing | yes |
| RDSO/B-10155/5 | 6 (RDSO_B_10155 to 10155-5 .pdf) | structural design details | 4.0 | checked against the displayed drawing | yes |
| RDSO/B-10155/6 | 1 (RDSO_B_10155_6 to 10155-10_.pdf) | structural design details | 5.0 | partly read set: nothing on it was checked against the drawing | NO |
| RDSO/B-10155/7 (overview only, not confirmed on a crop) | 2 (RDSO_B_10155_6 to 10155-10_.pdf) | structural design details | 6.0 | partly read set: nothing on it was checked against the drawing | NO |

### Haunch B x B (by CLS or cht)

| From (m) | To (m) | Size (mm) | Printed |
|---|---|---|---|
| - | 3.0 | 200 | LESS THAN 3 m -> 200 X200 mm |
| 3.0 | 3.5 | 300 | >= 3.0 m and <3.5m -> 300 X300 mm |
| 3.5 | 4.0 | 350 | >= 3.5 m and <4.0m -> 350 X350 mm |
| 4.0 | 4.5 | 400 | >= 4.0 m and <4.5m -> 400X400 mm |
| 4.5 | 5.0 | 450 | >= 4.5 m and < 5.0m -> 450 X450 mm |
| 5.0 | 5.5 | 500 | >= 5.0 m and < 5.5m -> 500 X500 mm |
| 5.5 | 6.0 | 550 | >= 5.5 m and < 6.0m -> 550 X550 mm |
| 6.0 | - | 600 | >= 6.0m -> 600 X600 mm |

### Depth of key DK at bottom slab

- UPTO 900mm -> 1200mm
- GREATER THAN 900mm -> tsb + 300mm

### Relations from the notations (derived)

- `RDSO-RCC-BOX-10155:ht`: ht = cht + wearing course thickness (ht is the height of box including wearing course; cht the clear height above the wearing course)
- `RDSO-RCC-BOX-10155:tht`: tht = ht + tst + tsb
- `RDSO-RCC-BOX-10155:ols`: OLS = CLS + 2 x tsv (single cell)
- `RDSO-RCC-BOX-10155:tbl`: TBL = UBL + DBL

### Notes (verbatim, general arrangement)

1. ALL DIMENSIONS ARE IN MILLIMETER UNLESS OTHERWISE SPECIFIED.
2. THIS DRAWING IS SUITABLE FOR DOUBLE LINE TRACK UPTO 4 DEGREE CURVATURE ONLY. [red: '10' written above, '4' struck; ALT 5]
3. MINIMUM SPACING OF TRACKS IS ASSUMED AS 5.3m IN DESIGN WHICH MAY BE SUITABLY INCREASED AS PER REQUIREMENTS OF CURVE.
4. PREPARATION OF BED BELOW 150mm THICK BASE COURSE SHOULD BE BASED ON ACTUAL SITE CONDITION IN ORDER TO ACHIEVE THE ADEQUATE BEARING CAPACITY REQUIRED TO WITHSTAND THE FOUNDATION PRESSURE GIVEN IN TABLE OF REFERENCE DRAWINGS.
5. REINFORCEMENT DETAILS, SLAB THICKNESS DETAILS AND FOUNDATION PRESSURE FOR VARIOUS FILL HEIGHTS HAVE BEEN GIVEN IN REFERENCE DRAWINGS. THICKNESSES OF TOP SLAB, BOTTOM SLAB AND VERTICAL WALLS HAVE BEEN KEPT UNIFORM.
6. THIS DESIGN IS SUITABLE FOR 25t LOADING-2008.
7. [struck through in red] HSD/TMT BARS CONFORMING TO IS:1786-2008 SHALL BE USED AS REINFORCEMENT. [red ALT 2 replacement, partly read: 'ALL REINFORCEMENT STEEL SHALL BE OF HIGH STRENGTH [...] / HIGHER GRADE REINFORCEMENT CONFORMING TO IS:1[...] / HYSD STEEL BARS HAVING MINIMUM ELONGATION OF 1[...] / REQUIREMENTS OF IS:1786 SHALL BE USED.' The elongation value is cut at a tile edge and is not recorded.]
8. DESIGN CRITERIA IS BASED ON FOLLOWING IRS CODES: i) IRS BRIDGE RULES ii) IRS CONCRETE BRIDGE CODE iii) IRS BRIDGE SUBSTRUCTURE & FOUNDATION CODE
9. LAPPING OF BARS SHOULD BE MINIMISED AND STAGGERED WHEREVER NECESSARY. MINIMUM LENGTH OF LAP SHALL BE AS GIVEN IN IRS CONCRETE BRIDGE CODE FOR TOR STEEL.
10. [struck through in red] BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUBSTRUCTURES & FOUNDATION CODE. [restored in red by ALT 4]
11. ALL R.C.C SURFACES COMING IN CONTACT WITH SOIL SHOULD BE PAINTED WITH BITUMEN OR COALTAR OF APPROVED QUALITY @ 1.464 KG/SQM.
12. CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm.
13. SAMPLE DETAILS OF WING WALL AND RETURN WALL ARE GIVEN. HOWEVER, WING WALL AND RETURN WALL SHOULD BE DESIGNED SUITABLY BY ZONAL RAILWAYS AS PER SITE CONDITIONS.
14. i) BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS BALLAST RETAINING WALL, DESIGNED SUITABLY.
15. [struck through in red, replaced by ALT 2] IN CASE OF ERODIBLE SOILS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS) WITH A MINIMUM DEPTH BELOW FLOOR LEVEL OF 2.0m FOR CURTAIN WALL AND 2.5m FOR DROP WALL. MINIMUM WIDTH OF FOUNDATION FOR CURTAIN WALL/DROP WALL SHOULD BE 900mm. [ALT 2 red text: 'IN CASE OF ERODIBLE SOILS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS). SCHEMATIC CURTAIN/DROP WALL IS GIVEN.']
16. TOLERANCE SHALL BE FOLLOWED AS PER IRS CONCRETE BRIDGE CODE.
17. M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER.
18. [struck through in red; replaced by ALT 2] BED SLOPE SHALL BE ADJUSTED AS PER SITE CONDITIONS BY COMPETENT AUTHORITY. IT SHOULD BE KEPT MINIMUM 1 IN 100. [ALT 2 red text: 'BED SLOPE SHALL BE ADJUSTED AS PER SITE CONDITIONS BY COMPETENT AUTHORITY.']
19. FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED.
20. WEEP HOLES SHALL BE OF 75/100 DIA PVC/AC PIPES STAGGERED @ 1000 C/C ABOVE LOW WATER LEVEL IN BOTH WING WALL/RETURN WALL AND EARTH RETAINER OF BOX.
21. BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN.
22. DEPTH OF KEY AT BOTTOM SLAB, DK SHOULD BE PROVIDED AS GIVEN BELOW: [table: UPTO 900mm -> 1200mm; GREATER THAN 900mm -> tsb + 300mm]
23. [red, ALT 5] NO SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN.

### Design basis (as printed)

- **loading**: 25t LOADING - 2008 (title block; note 6)
- **track curvature**: UPTO 4 DEGREE, with red 10 written above the struck 4 (ALT 5) (title; note 2)
- **minimum track spacing**: 5.3m (assumed) (note 3; 5300(min.) in the elevation)
- **concrete grade**: M-35 for span or height >= 4 m; M-30 for < 4 m (note 17)
- **reinforcement steel**: HSD/TMT bars to IS:1786-2008 (note 7, struck); ALT 2 replaces with HYSD bars to IS:1786 (note 7)
- **clear cover**: 50mm (note 12)
- **base course**: 150mm TH. PCC BASE COURSE (cross section; note 4)
- **wearing course**: 150mm TH. WEARING COURSE (cross section; elevation)
- **ballast cushion**: 350mm (considered in design) (note 21)
- **bed slope**: 1 IN 100 (MIN.) (sectional elevation; note 18 (ALT 2))
- **backfill slope**: SLOPE NOT STEEPER THAN 1:1 (cross section)
- **bank slope**: SLOPE 2:1 (sectional elevation)
- **stone pitching**: 300 TH. STONE PITCHING WITH CEMENT GROUTING (sectional elevation)
- **weep holes**: 75/100 DIA PVC/AC pipes at 1000 c/c above low water level (note 20; typical details A)
- **key depth DK**: UPTO 900mm tsb -> 1200mm; GREATER THAN 900mm tsb -> tsb + 300mm (note 22)
- **fill heights in reference drawings**: 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0 m; row 10 for 0.0 to 10.0 m (reference drawings table)
- **haunch size**: 200X200 to 600X600 mm by cht range (table for B x B haunch)
- **minimum foundation width (curtain/drop wall)**: 900mm (struck, note 15) (note 15)
- **depth below floor (curtain / drop wall)**: 2.0m / 2.5m (struck, note 15) (note 15)
- **coating of RCC in contact with soil**: bitumen or coal tar @ 1.464 KG/SQM (note 11)
- **approval / status**: PROVISIONAL; DATE: 22.05.2013; ED/STRUCTURES approval (blue 22/5/13) (title block)
- **boulder fill**: 600 (mm) well hand packed boulders (struck by ALT 3) (cross section)

### Schedule RDSO/B-10155/1 — fill 0.0 m (page 2, RDSO_B_10155 to 10155-5 .pdf)

Verification: checked against the displayed drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 200.0 | explicit | 2mX1.8m g-row text in the table: printed as 'BARELL' (sic). |
| 2mX2m | 350.0 | 350.0 | 350.0 | 200.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 150.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 160.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 160.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 170.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 180.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 190.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 140.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 150.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 160.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 170.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 180.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 180.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX6m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 210.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 220.0 | explicit |  |
| 5mX4m | 550.0 | 550.0 | 550.0 | 220.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 260.0 | explicit |  |
| 6mX3m | 600.0 | 600.0 | 600.0 | 190.0 | explicit |  |
| 6mX3.5m | 650.0 | 650.0 | 650.0 | 200.0 | explicit |  |
| 6mX4m | 650.0 | 650.0 | 650.0 | 210.0 | explicit |  |
| 6mX4.5m | 650.0 | 650.0 | 650.0 | 220.0 | explicit |  |
| 6mX5m | 650.0 | 650.0 | 650.0 | 220.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 240.0 | explicit |  |

### Schedule RDSO/B-10155/2 — fill 1.0 m (page 3, RDSO_B_10155 to 10155-5 .pdf)

Verification: checked against the displayed drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 170.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 170.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 180.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 190.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 200.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX4m | 400.0 | 400.0 | 400.0 | 230.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 240.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 270.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 180.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 250.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 180.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 190.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX4m | 550.0 | 550.0 | 550.0 | 210.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 6mX3m | 600.0 | 600.0 | 600.0 | 180.0 | explicit |  |
| 6mX3.5m | 650.0 | 650.0 | 650.0 | 190.0 | explicit |  |
| 6mX4m | 650.0 | 650.0 | 650.0 | 200.0 | explicit |  |
| 6mX4.5m | 650.0 | 650.0 | 650.0 | 210.0 | explicit |  |
| 6mX5m | 650.0 | 650.0 | 650.0 | 210.0 | explicit |  |
| 6mX6m | 650.0 | 650.0 | 650.0 | 230.0 | explicit |  |

### Schedule RDSO/B-10155/3 — fill 2.0 m (page 4, RDSO_B_10155 to 10155-5 .pdf)

Verification: checked against the displayed drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 180.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX4m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 230.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 240.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 260.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 180.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 250.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 180.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 190.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX4m | 550.0 | 550.0 | 550.0 | 210.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 6mX3m | 600.0 | 600.0 | 600.0 | 180.0 | explicit |  |
| 6mX3.5m | 650.0 | 650.0 | 650.0 | 190.0 | explicit |  |
| 6mX4m | 650.0 | 650.0 | 650.0 | 200.0 | explicit |  |
| 6mX4.5m | 650.0 | 650.0 | 650.0 | 210.0 | explicit |  |
| 6mX5m | 650.0 | 650.0 | 650.0 | 220.0 | explicit |  |
| 6mX6m | 700.0 | 700.0 | 700.0 | 240.0 | explicit |  |

### Schedule RDSO/B-10155/4 — fill 3.0 m (page 5, RDSO_B_10155 to 10155-5 .pdf)

Verification: checked against the displayed drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 180.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 180.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 210.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 220.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 230.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 240.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 270.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 180.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 250.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 190.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 6mX3m | 650.0 | 650.0 | 650.0 | 190.0 | explicit |  |
| 6mX3.5m | 650.0 | 650.0 | 650.0 | 200.0 | explicit |  |
| 6mX4m | 650.0 | 650.0 | 650.0 | 210.0 | explicit |  |
| 6mX4.5m | 650.0 | 650.0 | 650.0 | 220.0 | explicit |  |
| 6mX5m | 650.0 | 650.0 | 650.0 | 220.0 | explicit |  |
| 6mX6m | 700.0 | 700.0 | 700.0 | 240.0 | explicit |  |

### Schedule RDSO/B-10155/5 — fill 4.0 m (page 6, RDSO_B_10155 to 10155-5 .pdf)

Verification: checked against the displayed drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 210.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 220.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 230.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 240.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 240.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 270.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 240.0 | explicit |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 270.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 260.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 210.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 220.0 | explicit |  |
| 6mX4m | 700.0 | 700.0 | 700.0 | 220.0 | explicit |  |
| 6mX4.5m | 700.0 | 700.0 | 700.0 | 230.0 | explicit |  |
| 6mX5m | 700.0 | 700.0 | 700.0 | 240.0 | explicit |  |
| 6mX6m | 700.0 | 700.0 | 700.0 | 250.0 | explicit |  |

### Schedule RDSO/B-10155/6 — fill 5.0 m (page 1, RDSO_B_10155_6 to 10155-10_.pdf) — NOT USABLE

Verification: partly read set: nothing on it was checked against the drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 220.0 | unverified |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 220.0 | unverified |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 230.0 | unverified |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 240.0 | unverified |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 250.0 | unverified |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 260.0 | unverified | Top header line 'SPAN LENGTH X BOX HEIGHT CONFIGURATION' over row 1 columns 6 to 8 (2mX4.0m, 3mX1.8m, 3mX2.0m) is smeared by scan overprint; the configuration names beneath are clear. |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 200.0 | unverified | Top header line 'SPAN LENGTH X BOX HEIGHT CONFIGURATION' over row 1 columns 6 to 8 (2mX4.0m, 3mX1.8m, 3mX2.0m) is smeared by scan overprint; the configuration names beneath are clear. |
| 3mX2m | 400.0 | 400.0 | 400.0 | 200.0 | unverified | Top header line 'SPAN LENGTH X BOX HEIGHT CONFIGURATION' over row 1 columns 6 to 8 (2mX4.0m, 3mX1.8m, 3mX2.0m) is smeared by scan overprint; the configuration names beneath are clear. |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 220.0 | unverified |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 220.0 | unverified |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 230.0 | unverified |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 240.0 | unverified |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 250.0 | unverified |  |
| 3mX5m | 500.0 | 500.0 | 500.0 | 260.0 | unverified |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 290.0 | unverified |  |
| 4mX2m | 500.0 | 500.0 | 500.0 | 210.0 | unverified |  |
| 4mX2.5m | 500.0 | 500.0 | 500.0 | 210.0 | unverified |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 220.0 | unverified |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 230.0 | unverified |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 240.0 | unverified |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 240.0 | unverified |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 260.0 | unverified |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 280.0 | unverified |  |
| 5mX2.5m | 650.0 | 650.0 | 650.0 | 220.0 | unverified |  |
| 5mX3m | 650.0 | 650.0 | 650.0 | 230.0 | unverified |  |
| 5mX3.5m | 650.0 | 650.0 | 650.0 | 230.0 | unverified |  |
| 5mX4m | 650.0 | 650.0 | 650.0 | 240.0 | unverified |  |
| 5mX4.5m | 650.0 | 650.0 | 650.0 | 250.0 | unverified |  |
| 5mX5m | 650.0 | 650.0 | 650.0 | 260.0 | unverified |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 270.0 | unverified |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 220.0 | unverified | Table 5 (6mX3.0m to 6mX6.0m), row h, columns 6mX4.0m and 6mX5.0m: the leading digit of '10mm DIA @ 100mm' is clipped at the left cell edge and was not zoomed; read as 10mm (the same value in the other columns of the row). Columns 6mX3.5m, 6mX4.5m and 6mX6.0m were checked in zoom crops Z5h_c2, Z5h_c4, Z5h_c6 and read as 10mm DIA. |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 230.0 | unverified | Table 5 (6mX3.0m to 6mX6.0m), row h, columns 6mX4.0m and 6mX5.0m: the leading digit of '10mm DIA @ 100mm' is clipped at the left cell edge and was not zoomed; read as 10mm (the same value in the other columns of the row). Columns 6mX3.5m, 6mX4.5m and 6mX6.0m were checked in zoom crops Z5h_c2, Z5h_c4, Z5h_c6 and read as 10mm DIA. |
| 6mX4m | 700.0 | 700.0 | 700.0 | 240.0 | unverified | Table 5 (6mX3.0m to 6mX6.0m), row h, columns 6mX4.0m and 6mX5.0m: the leading digit of '10mm DIA @ 100mm' is clipped at the left cell edge and was not zoomed; read as 10mm (the same value in the other columns of the row). Columns 6mX3.5m, 6mX4.5m and 6mX6.0m were checked in zoom crops Z5h_c2, Z5h_c4, Z5h_c6 and read as 10mm DIA. |
| 6mX4.5m | 700.0 | 700.0 | 700.0 | 250.0 | unverified | Table 5 (6mX3.0m to 6mX6.0m), row h, columns 6mX4.0m and 6mX5.0m: the leading digit of '10mm DIA @ 100mm' is clipped at the left cell edge and was not zoomed; read as 10mm (the same value in the other columns of the row). Columns 6mX3.5m, 6mX4.5m and 6mX6.0m were checked in zoom crops Z5h_c2, Z5h_c4, Z5h_c6 and read as 10mm DIA. |
| 6mX5m | 750.0 | 750.0 | 750.0 | 260.0 | unverified | Table 5 (6mX3.0m to 6mX6.0m), row h, columns 6mX4.0m and 6mX5.0m: the leading digit of '10mm DIA @ 100mm' is clipped at the left cell edge and was not zoomed; read as 10mm (the same value in the other columns of the row). Columns 6mX3.5m, 6mX4.5m and 6mX6.0m were checked in zoom crops Z5h_c2, Z5h_c4, Z5h_c6 and read as 10mm DIA. |
| 6mX6m | 800.0 | 800.0 | 800.0 | 280.0 | unverified | Table 5 (6mX3.0m to 6mX6.0m), row h, columns 6mX4.0m and 6mX5.0m: the leading digit of '10mm DIA @ 100mm' is clipped at the left cell edge and was not zoomed; read as 10mm (the same value in the other columns of the row). Columns 6mX3.5m, 6mX4.5m and 6mX6.0m were checked in zoom crops Z5h_c2, Z5h_c4, Z5h_c6 and read as 10mm DIA. |

### Schedule RDSO/B-10155/7 (overview only, not confirmed on a crop) — fill 6.0 m (page 2, RDSO_B_10155_6 to 10155-10_.pdf) — NOT USABLE

Verification: partly read set: nothing on it was checked against the drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 230.0 | unverified |  |

Unclear items recorded by the extraction: 44; not-read items: 37 (full list in the JSON).

## RDSO/B-10157 (RDSO-RCC-BOX-10157)

Source: 10157 to10157-5.pdf, 10157-6to 10157-10.pdf. Title: R.D.S.O. / STANDARD DRAWING OF SINGLE BOX CULVERT FOR DOUBLE LINE TRACK CURVED UPTO 4 deg (4 struck through; 10 deg in red, ALT. 5) (GENERAL ARRANGEMENT) DFC LOADING (32.5t AXLE LOAD). Date: DATE: 14.08.2013.

### Applicability (as printed)

- **structure**: single-cell RCC box culvert  (title)
- **track**: double line  (title / note 2)
- **loading**: DFC loading (32.5 t axle load)  (title)
- **curvature**:  — THIS DRAWING IS SUITABLE FOR DOUBLE LINE TRACK UPTO 4 DEGREE CURVATURE ONLY. (printed 4 struck through in red; 10 written above in red; ALT. 5) (note 2)
- **skew**: no skew angle considered in the design — (red, ALT. 5) NO SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN. (note 23)
- **min_track_spacing_m**: 6.0 — MINIMUM SPACING OF TRACKS IS ASSUMED AS 6.0m IN DESIGN WHICH MAY BE SUITABLY INCREASED AS PER REQUIREMENTS OF CURVE. (note 3)
- **ballast_cushion_mm**: 350.0 — BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN. (note 21)
- **clear_cover_mm**: 50.0 — CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm. (note 12)
- **config_label_meaning**:   (not stated on the sheets read)
- **intermediate_configuration_rule**:  — FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED. (note 19)
- **barrel_length_rule**:  — i) BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS EARTH RETAINING WALL, DESIGNED SUITABLY. (note 14)
- **concrete_grade_rule**:  — M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER. (note 17)

### Sheets

| Drawing | Page | Kind | Fill (m) | Verification | Usable |
|---|---|---|---|---|---|
| RDSO/B-10157 | 1 (10157 to10157-5.pdf) | general arrangement | - | checked against the displayed drawing | yes |
| RDSO/B-10157/1 | 2 (10157 to10157-5.pdf) | structural design details | 0.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10157/2 | 3 (10157 to10157-5.pdf) | structural design details | 1.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10157/3 | 4 (10157 to10157-5.pdf) | structural design details | 2.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10157/4 | 5 (10157 to10157-5.pdf) | structural design details | 2.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10157/5 | 6 (10157 to10157-5.pdf) | structural design details | 3.0 | transcribed by eye from displayed tiles; not re-checked | yes |
| RDSO/B-10157/6 | 1 (10157-6to 10157-10.pdf) | structural design details | 4.0 | the extraction says not to use this page until it is re-read | NO |
| RDSO/B-10157/7 | 2 (10157-6to 10157-10.pdf) | structural design details | 5.0 | partly read set: nothing on it was checked against the drawing | NO |

### Haunch B x B (by CLS or cht)

| From (m) | To (m) | Size (mm) | Printed |
|---|---|---|---|
| - | 3.0 | 200 | LESS THAN 3 m -> 200 X200 mm |
| 3.0 | 3.5 | 300 | >= 3.0 m and < 3.5m -> 300 X300 mm |
| 3.5 | 4.0 | 350 | >= 3.5 m and < 4.0m -> 350 X350 mm |
| 4.0 | 4.5 | 400 | >= 4.0 m and < 4.5m -> 400X400 mm |
| 4.5 | 5.0 | 450 | >= 4.5 m and < 5.0m -> 450 X450 mm |
| 5.0 | 5.5 | 500 | >= 5.0 m and < 5.5m -> 500 X500 mm |
| 5.5 | 6.0 | 550 | >= 5.5 m and < 6.0m -> 550 X550 mm |
| 6.0 | - | 600 | >= 6.0m -> 600 X600 mm |

### Depth of key DK at bottom slab

- UPTO 900mm -> 1200mm
- GREATER THAN 900mm -> tsb + 300mm

### Relations from the notations (derived)

- `RDSO-RCC-BOX-10157:ht`: ht = cht + wearing course thickness (ht is the height of box including wearing course; cht the clear height above the wearing course)
- `RDSO-RCC-BOX-10157:tht`: tht = ht + tst + tsb
- `RDSO-RCC-BOX-10157:ols`: OLS = CLS + 2 x tsv (single cell)
- `RDSO-RCC-BOX-10157:tbl`: TBL = UBL + DBL

### Notes (verbatim, general arrangement)

1. ALL DIMENSIONS ARE IN MILLIMETER UNLESS OTHERWISE SPECIFIED. (ALT. 5 red circle at the end)
2. THIS DRAWING IS SUITABLE FOR DOUBLE LINE TRACK UPTO 4 DEGREE CURVATURE ONLY. (printed 4 struck through in red; 10 written above in red; ALT. 5)
3. MINIMUM SPACING OF TRACKS IS ASSUMED AS 6.0m IN DESIGN WHICH MAY BE SUITABLY INCREASED AS PER REQUIREMENTS OF CURVE.
4. PREPARATION OF BED BELOW 150mm THICK BASE COURSE SHOULD BE BASED ON ACTUAL SITE CONDITION IN ORDER TO ACHIEVE THE ADEQUATE BEARING CAPACITY REQUIRED TO WITHSTAND THE FOUNDATION PRESSURE GIVEN IN TABLE OF REFERENCE DRAWINGS.
5. REINFORCEMENT DETAILS, SLAB THICKNESS DETAILS AND FOUNDATION PRESSURE FOR VARIOUS FILL HEIGHTS HAVE BEEN GIVEN IN REFERENCE DRAWINGS . THICKNESSES OF TOP SLAB, BOTTOM SLAB AND VERTICAL WALLS HAVE BEEN KEPT UNIFORM.
6. THIS DESIGN IS SUITABLE FOR DFC LOADING.
7. (struck through in red) HSD/TMT BARS (Fe 415/Fe 500D) CONFORMING TO IS:1786-2008 SHALL BE USED AS REINFORCEMENT. Replaced in red handwriting (ALT. 2): ALL REINFORCEMENT STEEL SHALL BE OF HIGH STRENGTH DEFORMED (HSD)/TMT BARS, Fe 415 AND HIGHER GRADE REINFORCEMENT CONFORMING TO IS:1786-2008. FOR SEISMIC ZONES III, IV AND V HYSD STEEL BARS HAVING MINIMUM ELONGATION OF 14.5 PERCENT AND CONFORMING TO OTHER REQUIREMENTS OF IS:1786 SHALL BE USED.
8. DESIGN CRITERIA IS BASED ON FOLLOWING IRS CODES: i) IRS BRIDGE RULES ii) IRS CONCRETE BRIDGE CODE iii) IRS BRIDGE SUBSTRUCTURES & FOUNDATION CODE
9. LAPPING OF BARS SHOULD BE MINIMISED AND STAGGERED WHEREVER NECESSARY. MINIMUM LENGTH OF LAP SHALL BE AS GIVEN IN IRS CONCRETE BRIDGE CODE FOR TOR STEEL. (ALT. 3 red circle)
10. (struck through) BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUB-STRUCTURES & FOUNDATION CODE. Replaced in red (ALT. 4): 10. BACK FILL MATERIAL SHOULD BE AS PER CLAUSE 7.5 OF IRS BRIDGE SUB-STRUCTURES & FOUNDATION CODE. NOTE NO. 10 IS RESTORED.
11. ALL R.C.C SURFACES COMING IN CONTACT WITH SOIL SHOULD BE PAINTED WITH BITUMEN OR COALTAR OF APPROVED QUALITY @ 1.464 KG/SQM.
12. CLEAR COVER FOR REINFORCING BARS SHOULD BE 50mm.
13. SAMPLE DETAILS OF WING WALL AND RETURN WALL ARE GIVEN. HOWEVER, WING WALL AND RETURN WALL SHOULD BE DESIGNED SUITABLY BY ZONAL RAILWAYS AS PER SITE CONDITIONS.
14. i) BARREL LENGTH OF BOX CULVERT SHALL BE DECIDED BASED ON FILL HEIGHT ON THE BOX AS PER CROSS SECTION SHOWN. ii) IF BARREL LENGTH IS TO BE CURTAILED DUE TO SOME REASONS, THEN END OF BOX CAN BE PROJECTED UP AS EARTH RETAINING WALL, DESIGNED SUITABLY.
15. (struck through in red, with red asterisk) IN CASE OF ERODIBLE SOILS, FLOORING SHALL BE ENCLOSED BY SUITABLY DESIGNED CURTAIN WALL AND DROP WALL (TIED TO THE WING WALLS) WITH A MINIMUM DEPTH BELOW FLOOR LEVEL OF 2.0m FOR CURTAIN WALL AND 2.5m FOR DROP WALL. MINIMUM WIDTH OF FOUNDATION FOR CURTAIN WALL/DROP WALL SHOULD BE 900mm.
16. TOLERANCE SHALL BE FOLLOWED AS PER IRS CONCRETE BRIDGE CODE.
17. M-35 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX GREATER THAN OR EQUAL TO 4 METER. M-30 GRADE CONCRETE SHALL BE USED FOR THE SPAN OR HEIGHT OF THE BOX LESS THAN 4 METER.
18. SUITABLE BED SLOPE SHALL BE PROVIDED AND ADJUSTED AS PER SITE CONDITIONS.
19. FOR INTERMEDIATE SPAN/HEIGHTS, STRUCTURAL DESIGN DETAILS OF IMMEDIATELY HIGHER SPAN/HEIGHTS CONFIGURATION CAN BE ADOPTED.
20. WEEP HOLES SHALL BE OF 75/100 DIA PVC/AC PIPES STAGGERED @ 1000 c/c ABOVE LOW WATER LEVEL IN BOTH WING WALL/RETURN WALL AND EARTH RETAINER OF BOX.
21. BALLAST CUSHION OF 350mm HAS BEEN CONSIDERED IN DESIGN.
22. DEPTH OF KEY AT BOTTOM SLAB, DK SHOULD BE PROVIDED AS GIVEN BELOW: (table: UPTO 900mm -> 1200mm; GREATER THAN 900mm -> tsb + 300mm)
23. (red, ALT. 5) NO SKEW ANGLE HAS BEEN CONSIDERED IN THE DESIGN.

### Design basis (as printed)

- **loading**: DFC LOADING (32.5t AXLE LOAD) (title block; note 6)
- **track**: DOUBLE LINE TRACK, curved UPTO 4 degree (printed, struck); 10 degree written in red (ALT. 5) (title block; note 2)
- **minimum track spacing**: 6.0m (design); 6000 (min.) on the sectional elevation (note 3; SECTIONAL ELEVATION AT X-Y)
- **concrete grade**: M-35 for span or height >= 4 m; M-30 for < 4 m (note 17); M-20 for PCC wearing course (note 17; CROSS SECTION; wearing course label)
- **steel**: HSD/TMT Fe 415 and higher, IS:1786-2008; seismic zones III, IV, V: HYSD with minimum elongation 14.5 percent (ALT. 2 in red; original Fe 500D struck through) (note 7)
- **clear cover**: 50mm (note 12)
- **base course**: 150mm TH. PCC BASE COURSE (note 4; SECTIONAL ELEVATION AT X-Y)
- **wearing course**: 150mm TH. PCC WEARING COURSE (M-20) (SECTIONAL ELEVATION AT X-Y; CROSS SECTION)
- **ballast cushion**: 350mm (note 21)
- **stone pitching**: 300 TH. STONE PITCHING WITH CEMENT GROUTING (SECTIONAL ELEVATION AT X-Y)
- **bank slope**: SLOPE 2:1 (SECTIONAL ELEVATION AT X-Y)
- **key DK**: UPTO 900mm -> 1200mm; GREATER THAN 900mm -> tsb + 300mm (note 22)
- **haunch size**: 200X200 mm to 600X600 mm by CLS or cht (table) (TABLE FOR B X B HAUNCH)
- **weep holes**: 75/100 DIA PVC/AC pipes staggered @ 1000 c/c above LWL (note 20; TYPICAL DETAILS AT A)
- **wall stem and cap**: stem 250; cap 75 (top 75 | 250 | 75); return wall height dimension 750 (SECTION OF RETURN WALL; WING WALL)
- **bar spacing (walls)**: MAX. SPACING 200mm c/c (walls); BARS OF 10mm DIA @ 300mm c/c MAXIMUM (key) (WING WALL; SECTION OF RETURN WALL; TYPICAL DETAILS AT B)
- **design codes**: IRS Bridge Rules; IRS Concrete Bridge Code; IRS Bridge Substructures & Foundation Code (clause 7.5 for backfill) (note 8; note 10)
- **bed preparation**: based on site condition; foundation pressure from the reference drawings table (note 4)
- **backfill slope**: printed label ending '...AN 1:1' (start cut) (CROSS SECTION OF R.C.C BOX)

### Schedule RDSO/B-10157/1 — fill 0.0 m (page 2, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 260.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 270.0 | explicit |  |
| 3mX1.8m | 350.0 | 350.0 | 350.0 | 170.0 | explicit |  |
| 3mX2m | 350.0 | 350.0 | 350.0 | 170.0 | explicit |  |
| 3mX2.5m | 350.0 | 350.0 | 350.0 | 180.0 | explicit |  |
| 3mX3m | 350.0 | 350.0 | 350.0 | 190.0 | explicit |  |
| 3mX3.5m | 350.0 | 350.0 | 350.0 | 200.0 | explicit |  |
| 3mX4m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 250.0 | explicit |  |
| 4mX2m | 400.0 | 400.0 | 400.0 | 150.0 | explicit |  |
| 4mX2.5m | 400.0 | 400.0 | 400.0 | 160.0 | explicit |  |
| 4mX3m | 400.0 | 400.0 | 400.0 | 170.0 | explicit |  |
| 4mX3.5m | 450.0 | 450.0 | 450.0 | 180.0 | explicit |  |
| 4mX4m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX4.5m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX5m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX6m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 160.0 | explicit |  |
| 5mX3m | 550.0 | 550.0 | 550.0 | 160.0 | explicit |  |
| 5mX3.5m | 550.0 | 550.0 | 550.0 | 170.0 | explicit |  |
| 5mX4m | 550.0 | 550.0 | 550.0 | 180.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 190.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 200.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 220.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 220.0 | explicit |  |
| 6mX4m | 750.0 | 750.0 | 750.0 | 240.0 | explicit |  |
| 6mX4.5m | 750.0 | 750.0 | 750.0 | 240.0 | explicit |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 250.0 | explicit |  |
| 6mX6m | 750.0 | 750.0 | 750.0 | 270.0 | explicit |  |

### Schedule RDSO/B-10157/4 — fill 0.0 m (page 5, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 1mX1.2m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX1.2m | 350.0 | 350.0 | 350.0 | 150.0 | explicit |  |

### Schedule RDSO/B-10157/2 — fill 1.0 m (page 3, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 190.0 | explicit | Band 1 2mX1.8m 'row 3' pressure: printed as 190 kN/m2 in b1_t1 (left part of the cell cut in b1_t2 as 90); 190 taken from b1_t1. |
| 2mX2m | 350.0 | 350.0 | 350.0 | 190.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 200.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 210.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 220.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 230.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 160.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 160.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 170.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 170.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 180.0 | explicit |  |
| 3mX4m | 400.0 | 400.0 | 400.0 | 190.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX5m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 240.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 240.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 270.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 250.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 200.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 210.0 | explicit |  |
| 6mX4m | 750.0 | 750.0 | 750.0 | 220.0 | explicit |  |
| 6mX4.5m | 750.0 | 750.0 | 750.0 | 230.0 | explicit |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 230.0 | explicit |  |
| 6mX6m | 750.0 | 750.0 | 750.0 | 250.0 | explicit |  |

### Schedule RDSO/B-10157/4 — fill 1.0 m (page 5, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 1mX1.2m | 350.0 | 350.0 | 350.0 | 180.0 | explicit |  |
| 2mX1.2m | 350.0 | 350.0 | 350.0 | 130.0 | explicit |  |

### Schedule RDSO/B-10157/3 — fill 2.0 m (page 4, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 260.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 270.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 280.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 290.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX3.5m | 400.0 | 400.0 | 400.0 | 230.0 | explicit |  |
| 3mX4m | 400.0 | 400.0 | 400.0 | 240.0 | explicit |  |
| 3mX4.5m | 400.0 | 400.0 | 400.0 | 240.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 260.0 | explicit |  |
| 3mX6m | 500.0 | 500.0 | 500.0 | 280.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 240.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 260.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 190.0 | explicit |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 200.0 | explicit |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 250.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 200.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 210.0 | explicit |  |
| 6mX4m | 750.0 | 750.0 | 750.0 | 220.0 | explicit |  |
| 6mX4.5m | 750.0 | 750.0 | 750.0 | 230.0 | explicit |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 240.0 | explicit |  |
| 6mX6m | 750.0 | 750.0 | 750.0 | 250.0 | explicit |  |

### Schedule RDSO/B-10157/4 — fill 2.0 m (page 5, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 1mX1.2m | 350.0 | 350.0 | 350.0 | 180.0 | explicit |  |
| 2mX1.2m | 350.0 | 350.0 | 350.0 | 150.0 | explicit |  |

### Schedule RDSO/B-10157/5 — fill 3.0 m (page 6, 10157 to10157-5.pdf)

Verification: transcribed by eye from displayed tiles; not re-checked.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 240.0 | explicit |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 250.0 | explicit |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 260.0 | explicit |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 270.0 | explicit |  |
| 2mX4m | 350.0 | 350.0 | 350.0 | 280.0 | explicit |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 200.0 | explicit |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX2.5m | 400.0 | 400.0 | 400.0 | 210.0 | explicit |  |
| 3mX3m | 400.0 | 400.0 | 400.0 | 220.0 | explicit |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 230.0 | explicit |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 240.0 | explicit |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 250.0 | explicit |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 260.0 | explicit |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 290.0 | explicit |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 190.0 | explicit |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 200.0 | explicit |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 210.0 | explicit |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 220.0 | explicit |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 230.0 | explicit |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 240.0 | explicit |  |
| 4mX5m | 500.0 | 500.0 | 500.0 | 240.0 | explicit |  |
| 4mX6m | 550.0 | 550.0 | 550.0 | 260.0 | explicit |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 200.0 | explicit |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 210.0 | explicit |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 220.0 | explicit |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 230.0 | explicit |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 240.0 | explicit |  |
| 5mX6m | 600.0 | 600.0 | 600.0 | 260.0 | explicit |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 210.0 | explicit |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 220.0 | explicit |  |
| 6mX4m | 750.0 | 750.0 | 750.0 | 230.0 | explicit |  |
| 6mX4.5m | 750.0 | 750.0 | 750.0 | 240.0 | explicit |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 250.0 | explicit |  |
| 6mX6m | 750.0 | 750.0 | 750.0 | 260.0 | explicit |  |

### Schedule RDSO/B-10157/6 — fill 4.0 m (page 1, 10157-6to 10157-10.pdf) — NOT USABLE

Verification: the extraction says not to use this page until it is re-read.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 240.0 | unverified |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 240.0 | unverified |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 250.0 | unverified |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 260.0 | unverified |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 270.0 | unverified |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 280.0 | unverified |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 210.0 | unverified |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 210.0 | unverified |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 220.0 | unverified |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 230.0 | unverified |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 240.0 | unverified |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 240.0 | unverified |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 250.0 | unverified |  |
| 3mX5m | 450.0 | 450.0 | 450.0 | 260.0 | unverified |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 290.0 | unverified |  |
| 4mX2m | 450.0 | 450.0 | 450.0 | 200.0 | unverified |  |
| 4mX2.5m | 450.0 | 450.0 | 450.0 | 210.0 | unverified |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 220.0 | unverified |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 230.0 | unverified |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 230.0 | unverified |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 240.0 | unverified |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 260.0 | unverified |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 280.0 | unverified |  |
| 5mX2.5m | 550.0 | 550.0 | 550.0 | 210.0 | unverified |  |
| 5mX3m | 600.0 | 600.0 | 600.0 | 220.0 | unverified |  |
| 5mX3.5m | 600.0 | 600.0 | 600.0 | 230.0 | unverified |  |
| 5mX4m | 600.0 | 600.0 | 600.0 | 240.0 | unverified |  |
| 5mX4.5m | 600.0 | 600.0 | 600.0 | 240.0 | unverified |  |
| 5mX5m | 600.0 | 600.0 | 600.0 | 250.0 | unverified |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 270.0 | unverified |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 220.0 | unverified |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 230.0 | unverified |  |
| 6mX4m | 750.0 | 750.0 | 750.0 | 240.0 | unverified |  |
| 6mX4.5m | 750.0 | 750.0 | 750.0 | 250.0 | unverified |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 250.0 | unverified |  |
| 6mX6m | 750.0 | 750.0 | 750.0 | 270.0 | unverified |  |

### Schedule RDSO/B-10157/7 — fill 5.0 m (page 2, 10157-6to 10157-10.pdf) — NOT USABLE

Verification: partly read set: nothing on it was checked against the drawing.

| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |
|---|---|---|---|---|---|---|
| 2mX1.8m | 350.0 | 350.0 | 350.0 | 240.0 | unverified |  |
| 2mX2m | 350.0 | 350.0 | 350.0 | 250.0 | unverified |  |
| 2mX2.5m | 350.0 | 350.0 | 350.0 | 260.0 | unverified |  |
| 2mX3m | 350.0 | 350.0 | 350.0 | 260.0 | unverified |  |
| 2mX3.5m | 350.0 | 350.0 | 350.0 | 270.0 | unverified |  |
| 2mX4m | 400.0 | 400.0 | 400.0 | 290.0 | unverified |  |
| 3mX1.8m | 400.0 | 400.0 | 400.0 | 220.0 | unverified |  |
| 3mX2m | 400.0 | 400.0 | 400.0 | 220.0 | unverified |  |
| 3mX2.5m | 450.0 | 450.0 | 450.0 | 230.0 | unverified |  |
| 3mX3m | 450.0 | 450.0 | 450.0 | 240.0 | unverified |  |
| 3mX3.5m | 450.0 | 450.0 | 450.0 | 250.0 | unverified |  |
| 3mX4m | 450.0 | 450.0 | 450.0 | 260.0 | unverified |  |
| 3mX4.5m | 450.0 | 450.0 | 450.0 | 260.0 | unverified |  |
| 3mX5m | 500.0 | 500.0 | 500.0 | 280.0 | unverified |  |
| 3mX6m | 550.0 | 550.0 | 550.0 | 300.0 | unverified |  |
| 4mX2m | 500.0 | 500.0 | 500.0 | 220.0 | unverified |  |
| 4mX2.5m | 500.0 | 500.0 | 500.0 | 220.0 | unverified |  |
| 4mX3m | 500.0 | 500.0 | 500.0 | 230.0 | unverified |  |
| 4mX3.5m | 500.0 | 500.0 | 500.0 | 240.0 | unverified |  |
| 4mX4m | 500.0 | 500.0 | 500.0 | 250.0 | unverified |  |
| 4mX4.5m | 500.0 | 500.0 | 500.0 | 260.0 | unverified |  |
| 4mX5m | 550.0 | 550.0 | 550.0 | 270.0 | unverified |  |
| 4mX6m | 600.0 | 600.0 | 600.0 | 290.0 | unverified |  |
| 5mX2.5m | 650.0 | 650.0 | 650.0 | 230.0 | unverified |  |
| 5mX3m | 650.0 | 650.0 | 650.0 | 240.0 | unverified |  |
| 5mX3.5m | 650.0 | 650.0 | 650.0 | 240.0 | unverified |  |
| 5mX4m | 650.0 | 650.0 | 650.0 | 250.0 | unverified |  |
| 5mX4.5m | 650.0 | 650.0 | 650.0 | 260.0 | unverified |  |
| 5mX5m | 650.0 | 650.0 | 650.0 | 270.0 | unverified |  |
| 5mX6m | 650.0 | 650.0 | 650.0 | 280.0 | unverified |  |
| 6mX3m | 700.0 | 700.0 | 700.0 | 230.0 | unverified |  |
| 6mX3.5m | 700.0 | 700.0 | 700.0 | 240.0 | unverified |  |
| 6mX4m | 750.0 | 750.0 | 750.0 | 250.0 | unverified |  |
| 6mX4.5m | 750.0 | 750.0 | 750.0 | 260.0 | unverified |  |
| 6mX5m | 750.0 | 750.0 | 750.0 | 270.0 | unverified |  |
| 6mX6m | 800.0 | 800.0 | 800.0 | 290.0 | unverified |  |

Unclear items recorded by the extraction: 20; not-read items: 35 (full list in the JSON).

## Context from the Foundation Model knowledge base (unreviewed there)

| Id | Topic | Name | Statement | Evidence | Kind here |
|---|---|---|---|---|---|
| `kb.standard_drawing.rdso_b_10151_r` | standard_drawing | RDSO/B-10151/R | RDSO/B-10151/R: Standard drawing of single box culvert (general arrangement), DFC loading (32.5t axle load); series 10151/1R-9R by fill height | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10152_r` | standard_drawing | RDSO/B-10152/R | RDSO/B-10152/R: Standard drawing of single box culvert (general arrangement), 25t loading-2008; series 10152/2R-10R | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10153` | standard_drawing | RDSO/B-10153 | RDSO/B-10153: Standard drawing of segmental RCC box culvert for limited height subway, 25t loading-2008 (general arrangement part-I) | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10154_r` | standard_drawing | RDSO/B-10154/R | RDSO/B-10154/R: Standard drawing of double box culvert (general arrangement), DFC loading (32.5t axle load); series 10154/1R-9R | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10155` | standard_drawing | RDSO/B-10155 | RDSO/B-10155: Standard drawing of single box culvert for double line track curved up to 10 deg (general arrangement), 25t loading-2008; 10155/1-5 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10155_6` | standard_drawing | RDSO/B-10155/6 | RDSO/B-10155/6: Standard drawing of single box culvert for double line track curved up to 10 deg (structural design details for 5.0 m fill height), 25t loading-2008; 10155/6-10 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10156` | standard_drawing | RDSO/B-10156 | RDSO/B-10156: Standard drawing of segmental RCC box culvert for limited height subway, DFC loading (32.5t axle load) (general arrangement part-I) | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10157` | standard_drawing | RDSO/B-10157 | RDSO/B-10157: Standard drawing of single box culvert for double line track, curved (printed "up to 10", with an overprinted earlier angle) (general arrangement), DFC loading; 10157/1-5 by fill height | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10157_6` | standard_drawing | RDSO/B-10157/6 | RDSO/B-10157/6: Standard drawing of single box culvert for double line track curved up to 10 deg (structural design details for 4.0 m fill height), DFC loading; 10157/6-10 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10158` | standard_drawing | RDSO/B-10158 | RDSO/B-10158: Standard drawing of double box culvert for double line track curved up to 10 deg and straight track (general arrangement), 25t loading-2008; 10158/1,2 and 1A,2A | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10159` | standard_drawing | RDSO/B-10159 | RDSO/B-10159: Typical plan of RCC segmental box for RUB with footpath and provision for cut and drop wall, 6.00 m (clear span) x 4.65 m (height), 25t loading-2008 (general arrangement) | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10160` | standard_drawing | RDSO/B-10160 | RDSO/B-10160: Typical drawing for construction of RUB/subway using the combination of "cut, open and push the single long barrel RCC box" | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10161` | standard_drawing | RDSO/B-10161 | RDSO/B-10161: Standard drawing of RCC box pushing using protection plate arrangement (general arrangement), 25t loading-2008; 10161/1 protection plate and anchoring arrangement | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10163` | standard_drawing | RDSO/B-10163 | RDSO/B-10163 and B-10163/1: standard drawing of segmental box culvert for limited height subway under multiple track for curvature up to 10 deg conforming to 25t loading-2008 (RDSO issuing letter of 30.06.2025 with the d… | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10164` | standard_drawing | RDSO/B-10164 | RDSO/B-10164: Standard drawing of RCC double box culvert for double track condition and curvature up to 10 deg (general arrangement), DFC loading (32.5t axle load); 10164/1-9 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10165` | standard_drawing | RDSO/B-10165 | RDSO/B-10165: Standard drawing of single box culvert for double line straight track up to 45 deg skew angle (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10166` | standard_drawing | RDSO/B-10166 | RDSO/B-10166: Standard drawing of double box culvert with clear span 7.5 m for double line straight track (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10167` | standard_drawing | RDSO/B-10167 | RDSO/B-10167: Standard drawing of single box culvert with clear span 7.5 m for double line straight track (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10168` | standard_drawing | RDSO/B-10168 | RDSO/B-10168: Standard drawing of single cell segmental RCC box (M45) for double line straight track (size 3.0 m x 2.65 m) (limited height subway) (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10169` | standard_drawing | RDSO/B-10169 | RDSO/B-10169: Standard drawing of single cell RCC box with clear span 9.0 m for double line straight track (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10170` | standard_drawing | RDSO/B-10170 | RDSO/B-10170: Standard drawing of single cell segmental RCC box (M45) for double line straight track (size 3.0 m x 2.65 m) (limited height subway) (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_b_10171` | standard_drawing | RDSO/B-10171 | RDSO/B-10171: Standard drawing of single cell segmental UHPFRC box (M155) for double line straight track (size 2.73 m x 2.65 m) (limited height subway) (FOR TRIAL PURPOSE ONLY) (general arrangement), 25t loading-2008 | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_m_00004` | standard_drawing | RDSO/M-00004 | RDSO/M-00004: Standard drawing of single box culvert (general arrangement) (bilingual Hindi / English) | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_m_00005` | standard_drawing | RDSO/M-00005 | RDSO/M-00005: Standard drawing of double box culvert for single track (general arrangement) | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_m_00008` | standard_drawing | RDSO/M-00008 | RDSO/M-00008: Standard drawing of limited use subway (general arrangement) (bilingual Hindi / English), pre-cast box unit | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.standard_drawing.rdso_rcc_box_annexure_to_m_00004` | standard_drawing | Annexure to drawing RDSO/M-00004: design parameters for single box cul | Annexure to drawing RDSO/M-00004: design parameters for single box culvert (reinforcement and thickness tables for single-cell boxes of several spans and heights; zero fill depth, 350 mm ballast cushion; 18 pages, the te… | REFERENCE_OBSERVED (proposed) | explicit |
| `kb.formula.d_clear_height` | formula | D-CLEAR-HEIGHT | clear_height = soffit_level - floor_level | DERIVED (seed_unreviewed) | derived |
| `kb.formula.d_clear_height_from_bed` | formula | D-CLEAR-HEIGHT-FROM-BED | clear_height = soffit_level - bed_level | DERIVED (seed_unreviewed) | derived |
| `kb.formula.d_clearance` | formula | D-CLEARANCE | clearance = soffit_level - hfl when drawings write CL-/V.C. against the HFL; IRBM 312 measures clearance from the design-discharge water level incl. afflux (KC-6) | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `kb.formula.d_cushion` | formula | D-CUSHION | cushion = formation_level - top_slab_level when the datum of a standard drawing's 'fill height' (formation, sleeper or rail) is not settled (KC-5); the drawing's own cushion is formation − top of structure | DERIVED (seed_unreviewed) | derived |
| `kb.formula.d_top_slab` | formula | D-TOP-SLAB | top_slab = top_slab_level - soffit_level | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_box_soffit` | formula | F-BOX-SOFFIT | soffit_level = floor_level + clear_height | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_box_soffit_from_bed` | formula | F-BOX-SOFFIT-FROM-BED | soffit_level = bed_level + clear_height | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_box_top` | formula | F-BOX-TOP | top_slab_level = soffit_level + top_slab | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_floor_from_bed_wearing` | formula | F-FLOOR-FROM-BED-WEARING | floor_level = bed_level - wearing_course when the bed level marks the top of the wearing course in the cells (layout bed_is = wearing_top) | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_floor_from_soffit` | formula | F-FLOOR-FROM-SOFFIT | floor_level = soffit_level - clear_height | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_pipe_soffit` | formula | F-PIPE-SOFFIT | soffit_level = floor_level + pipe_diameter | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_pipe_top` | formula | F-PIPE-TOP | top_slab_level = soffit_level + pipe_thickness | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_span_seat` | formula | F-SPAN-SEAT | seat_level = soffit_level - bearing_height | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_span_seat_no_bearing` | formula | F-SPAN-SEAT-NO-BEARING | seat_level = soffit_level when no bearing read (DEF-NO-BEARING) | ASSUMPTION (seed_unreviewed) | unverified |
| `kb.formula.f_span_soffit_at_seat` | formula | F-SPAN-SOFFIT-AT-SEAT | soffit_level = seat_level when no bearing read: the deck sits on the seat (defaults.json DEF-NO-BEARING) | ASSUMPTION (seed_unreviewed) | unverified |
| `kb.formula.f_span_soffit_from_seat` | formula | F-SPAN-SOFFIT-FROM-SEAT | soffit_level = seat_level + bearing_height | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_span_soffit_from_top_girder` | formula | F-SPAN-SOFFIT-FROM-TOP-GIRDER | soffit_level = top_slab_level - girder_depth | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_span_soffit_from_top_slab` | formula | F-SPAN-SOFFIT-FROM-TOP-SLAB | soffit_level = top_slab_level - deck_slab | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_span_top_girder` | formula | F-SPAN-TOP-GIRDER | top_slab_level = soffit_level + girder_depth | DERIVED (seed_unreviewed) | derived |
| `kb.formula.f_span_top_slab` | formula | F-SPAN-TOP-SLAB | top_slab_level = soffit_level + deck_slab | DERIVED (seed_unreviewed) | derived |
| `kb.formula.hwb_val_007` | formula | HWB-VAL-007 | highway haunch ≥ 0.15 m — unverified | UNKNOWN (seed_unreviewed) | unverified |
| `kb.formula.rcr_lvl_007` | formula | RCR-LVL-007 | FW + 4·cushion with a '1:1 slope' contradicts itself (a 1:1 slope gives FW + 2H) | DISPUTED (seed_unreviewed) | unverified |
| `kb.formula.rcr_val_007` | formula | RCR-VAL-007 | cushion ≥ 75 mm — unverified | UNKNOWN (seed_unreviewed) | unverified |
| `kb.formula.rcr_val_008` | formula | RCR-VAL-008 | haunch ≥ 0.3 m — unverified; drawings in hand use 200 | UNKNOWN (seed_unreviewed) | unverified |
| `kb.rule.irbm_207_3_weep_holes` | rule | Weep holes 1 m × 1 m staggered; lowest row placement | Weep holes at 1 m vertical and 1 m horizontal, staggered, in abutments, wing and return walls; the bottom row above LWL in flowing streams, 250 mm above bed otherwise, above FSL in canals. | NORMATIVE (seed_unreviewed) | explicit |
| `kb.rule.irbm_312_1_vertical_clearance` | rule | Vertical clearance above the design water level (by discharge) | Soffit minus the water level of the design discharge incl. afflux: 600 mm for 0–30 m³/s, 600–1200 pro rata for 31–300, 1500 for 301–3000, 1800 above. | NORMATIVE (seed_unreviewed) | explicit |
| `kb.rule.irbm_312_3_culvert_exempt` | rule | Pipe and box culverts: no vertical clearance (pressure conduits) | Syphons, pipe and box culverts are designed as pressure conduits; no clearance is required for them. | NORMATIVE (seed_unreviewed) | explicit |
| `kb.rule.irbm_402_culvert_scour` | rule | Pipe / box culverts not where the bed is likely to scour | Pipe and box culverts on open foundations are built on a levelled, consolidated bed with lean concrete, and should not normally be provided where the bed is likely to be scoured. | NORMATIVE (seed_unreviewed) | explicit |
| `kb.rule.ircm_box_span` | rule | RCC box span > 3 m needs CAO(C) / CBE approval | RCC boxes for minor bridges up to 3 m span with adequate cushion; larger spans need CAO(C)/CBE approval (IRCM, quoted by a secondary source). | REFERENCE_OBSERVED (seed_unreviewed) | explicit |
| `kb.rule.know_cushion_minimum` | rule | Minimum earth cushion | No source in hand sets a minimum cushion or its datum; the documented 75 mm (RCR-VAL-007) is unverified. | UNKNOWN (seed_unreviewed) | unverified |
| `kb.rule.know_haunch_minimum` | rule | Minimum haunch | No source in hand sets a minimum haunch; the documented 300 mm (RCR-VAL-008) is unverified. | UNKNOWN (seed_unreviewed) | unverified |
| `kb.rule.level_order_cover` | rule | Formation not below the top of a buried structure | A box or pipe is under the formation: formation level ≥ top of the structure (cushion ≥ 0). | DERIVED (seed_unreviewed) | derived |
| `kb.rule.level_order_rail_formation` | rule | Rail above formation | The rail sits on the formation: rail level above formation level. | DERIVED (seed_unreviewed) | derived |
| `kb.rule.level_order_slabs` | rule | Top of structure above soffit above floor above underside | top of the top slab > soffit > floor > underside of the bottom slab. | DERIVED (seed_unreviewed) | derived |
| `kb.rule.track_rail_over_formation` | rule | Rail over formation (0.762 m is an assumption) | Rail level minus formation level depends on the rail, sleeper and ballast of each track; 0.762 m is a common assumption, not a rule. | ASSUMPTION (seed_unreviewed) | unverified |
| `kb.level_chain.chain_pipe` | level_chain | chain.pipe | A pipe crossing: the invert (written, or at the bed), the inside crown, the outside crown (what the cushion is measured from), the outside invert and the bedding courses under it. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `kb.level_chain.chain_slab` | level_chain | chain.slab | A slab deck on abutments and piers: the deck from its soffit (written, or from its top and depth, or from the bearing seat), the seat under it, the footings from the B.O.F. (or the bed and the embedment) and the courses … | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `kb.conflict.kc_1` | conflict | KC-1: Rail level − formation level | Rail level − formation level | DISPUTED (seed_unreviewed) | unverified |
| `kb.conflict.kc_2` | conflict | KC-2: Barrel length | Barrel length | DISPUTED (seed_unreviewed) | unverified |
| `kb.conflict.kc_3` | conflict | KC-3: Minimum haunch | Minimum haunch | DISPUTED (seed_unreviewed) | unverified |
| `kb.conflict.kc_5` | conflict | KC-5: Earth cushion minimum and datum | Earth cushion minimum and datum | DISPUTED (seed_unreviewed) | unverified |
| `ref.level.bed` | datum | Bed level | Level of the stream bed at the bridge; in a box on the railway convention, the top of the wearing course in the cells. | COMMON_PRACTICE (draft) | unverified |
| `ref.level.coping` | datum | Top of the wing / return wall (its coping) | The level top of a wing or return wall — the top of its coping where it has one. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `ref.level.floor_invert` | datum | Floor (top of bottom slab) / pipe invert | Top face of a box's bottom slab (under any wearing course), or a pipe's inside invert. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `ref.level.formation` | datum | Formation level | Top of the railway embankment on which the ballast rests; free board is measured to it (IRBM 313). | COMMON_PRACTICE (draft) | unverified |
| `ref.level.rail` | datum | Rail level | Level of the top of the rail. | COMMON_PRACTICE (draft) | unverified |
| `ref.level.soffit` | datum | Soffit level | Underside of the top slab / deck (the inside crown of a pipe). Vertical clearance is measured to it (IRBM 312). | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `ref.level.wing_top` | datum | Top of the wing / return wall (its coping) | The level top of a wing or return wall — the top of its coping where it has one. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.component.ballast` | component | Ballast bed | Ballast cushion under sleepers. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.component.box_barrel` | component | Box barrel | The monolithic RCC box (all cells, walls, slabs, haunches) as one component. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.component.earth_cushion` | component | Earth cushion (fill over box/pipe) | Fill between top of box/pipe and formation. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.component.return_wall` | component | Return wall | Wall parallel to the track (perpendicular to the abutment) retaining embankment side fill. | COMMON_PRACTICE (draft) | unverified |
| `phys.component.toe_wall` | component | Toe wall | Small wall at toe of pitching/apron. | COMMON_PRACTICE (draft) | unverified |
| `phys.component.top_slab` | component | Top slab | Roof slab of the box; carries cushion/ballast/track. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.component.wearing_course` | component | Wearing course | Wearing coat over deck or box top / floor. | COMMON_PRACTICE (draft) | unverified |
| `phys.subcomponent.coping` | component | Coping | Cap course on top of a wing/return wall or abutment, sometimes chamfered. | COMMON_PRACTICE (draft) | unverified |
| `phys.subcomponent.haunch` | component | Haunch | Triangular thickening at slab–wall junction inside a cell, written 'HAUNCH a X b'. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.subcomponent.shear_key` | component | Shear key | Key between precast box units or slab joints. | COMMON_PRACTICE (seed_unreviewed) | unverified |
| `phys.subcomponent.wing_stem` | component | Wing wall stem | Stem of a wing/return wall above its footing. | COMMON_PRACTICE (seed_unreviewed) | unverified |

