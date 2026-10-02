"""Staging orchestration for a temporary Harness engine copy.

Each phase lives in a responsibility-specific module; this facade keeps the
legacy private helper imports and the public ``stage`` entry stable.
"""
from pathlib import Path

from .stage_source import _copy_source_tree
from .stage_overlay import _install_overlay_assets, _install_overlay_autoload
from .stage_squads import _patch_squads
from .stage_unit import _patch_unit
from .stage_combat import _patch_combat_fx
from .stage_world import _patch_world_and_tactics, _install_world_assets


def stage(root, destination):
    root, destination = Path(root), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).parent
    _copy_source_tree(root, destination)
    emoji_codes = _install_overlay_assets(destination, here)
    _patch_squads(destination, here)
    _patch_unit(destination, here)
    _patch_combat_fx(destination, here)
    _patch_world_and_tactics(destination, here, emoji_codes)
    _install_world_assets(destination, here)
    _install_overlay_autoload(destination)
    return destination
