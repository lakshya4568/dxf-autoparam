"""dxf-autoparam: reverse-engineer an existing 2D DXF into a parametric model.

Generic geometry first (datums, gaps, axes, repeats, evidence), an optional domain
pack on top (naming, which levels are site inputs), deterministic regeneration, and
the original DXF written back with only its coordinates changed.
"""

from .build import Decisions, build, describe
from .pipeline import autoparametrize, model_to_json, save_model, validate
from .regen import regenerate

__all__ = ["Decisions", "autoparametrize", "build", "describe", "model_to_json", "regenerate", "save_model", "validate"]
