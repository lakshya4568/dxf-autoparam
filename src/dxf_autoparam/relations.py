"""A relation proposed between named values and the drawing's own lines — checked on the drawing before anything binds it.

A relation comes from somewhere: what a generator computes (`FootingWidth = ToeWidth + StemBottomThickness + HeelWidth`), a standard, the drawing's
own notes, the agent's reading. It is a HYPOTHESIS about this drawing until the drawing says so. `check(prog, "LHS = RHS")` says, nothing changed:

  holds      the two sides at the drawn values, and their difference (mm): within tolerance, or not
  terms      what each name is — a named value (length mm, level m), a set-out line (its position, mm), a relation the engine works out — and its value
  units      levels (metres) and lengths (millimetres) are both taken in mm, as `calculate` takes them; a side that adds a level to a length (or two
             levels) is said, because it is rarely what was meant
  follows    for each named value that takes part — named on either side, or moving a line the relation names: step it by one unit — do the two
             sides, as the drawing is set out NOW, still agree? yes for every one: the drawing already carries the relation (an identity of its
             set-out); no: binding it would change how the drawing behaves when that value changes
  gives      for each of those values, which terms of the relation move when it is stepped (mm per unit): which quantity gives way. A relation
             can be carried with another choice of what gives than a designer's (the barrel kept and the formation widening, where production
             keeps the formation and lengthens the barrel): that is design intent, said here, chosen by setting lines out (set_formulas)
  binding    what binding it takes: nothing (already carried) · the left value worked out from the right (set_relation) · the left line set out from the
             right (set_formulas) · nothing to bind (it does not hold: check the reading, or the relation)

Expressions use the engine's own evaluator (numbers, names, + - * / ^ and its functions); nothing else runs."""

from __future__ import annotations

from .program import ExprError, evaluate, names_in

TOL_MM = 0.5


def _split(equation: str) -> tuple[str, str]:
    for sep in ("==", "="):
        if sep in equation:
            lhs, rhs = equation.split(sep, 1)
            if lhs.strip() and rhs.strip() and "=" not in rhs:
                return lhs.strip(), rhs.strip()
    raise ExprError(f"a relation is LEFT = RIGHT: {equation!r}")


def _scope(prog, values: dict[str, float] | None) -> tuple[dict[str, float], dict[str, dict]]:
    """Every name an equation may use, in mm: named values (a level's metres as mm), relations the engine works out, set-out lines."""
    um = prog.analysis.drawing.units_mm
    vals = {**prog.defaults(), **(values or {})}
    scope: dict[str, float] = {}
    kinds: dict[str, dict] = {}
    for n, p in prog.params.items():
        v = float(vals.get(n, p.value))
        scope[n] = v * 1000.0 if p.kind == "level" else v
        kinds[n] = {"is": "level" if p.kind == "level" else ("angle" if p.kind == "angle" else "value"), "unit": "m" if p.kind == "level" else p.unit}
    for r in prog.relations:
        try:
            scope[r.name] = float(prog.relation_value(r, values))
            kinds[r.name] = {"is": "worked out", "unit": "mm"}
        except (ExprError, ArithmeticError, KeyError, ValueError):
            continue  # a relation the drawing cannot evaluate here is not a term anybody can check against
    for d, v in prog.datum_values(values).items():
        scope.setdefault(d, v * um)
        kinds.setdefault(d, {"is": "line", "unit": "mm"})
    return scope, kinds


def _taking_part(prog, names: set[str], kinds: dict[str, dict], scope: dict[str, float]) -> list[str]:
    """The named values a relation's agreement depends on: those it names, and those somebody named that move a line it names (a value the
    engine generated and nobody named is not a design input anybody changes)."""
    from .generic import is_generated

    out = [n for n in sorted(names) if kinds[n]["is"] in ("value", "level") and n in prog.params]
    lines = [n for n in names if kinds[n]["is"] == "line"]
    if lines:
        for n, p in sorted(prog.params.items()):
            if n in out or p.kind not in ("length", "level") or (is_generated(n) and p.source != "ai"):
                continue
            try:
                v1 = prog.datum_values({n: float(p.value) + (1e-3 if p.kind == "level" else 1.0)})
            except (ExprError, ArithmeticError, KeyError, ValueError):
                continue  # a value whose step the program cannot evaluate moves nothing that can be measured
            um = prog.analysis.drawing.units_mm
            if any(abs(v1[t] * um - scope[t]) > 1e-9 for t in lines if t in v1):
                out.append(n)
    return out


def check(prog, equation: str, step: float = 1.0) -> dict:
    """The relation `equation` on this program's drawing, measured (module doc). Raises nothing for a bad equation: it says why."""
    try:
        lhs, rhs = _split(equation)
        names = names_in(lhs) | names_in(rhs)
    except ExprError as exc:
        return {"equation": equation, "error": str(exc)}
    scope, kinds = _scope(prog, None)
    missing = sorted(n for n in names if n not in scope)
    if missing:
        return {"equation": equation, "error": f"not a value, level, relation or line of this unit: {', '.join(missing)}"}
    try:
        a, b = evaluate(lhs, scope), evaluate(rhs, scope)
    except ExprError as exc:
        return {"equation": equation, "error": str(exc)}
    out: dict = {"equation": f"{lhs} = {rhs}", "left_mm": round(a, 3), "right_mm": round(b, 3), "residual_mm": round(a - b, 3),
                 "holds": abs(a - b) <= max(TOL_MM, 1e-6 * max(abs(a), abs(b))),
                 "terms": {n: {**kinds[n], "mm": round(scope[n], 3)} for n in sorted(names)}}
    levels = [n for n in names_in(rhs) if kinds[n]["is"] == "level"]
    lengths = [n for n in names_in(rhs) if kinds[n]["is"] in ("value", "worked out")]
    if len(levels) > 1 or (levels and lengths and "-" not in rhs and kinds.get(lhs, {}).get("is") != "level"):
        out["units"] = (f"the right side adds {'levels' if len(levels) > 1 else 'a level and a length'} ({', '.join(levels + lengths)}): a level is a position "
                        "(metres, taken as mm here), a length a distance — check the relation means it")
    if not out["holds"]:
        out["binding"] = "nothing to bind: it does not hold on this drawing — check the reading (which lines, which values) or the relation itself"
        return out
    follows, gives = {}, {}
    for n in _taking_part(prog, names, kinds, scope):
        d = step / 1000.0 if kinds[n]["is"] == "level" else step
        try:
            s1, _k = _scope(prog, {n: float(prog.params[n].value) + d})
            a1, b1 = evaluate(lhs, s1), evaluate(rhs, s1)
        except (ExprError, ArithmeticError, KeyError, ValueError) as exc:
            follows[n] = f"not evaluable: {exc}"[:120]
            continue
        follows[n] = abs((a1 - a) - (b1 - b)) <= 1e-6 * max(1.0, abs(a1 - a), abs(b1 - b))
        moved = {t: round(s1[t] - scope[t], 3) for t in sorted(names) if t in s1 and abs(s1[t] - scope[t]) > 1e-9}
        if moved:
            gives[n] = moved
    out["follows"] = follows
    if gives:
        out["gives"] = gives
    if follows and all(v is True for v in follows.values()):
        out["binding"] = ("already carried: the drawing's set-out keeps it under every change of its values — nothing to bind (say it in the plan). "
                          "`gives` says which terms move for each value: if a designer keeps another one fixed, set the lines out that way (set_formulas)")
    elif lhs in prog.params:
        still = [n for n, v in follows.items() if v is not True]
        why = f"stepping {', '.join(still)} leaves it" if still else "its right side is the drawing's own lines and numbers"
        p = prog.params[lhs]
        if p.measures:  # an input that drives two lines: the drawing follows only when one of its lines is set out from the right side
            a, b = p.measures
            out["binding"] = (f"{lhs} is an input now ({why}); for the drawing to follow, set one of its lines out from the right side — e.g. "
                              f"set_formulas {{line: '{b}', expr: '{a} + ({rhs})'}} (what_moves({lhs}) shows which of {a} / {b} moves; a centred size moves "
                              f"both by half) — or set_relation to REPORT it worked out without moving anything")
        else:
            out["binding"] = f"{lhs} is an input now ({why}): set_relation makes it worked out from the right side (it then follows them, and stops being an input)"
    elif names_in(lhs) <= {k for k, v in kinds.items() if v["is"] == "line"}:
        out["binding"] = ("the left side is the drawing's lines: set_formulas sets one of them out from the right side so they follow "
                          f"({', '.join(n for n, v in follows.items() if v is not True)} do not move them now)")
    else:
        out["binding"] = "it holds at the drawn values only: the drawing does not carry it when the values change"
    return out
