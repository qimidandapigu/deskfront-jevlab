"""Freshness-checked, read-only Godot query results for the model context."""
import json
import math
from pathlib import Path

def read_queries(path, state, unit):
    try:
        report=json.loads(Path(path).read_text(encoding='utf-8'))
        # Paused opening snapshots can precede the final physics query by one
        # 60 Hz tick. Do not relax clock ordering during normal gameplay.
        tolerance=1/60+1e-9 if state.get('paused') or state.get('spatial_clock_paused') else 0
        if report['run_id'] != state['run_id'] or not -tolerance <= state['time']-report['time'] <= 2:return {}
        # A fresh timestamp can still describe destroyed or rebuilt cover.
        # Older report fixtures lack this field; newly published Godot reports
        # always include it and are rejected when map geometry has changed.
        revision=report.get('navigation_revision')
        if revision is not None and revision != state.get('navigation_revision'):return {}
        result=report['units'].get(unit['id'], {})
        if math.dist(result['origin'],unit['position']) > .15:return {}
        return dict(result, sampled_at=report['time'], navigation_revision=revision)
    except (OSError,ValueError,KeyError,TypeError):return {}
