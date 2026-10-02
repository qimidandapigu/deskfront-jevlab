"""Portable paths shared by Deskfront Harness checks.

The Harness is normally a sibling checkout of Deskfront, but the published
layout embeds it at ``<deskfront>/harness``.  Keep an explicit
``DESKFRONT_ROOT`` authoritative, then detect the embedded parent and finally
retain the historical sibling fallback.
"""

import os
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[1]
_embedded_root = HARNESS_ROOT.parent
_legacy_root = _embedded_root / "deskfront-jevlab"


def _configured_root() -> Path:
    value = os.environ.get("DESKFRONT_ROOT")
    if value:
        return Path(value).expanduser().resolve()
    if (_embedded_root / "project.godot").is_file():
        return _embedded_root
    return _legacy_root


DESKFRONT_ROOT = _configured_root()
DESKFRONT_TOOLS = DESKFRONT_ROOT / "tools"
