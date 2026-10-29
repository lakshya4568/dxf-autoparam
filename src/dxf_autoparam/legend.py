"""What a drawing's own legend says its colours mean — proposed work, existing work, work to be dismantled, a boundary — and which entities are drawn
in each. Read from the sheet, never assumed: a GAD says "PROP. WORK SHOWN IN RED", "DISMANTLED WORK SHOWN IN YELLOW", or puts a sample line beside
"RAILWAY LAND BOUNDARY" in a legend table. The sample line is what is drawn, so it outranks the colour word (one sheet says yellow and draws its
dismantling work orange).

What the engine does with it (validator.apply): work to be dismantled and a boundary stay where they are drawn — a structure's value never re-sets them
— and new work may pass through work that is dismantled (no clash). Proposed and existing are said to the agent; which part is which stays its answer."""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass, field

from .ir import Drawing

# a legend entry's words → the state it names (the first that matches: "EXIST. RAIL BOUNDARY" is a boundary, "DISMANTLED EXIST. WORK" is dismantled)
STATES = (
    ("dismantled", re.compile(r"DISMANT|DEMOLI|TO BE REMOVED")),
    ("boundary", re.compile(r"\bBO\w{0,3}NDAR")),  # BOUNDARY, and the spelling a sheet got wrong (BOUANDARY)
    ("proposed", re.compile(r"\bPROP(?:OSED)?\b|\bPROP\.|\bNEW\s+WORK")),
    ("existing", re.compile(r"\bEXIST|\bEXG\b|\bEXTG\b")),
)
HELD_STATES = ("dismantled", "boundary")  # what stays where it is drawn
FG = "fg"  # the drawing's foreground colour (ACI 7: black on paper, white on a dark screen)
WORDS = {"RED": "#ff0000", "GREEN": "#00ff00", "BLUE": "#0000ff", "YELLOW": "#ffff00", "CYAN": "#00ffff", "MAGENTA": "#ff00ff", "PINK": "#ff00ff",
         "ORANGE": "#ff8000", "BROWN": "#996633", "GREY": "#808080", "GRAY": "#808080", "BLACK": FG, "WHITE": FG}
HUE_TOL = 15.0  # degrees: an entity's colour is a legend colour when no other legend colour is nearer and it is this close


@dataclass
class Legend:
    colours: dict[str, list[str]] = field(default_factory=dict)  # state → the colours it is drawn in (hex, or FG)
    entries: list[dict] = field(default_factory=list)  # each legend entry read: {text, state, colour, source}

    def __bool__(self) -> bool:
        return bool(self.colours)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\\[A-Za-z][^;\\]*;|[{}]", " ", s)).strip().upper()


def _shown(it) -> str | None:
    st = it.extra.get("style") or {}
    if st.get("fg"):
        return FG
    c = st.get("color")
    return c.lower() if isinstance(c, str) and c.startswith("#") else None


def _hsv(c: str) -> tuple[float, float, float]:
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def _hue_gap(a: str, b: str) -> float | None:
    """How far apart two colours are in hue (degrees), or None when either is not a colour of its own (the foreground, a grey)."""
    if FG in (a, b):
        return 0.0 if a == b else None
    (ha, sa, va), (hb, sb, vb) = _hsv(a), _hsv(b)
    if min(sa, sb) < 0.3 or min(va, vb) < 0.2:
        return 0.0 if a == b else None
    d = abs(ha - hb) % 360.0
    return min(d, 360.0 - d)


def read_legend(dr: Drawing) -> Legend:
    """The legend of a sheet: each short text that names a state, with its colour — the sample line drawn beside it on its row if there is one, else
    the colour its words say ("… SHOWN IN RED")."""
    items = dr.items
    texts = [it for it in items if it.dxftype in ("TEXT", "MTEXT") and it.text and it.pts]
    lines = [it for it in items if it.dxftype in ("LINE", "LWPOLYLINE", "POLYLINE") and len(it.pts) >= 2]
    out = Legend()
    for t in texts:
        s = _clean(t.text or "")
        said = re.search(r"SHOWN\s+(?:IN|AS)\s+[A-Z]+", s)
        if not s or len(s) > 60 or re.search(r"\d", s) or not said and len(s.split()) > 4:
            continue  # a note, a level ("PROP. ROAD LEVEL 711.477" beside its line), a title: not a legend entry
        state = next((name for name, rx in STATES if rx.search(s)), None)
        if state is None:
            continue
        h = t.text_height or 0.0
        x, y = t.pts[0]
        swatch = None
        if h > 0:
            row = []
            for it in lines:
                xs, ys = [p[0] for p in it.pts], [p[1] for p in it.pts]
                if max(ys) - min(ys) > 0.5 * h or max(xs) - min(xs) < 2 * h:
                    continue  # a sample is a horizontal stroke of some length
                cy = (max(ys) + min(ys)) / 2
                if abs(cy - (y + h / 2)) <= 1.5 * h and -40 * h <= min(xs) - x <= 60 * h and (c := _shown(it)):
                    row.append((c != FG, -abs(min(xs) - x), c))
            if row:
                swatch = max(row)[2]  # a coloured stroke before a foreground one (the table's own rules are drawn in the foreground)
        m = re.search(r"SHOWN\s+(?:IN|AS)\s+([A-Z]+)", s)
        word = WORDS.get(m.group(1)) if m else None
        colour, source = (swatch, "sample line") if swatch else (word, "words") if word else (None, "")
        if colour is None:
            continue
        out.entries.append({"text": s, "state": state, "colour": colour, "source": source})
        if colour not in out.colours.setdefault(state, []):
            out.colours[state].append(colour)
    # a colour two states claim tells them apart from nothing (one sheet's legend gives black and red to proposed, existing and dismantled alike),
    # and what stays where it is drawn is never the foreground: the drawing's own lines are mostly drawn in it
    claims: dict[str, set[str]] = {}
    for state, cs in out.colours.items():
        for c in cs:
            claims.setdefault(c, set()).add(state)
    for state in list(out.colours):
        out.colours[state] = [c for c in out.colours[state] if len(claims[c]) == 1 and not (state in HELD_STATES and c == FG)]
        if not out.colours[state]:
            del out.colours[state]
    return out


def state_of(colour: str | None, legend: Legend) -> str | None:
    """The state an entity drawn in `colour` is in: the legend colour nearest in hue (the foreground only as itself), within HUE_TOL."""
    if colour is None or not legend:
        return None
    best: tuple[float, str] | None = None
    for state, cs in legend.colours.items():
        for c in cs:
            d = _hue_gap(colour, c)
            if d is not None and d <= HUE_TOL and (best is None or d < best[0]):
                best = (d, state)
    return best[1] if best else None


def entity_states(dr: Drawing, legend: Legend | None = None) -> dict[int, str]:
    """index → state, for the structural entities the legend's colours say something about."""
    legend = legend if legend is not None else read_legend(dr)
    if not legend:
        return {}
    out = {}
    for it in dr.items:
        if it.role.value in ("structural", "reference") and (st := state_of(_shown(it), legend)):
            out[it.index] = st
    return out
