"""Nonblocking, observation-scoped spectator projections for the EXE host.

The host must continue observing while a controller waits for native queries.
Only display packets are cached; no commands, leases or model state are cached.
"""
import copy
import math
import time


def _scope(world, team):
    growth = world.get('world_growth', {})
    return (world.get('run_id'), world.get('navigation_revision'),
            world.get('control_epochs', {}).get(team), world.get('control', {}).get(team),
            growth.get('revision') if growth.get('enabled') else None,
            growth.get('mission', {}).get('index', 0))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


class AttachedDisplayCache:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.entries = {}

    def clear(self, team=None):
        if team is None:
            self.entries.clear()
        else:
            self.entries.pop(team, None)

    def sample(self, team, controller, current_world, presentation):
        scope = _scope(current_world, team)
        entry = self.entries.get(team)
        if entry and entry['scope'] != scope:
            self.clear(team)
            entry = None
        status = 'retained_busy' if entry else 'unavailable_busy'
        # Do not wait behind controller.tick's synchronous candidate queries.
        if controller.lock.acquire(blocking=False):
            try:
                observed = getattr(controller, 'world', {})
                if scope[0] and _scope(observed, team) == scope:
                    snapshot = controller.snapshot(lightweight=True)
                    sidebar = presentation.project(team, controller.plan or {}, controller.version,
                                                   observed, current_world)
                    entry = dict(scope=scope, snapshot=snapshot, sidebar=sidebar,
                                 tick=observed.get('tick'), game_time=observed.get('time'),
                                 captured_at=self.clock())
                    self.entries[team] = entry
                    status = 'captured'
                else:
                    status = 'retained_waiting_controller' if entry else 'awaiting_controller_snapshot'
            finally:
                controller.lock.release()
        sampled_time = entry['game_time'] if entry else None
        current_time = current_world.get('time')
        source = dict(source='controller_observation_projection', cache_status=status,
                      run_id=scope[0], navigation_revision=scope[1],
                      sampled_tick=entry['tick'] if entry else None, sampled_game_time=sampled_time,
                      published_tick=current_world.get('tick'), published_game_time=current_time,
                      age_game_s=round(max(0, current_time-sampled_time), 3)
                                 if _number(current_time) and _number(sampled_time) else None,
                      age_wall_s=round(max(0, self.clock()-entry['captured_at']), 3) if entry else None,
                      applies_to=['snapshot', 'sidebar'],
                      basis='same_controller_lock_capture; retained packets keep their original sample, not the new native tick')
        snapshot = copy.deepcopy(entry['snapshot']) if entry else None
        if snapshot is not None:
            snapshot['display_sample'] = copy.deepcopy(source)
        return dict(snapshot=snapshot, sidebar=copy.deepcopy(entry['sidebar']) if entry else None,
                    sample=source)
