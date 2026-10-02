"""Public staging entry point.

The implementation is split into composable asset, gameplay-hook and runtime
installation phases in :mod:`world.stage_pipeline`; this module preserves the
original imports used by adapters and tests.
"""
from .stage_contract import PASSING_HOOK, apply_hooks
from .stage_pipeline import stage

__all__ = ["PASSING_HOOK", "apply_hooks", "stage"]
