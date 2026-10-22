"""Each view of a sheet in its own coordinate frame — the frame its numbers were made in.

A generator builds every view in its own world units (millimetres or metres from the view's own origin — a centre line, a face — with the reduced
level as the vertical) and only then places it on the sheet at a scale. A frame recovers that: real millimetres from the view's own origin, and the
reduced level wherever the view states one. It is a pure transform — a scale and a translation; views are axis-aligned on a sheet — so every point
goes to the sheet and back exactly: selection, edits and export stay on the sheet's own entities, and the sheet is rebuilt from them as it was.

The origin is decided from the view's own content, in this order, and said: x = 0 on the view's drawn centre line or axis of symmetry (one inside the
view), else its left-most structural line; y = 0 on a level the unit states (a site input first), else its lowest structural line."""

from __future__ import annotations

from dataclasses import asdict, dataclass

AXIS_SOURCES = ("drawn-axis", "global-axis", "loop-axis")  # a drawn centre line first: the drafter's own; a symmetry the engine found after it


@dataclass
class Frame:
    view: str
    mm_per_unit: float  # one drawing unit of this view, in real millimetres (its own scale)
    origin: tuple[float, float]  # sheet drawing units
    x_from: str
    y_from: str
    level: dict | None = None  # {"name", "rl_m", "at_y"}: the reduced level of the sheet line at_y (drawing units)

    def to_local(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.origin[0]) * self.mm_per_unit, (y - self.origin[1]) * self.mm_per_unit)

    def to_sheet(self, lx: float, ly: float) -> tuple[float, float]:
        return (self.origin[0] + lx / self.mm_per_unit, self.origin[1] + ly / self.mm_per_unit)

    def rl(self, y: float) -> float | None:
        """The reduced level (metres) of a sheet y, where the view states a level."""
        if not self.level:
            return None
        return self.level["rl_m"] + (y - self.level["at_y"]) * self.mm_per_unit / 1000.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["origin"] = list(self.origin)
        return d


def _structural_box(sm, gid: str) -> tuple[float, float, float, float] | None:
    g = sm.layout.group(gid)
    xs, ys = [], []
    for i in g.items:
        it = sm.dr.items[i]
        if it.role.value == "structural":
            for x, y in it.pts:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def view_frame(sm, gid: str, read: bool = True) -> Frame:
    """The frame of one view. `read`: the view's unit may be analysed for its axes and levels (False: only what is analysed already)."""
    g = sm.layout.group(gid)
    box = _structural_box(sm, gid) or g.bbox
    uid = sm.unit_of_view.get(gid)
    unit = sm.units.get(uid) if uid else None
    um = float(unit.sub.units_mm) if unit is not None else float(sm.dr.units_mm or 1.0)
    x0, x_from = box[0], "the view's left-most structural line"
    y0, y_from, level = box[1], "the view's lowest structural line", None
    if unit is not None and (read or unit.built):
        u = sm.unit(uid)
        an = u.an
        inside = [d for d in an.datums.values() if d.axis == "x" and d.source in AXIS_SOURCES and box[0] - 1e-6 <= d.value <= box[2] + 1e-6]
        if inside:
            d = min(inside, key=lambda d: (AXIS_SOURCES.index(d.source), abs(d.value - (box[0] + box[2]) / 2)))
            x0, x_from = d.value, f"its {'drawn centre line' if d.source == 'drawn-axis' else 'axis of symmetry'} {d.id}"
        answer = u.answer or {}
        values = {n: p.value for n, p in (u.prog.params.items() if u.prog else []) if p.kind == "level"}
        rows = [r for r in answer.get("levels", []) if (r.get("datum") or r.get("line")) in an.datums and r.get("name") in values
                and box[1] - 1e-6 <= an.datums[r.get("datum") or r["line"]].value <= box[3] + 1e-6]
        if rows:
            r = min(rows, key=lambda r: (r.get("role") != "site_input", r.get("name", "")))
            at = an.datums[r.get("datum") or r["line"]].value
            level = {"name": r["name"], "rl_m": float(values[r["name"]]), "at_y": at}
            y0, y_from = at, f"the level {r['name']} (RL {values[r['name']]:.3f} m)"
    return Frame(gid, um, (x0, y0), x_from, y_from, level)


def frames(sm, read: bool = False) -> dict[str, dict]:
    """Every view's frame, by view id (`read`: analyse units that are not yet — the page asks without, so a sheet opens fast)."""
    return {g.id: view_frame(sm, g.id, read).to_dict() for g in sm.layout.views()}
