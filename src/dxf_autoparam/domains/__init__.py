"""Domain packs: semantic layers on top of the generic engine.

A domain pack may only DECIDE and NAME — which stated levels are site inputs, what a
value is called — through the same `Decisions` a person makes in review. It never
creates geometry, never adds a relationship the geometry does not show, and the
engine works without any pack.
"""

from .bridge import bridge_decisions

PACKS = {"bridge": bridge_decisions}
