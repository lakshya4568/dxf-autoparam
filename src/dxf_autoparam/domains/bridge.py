"""Railway / highway bridge drafting vocabulary (GADs of culverts, slabs, girders, piers ...).

Two things only:

  1. SITE LEVELS are inputs. A GAD states levels in notes; the engine finds every note
     that states the height of a line (generic). Which of those are given by the site —
     bed, HFL, LWL, formation, rail, ground, scour — rather than worked out from the
     structure is bridge knowledge, so it lives here. Those lines are pinned: when the
     box gets taller, the formation level stays where the site puts it and the earth
     cushion is what changes.
  2. NAMES. Words the drawing itself writes near a value ("HAUNCH 150x150", "WEARING
     COURSE") are mapped to the project's usual parameter names.
"""

from __future__ import annotations

import re

from ..build import Decisions
from ..ir import Analysis

# Levels a structure is checked against, never set out from.
WATER = {"HFL", "LWL", "DangerLevel", "ScourLevel"}

SITE_LEVELS: list[tuple[str, str]] = [
    (r"\bH\.?\s?F\.?\s?L\b|HIGH\s+FLOOD", "HFL"),
    (r"\bL\.?\s?W\.?\s?L\b|LOW\s+WATER", "LWL"),
    (r"FORMATION|\bF\.\s?L\b", "FormationLevel"),
    (r"RAIL\s+LEVEL|TOP\s+OF\s+RAIL|\bR\.?\s?T\.?\s?L\b", "RailLevel"),
    (r"\bBED\b", "BedLevel"),
    (r"GROUND|\bG\.\s?L\b|\bN\.?\s?S\.?\s?L\b", "GroundLevel"),
    (r"SCOUR", "ScourLevel"),
    (r"DANGER", "DangerLevel"),
]

NAMES: list[tuple[str, str]] = [
    (r"HAUNCH", "Haunch"),
    (r"WEARING", "WearingCourse"),
    (r"CUSHION", "EarthCushion"),
    (r"P\.?\s?C\.?\s?C|LEAN|BLINDING", "PccThickness"),
    (r"COPING", "Coping"),
    (r"BOULDER|PITCHING", "Pitching"),
    (r"WEEP|DRAIN", "WeepHoleDia"),
]


def bridge_decisions(an: Analysis) -> Decisions:
    dec = Decisions()
    used: set[str] = set()
    for datum, _item, words, _value in an.stated_levels:
        for pattern, name in SITE_LEVELS:
            if re.search(pattern, words) and name not in used and datum not in dec.pin:
                dec.pin[datum] = name
                if name in WATER:
                    dec.reference_only.add(datum)
                used.add(name)
                break
    taken: set[str] = set()
    for c in an.clusters.values():
        if not c.suggested:
            continue
        for pattern, name in NAMES:
            if re.search(pattern, c.suggested.upper()) and name not in taken:
                dec.rename[c.id] = name
                taken.add(name)
                break
    return dec
