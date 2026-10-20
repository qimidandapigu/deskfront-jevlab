"""Read-only commander plan projection for the native spectator sidebar.

This is a record of plans observed after controller validation, not native
order acceptance or a causal explanation. Actual execution remains native.
"""
import copy
import math

from commander_tactical_brief import brief_signature


PLAN_FIELDS = ('region_id', 'position', 'radius', 'stage', 'equipment_goal', 'tactical_brief')


def _meaning(plan, field):
    value = plan.get(field)
    if field == 'tactical_brief':
        return brief_signature(value)
    if field == 'equipment_goal' and isinstance(value, dict):
        return (value.get('equipment_id'), value.get('phase'), value.get('state_basis'))
    return value


def _identity(world, faction):
    growth = world.get('world_growth', {})
    return (world.get('run_id'), world.get('control_epochs', {}).get(faction),
            world.get('control', {}).get(faction),
            growth.get('revision') if growth.get('enabled') else None,
            growth.get('mission', {}).get('index', 0))


def _plan(plan):
    # Do not leak other model context, hidden reasoning, or another faction's
    # data into the UI. Only the explicit, validated plan fields are projected.
    return dict(objective=str(plan.get('objective', ''))[:600],
                stage=str(plan.get('stage', ''))[:100],
                region_id=str(plan.get('region_id', ''))[:100],
                position=copy.deepcopy(plan.get('position') or []),
                radius=plan.get('radius'),
                equipment_goal=copy.deepcopy(plan.get('equipment_goal') or {}),
                tactical_brief=copy.deepcopy(plan.get('tactical_brief') or {}))


class CommandPresentation:
    """Maintain small, faction-local histories without changing controllers."""

    def __init__(self):
        self._teams = {}

    def project(self, faction, plan, version, controller_world, current_world):
        """Return a detached sidebar packet; call while holding controller.lock.

        Both worlds must refer to the same run, encounter, and control epoch.
        This prevents an old asynchronous controller snapshot being relabeled
        as the current mission. Empty/invalidated plans also clear old goals.
        """
        identity = _identity(current_world, faction)
        valid = bool(identity[0]) and _identity(controller_world, faction) == identity
        status = 'planned' if valid and plan else 'awaiting_plan' if valid else 'awaiting_snapshot'
        previous = self._teams.get(faction)
        if not valid or not plan:
            self._teams.pop(faction, None)
            projected, changes, observed_at, display_revision = {}, [], None, 0
        else:
            projected = _plan(plan)
            at = controller_world.get('time')
            observed_at = at if type(at) in (int, float) and math.isfinite(at) else None
            if previous and (previous['identity'] != identity or version < previous['version']):
                previous = None
            changes = copy.deepcopy(previous['changes']) if previous else []
            display_revision = previous['display_revision'] if previous else 1
            brief_meaning = brief_signature(projected['tactical_brief'])
            previous_brief_meaning = previous.get('brief_meaning') if previous else None
            if previous:
                fields = [field for field in PLAN_FIELDS
                          if (previous_brief_meaning if field == 'tactical_brief'
                              else _meaning(previous['plan'], field)) != _meaning(projected, field)
                          and (field != 'tactical_brief' or projected['tactical_brief'])]
                # The controller increments versions for executable changes.
                # A wording refresh, request ID, or periodic poll is not a new
                # command. The optional typed diagram has its own display
                # revision and never changes tactical/executor versions.
                if fields and (version != previous['version'] or 'tactical_brief' in fields):
                    display_revision += 1
                    changes.insert(0, dict(plan_version=version, display_revision=display_revision, observed_at=observed_at,
                                           changed_fields=fields,
                                           before=copy.deepcopy(previous['plan']),
                                           after=copy.deepcopy(projected)))
                    changes = changes[:3]
                else:
                    observed_at = previous['observed_at']
            self._teams[faction] = dict(identity=identity, version=version,
                                       plan=copy.deepcopy(projected), changes=copy.deepcopy(changes),
                                       observed_at=observed_at, display_revision=display_revision,
                                       # Missing/invalid optional annotation clears the
                                       # drawing, but its later identical return is
                                       # not a newly declared tactical change.
                                       brief_meaning=brief_meaning or previous_brief_meaning)
        presentation = dict(schema_version=1, faction=faction, run_id=identity[0],
                            mission_index=identity[-1], plan_version=version,
                            display_revision=display_revision,
                            status=status, source=str(plan.get('source', '')) if valid and plan else '',
                            basis='controller_plan_observation', observed_at=observed_at,
                            plan=projected, previous_plan=copy.deepcopy(changes[0]['before']) if changes else {},
                            changes=changes)
        return dict(commander=projected.get('objective', ''),
                    goal=copy.deepcopy(projected.get('position', [])),
                    region_id=projected.get('region_id', ''),
                    stage=projected.get('stage', ''), mission_index=identity[-1],
                    presentation=presentation)
