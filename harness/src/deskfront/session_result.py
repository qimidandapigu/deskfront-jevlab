"""Evidence-bound duel outcome classification outside the native game rules.

The game declares a winner for flag/clock results. A fixed duel can also end
when its controlled active squad is wholly eliminated. That is a Harness
session result; it does not rewrite the native snapshot's ``winner`` field.
"""
import math


def _hp(unit):
    value = unit.get('hp')
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def controlled_team_elimination(state, team, expected_unit_ids=None):
    """Return a documented loss only for an observed active duel battle."""
    if not isinstance(state, dict) or team not in ('green', 'red'):
        return None
    if state.get('winner') or (state.get('demo') or {}).get('phase') != 'battle':
        return None
    units = state.get('units')
    if not isinstance(units, list):
        return None
    participants = (state.get('demo') or {}).get('participants')
    if not isinstance(participants, list) or team not in participants:
        return None
    controlled = [u for u in units if isinstance(u, dict) and u.get('faction') == team
                  and u.get('deployment_phase') == 'active']
    opponents = [u for u in units if isinstance(u, dict) and u.get('faction') in participants
                 and u.get('faction') != team and u.get('deployment_phase') == 'active'
                 and _hp(u) is not None and _hp(u) > 0]
    observed_ids = {u.get('id') for u in controlled}
    if (not controlled or not opponents or any(_hp(u) is None or _hp(u) > 0 for u in controlled)
            or expected_unit_ids is not None and not set(expected_unit_ids) <= observed_ids):
        return None
    # A missing, parked, or undeployed participant is not evidence of death.
    teams = sorted({u['faction'] for u in opponents if isinstance(u.get('faction'), str)})
    return dict(outcome='lost', reason='controlled_squad_eliminated',
                controlled_team=team, eliminated_units=sorted(u['id'] for u in controlled),
                surviving_opponent_teams=teams,
                inferred_winner=teams[0] if len(teams) == 1 else None,
                native_winner=state.get('winner', ''), game_time=state.get('time'),
                basis='All observed active controlled units have HP <= 0; at least one active opponent has HP > 0. Native winner is unchanged.')


def engine_exit_outcome(state, team, returncode, *, duel_ready, expected_unit_ids=None):
    """Only an established elimination converts a process exit to a loss."""
    if duel_ready and returncode == 0:
        result = controlled_team_elimination(state, team, expected_unit_ids)
        if result is not None:
            return result
    return dict(outcome='error', reason='engine_exited', returncode=returncode)
