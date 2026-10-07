"""The shape of Gemini's answer. Everything it may say, nothing it could say vaguely.

Every claim names ids from the CAD JSON (regions R…, entities L…/PL…/A…/C…/T…/D…, set-out lines
x…/y…/ax…, candidate values c…) so the validator can check it against the geometry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Field(default=0.8, ge=0.0, le=1.0, description="0..1: how sure you are, from the evidence")


class AIComponent(BaseModel):
    name: str = Field(description="PascalCase name of this part on this drawing, e.g. ProposedBox, WingWallLeft, TopSlab, PccCourse")
    type: str = Field(description="concept id from KNOWLEDGE (box, top_slab, wall, wing_wall, return_wall, apron, drop_wall, courses, earth_fill, track, deck, girder, pier, abutment, footing …) or a plain snake_case word")
    level: Literal["assembly", "component", "subcomponent"] = Field(
        default="component", description="assembly: a whole structure (the proposed box, the existing bridge); component: a part of it (a wall, a slab, an apron); subcomponent: a detail of a part (a haunch, a coping, a step)")
    parent: str | None = Field(default=None, description="name of the assembly / component this is part of (None for a top-level assembly)")
    regions: list[str] = Field(default_factory=list, description="ids of the closed regions (R…) that make it up")
    entities: list[str] = Field(default_factory=list, description="ids of other entities that belong to it but bound no region (open lines: track, ground line, a level line)")
    datums: list[str] = Field(default_factory=list, description="set-out lines that bound it, when regions do not say enough")
    existing: bool = Field(default=False, description="true for EXISTING / old work (beside a doubling / extension). It is parametrized too (prefix names Existing…); a person may hold it fixed")
    parametrize: bool = Field(default=True, description="your recommendation: should a person make this part parametric? false for a detail that stays as drawn (a drainage detail, a typical sketch), reference / construction geometry, title, notes")
    confidence: float = Confidence
    evidence: list[str] = Field(default_factory=list, description="short facts that show what it is: a note's words, its hatch, its shape, where it sits, what it rests on")
    description: str = ""
    outlines: list[str] = Field(default_factory=list, description="(older form of `entities` for closed outlines; prefer regions)")


class AILineRole(BaseModel):
    datum: str = Field(description="set-out line id (x…/y…/ax…)")
    component: str = Field(description="component name")
    role: str = Field(description="what the line is for that part, in a draftsman's words: inner face, outer face, top, bottom, soffit, centre line, toe, heel, cell floor, formation …")
    confidence: float = Confidence


class AILevel(BaseModel):
    datum: str = Field(description="y datum id the level line is drawn at")
    name: str = Field(description="PascalCase, ends in Level (or Hfl/Lwl), e.g. BedLevel, FormationLevel, RailLevel")
    role: Literal["site_input", "check_only", "derived"] = Field(
        description="site_input: given by the site and held fixed (bed, formation, rail, ground); check_only: a water level the structure is checked against (HFL, LWL); derived: follows the structure (top of slab, soffit, foundation)")


class AIParameter(BaseModel):
    name: str = Field(description="PascalCase engineering name, from KNOWLEDGE where one fits (ClearSpan, OuterWall, TopSlab, Haunch …)")
    label: str = Field(description="plain words, e.g. 'Clear span of each cell'")
    component: str = Field(description="component name it belongs to")
    kind: Literal["length"] = "length"
    candidate: str | None = Field(default=None, description="id of the candidate value (c…) this names; all its occurrences stay one value")
    from_datum: str | None = Field(default=None, description="when no candidate fits: the datum it is measured from")
    to_datum: str | None = Field(default=None, description="... and the datum it is measured to")
    value: float = Field(description="its value in mm — exactly the measured value")
    importance: Literal["primary", "secondary", "detail"] = Field(
        default="secondary", description="primary: what a designer changes first (span, height, number of cells, levels); secondary: member sizes; detail: small fixed details")
    recommended: bool = Field(default=True, description="your recommendation: make it an editable input (false: keep it as drawn)")
    confidence: float = Confidence
    evidence: list[str] = Field(default_factory=list, description="why it is a design input: dimension D… states it, it repeats n times, the note says …, it spans region R… between its faces")
    reason: str = ""


class AIFormula(BaseModel):
    datum: str = Field(description="datum id to set out")
    expr: str = Field(description="expression in mm over datum ids and parameter names, e.g. 'y5 + ClearHeight'")
    reason: str = ""


class AIRelation(BaseModel):
    name: str = Field(description="PascalCase, e.g. OverallWidth, EarthCushion")
    label: str
    expr: str = Field(description="expression over parameter names (mm; levels in m, use *1000 to get mm)")
    from_datum: str | None = None
    to_datum: str | None = None


Behaviour = Literal["grows", "shrinks", "moves", "fixed", "keeps_thickness", "keeps_level", "stays_centred",
                    "stays_symmetric", "stays_connected", "keeps_slope"]


class AIEffect(BaseModel):
    target: str = Field(description="a component name, a level name or a relation name")
    behaviour: Behaviour = Field(description="what happens to it when the parameter INCREASES")
    axis: Literal["x", "y", "both"] | None = Field(default=None, description="x = horizontal, y = vertical (None when it does not matter)")
    why: str = ""


class AIBehaviour(BaseModel):
    parameter: str = Field(description="parameter (or level) name")
    effects: list[AIEffect] = Field(description="the parts that grow, move or must stay as they are when it increases — include what stays FIXED, not only what changes")


ConstraintType = Literal["distance", "fixed", "symmetric", "centred", "equal", "connected", "slope", "parallel", "perpendicular", "collinear"]


class AIConstraint(BaseModel):
    type: ConstraintType = Field(description=(
        "distance: datums [a, b] stay `value` apart; fixed: datums never move; symmetric: datums [a, b, axis] mirror about the axis; "
        "centred: datums [a, b] stay centred on datums[2]; equal: datums [a, b, c, d] keep b-a = d-c; connected: components [A, B] keep touching; "
        "slope: components [A] keep their inclined edges' angle; parallel / perpendicular / collinear: entities stay so"))
    datums: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    value: str | None = Field(default=None, description="for distance: an expression over parameter names (mm), e.g. 'OuterWall'")
    description: str = ""
    confidence: float = Confidence
    evidence: list[str] = Field(default_factory=list)


class AIAnswer(BaseModel):
    structure_type: str = Field(description="e.g. 'RCC box culvert, 2 cells' or 'PSC girder bridge, 3 spans'")
    family: str = Field(description="family id from the knowledge pack (rcc_box, slab, girder, pipe, arch, rub, rob) or 'other'")
    views: list[str] = Field(description="what each view on the sheet is, e.g. 'half section / half elevation at A-A'")
    summary: str
    components: list[AIComponent]
    line_roles: list[AILineRole] = Field(default_factory=list)
    levels: list[AILevel]
    parameters: list[AIParameter]
    datum_formulas: list[AIFormula] = Field(default_factory=list)
    relations: list[AIRelation] = Field(default_factory=list)
    behaviours: list[AIBehaviour] = Field(default_factory=list)
    constraints: list[AIConstraint] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, description="real ambiguities a person should decide")
