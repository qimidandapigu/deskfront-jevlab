"""Bound repeated idle choices without choosing a route for the executor."""


def constrain_idle_routes(options, task, unit, feedback, cover_state):
    """Require a route choice only when a safe native short step is available.

    A waiting occupier may prepare a position but may not bypass its partner
    dependency to capture the flag. The model still chooses among the remaining
    routes, posture changes, and protection actions.
    """
    command=(task or {}).get('command')
    if command not in ('occupy','support','eliminate','flank'):
        return False
    failed_fire=(feedback.get('local_failure') or {}).get('action')=='local_reposition'
    if command!='occupy' and not failed_fire:
        return False
    combat = unit.get('combat') or {}
    if ((cover_state != 'none' and not failed_fire) or
            (combat.get('path_active') and not feedback.get('path_stalled')) or
            combat.get('engageable_targets') or
            unit.get('order_mode') == 'self_preserve' or
            unit.get('reload_remaining', 0) > 0 or
            unit.get('suppression', 0) >= .5 or
            unit.get('hp', 0) / max(1, unit.get('max_hp', 1)) < .35 or
            feedback.get('no_movement_seconds', 0) < 3 or
            feedback.get('unproductive_seconds', 0) < 3):
        return False
    safe_steps = [key for key, item in options.items()
                  if key.startswith(('local_', 'region_goal_')) and
                  item.get('command', {}).get('action') == 'move' and
                  item.get('native_step_risk', {}).get('status') == 'sampled' and
                  item['native_step_risk'].get('peak_attackers') == 0 and
                  item['native_step_risk'].get('exposed_s', 0) <= .2]
    if not safe_steps:
        return False
    options.pop('continue_task', None)
    options.pop('halt', None)
    return True
