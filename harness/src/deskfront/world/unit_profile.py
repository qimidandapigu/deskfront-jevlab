"""Session-copy instrumentation; totals are inclusive when functions nest."""
import re


def instrument(source):
    methods = {
        'tick': ('dt: float', 'dt'),
        'survival_tick': ('', ''),
        'cover_behavior': ('', ''),
        'monitor_progress': ('dt: float', 'dt'),
        'update_firing_awareness': ('', ''),
        'animate': ('clip: String', 'clip'),
        'presentation_tick': ('dt: float', 'dt'),
    }
    for name, (args, values) in methods.items():
        pattern = r'(?m)^func ' + name + r'\([^\n]*\) -> void:'
        if len(re.findall(pattern, source)) != 1:
            raise RuntimeError('Missing profile method: ' + name)
        source = re.sub(pattern, 'func _profile_' + name + '(' + args + ') -> void:', source)
        if name == 'cover_behavior':
            # Cover/peek is presentation and local posture maintenance, not
            # an emergency safety gate.  The old wrapper recomputed the
            # native firing solution for every unit on every physics tick;
            # that made a crowded desk produce large synchronous spikes.
            # Keep movement, damage, firing and survival per tick, while
            # allowing the visual cover state to settle within 0.1 seconds.
            source += ('\nfunc ' + name + '(' + args + ') -> void:\n'
                       '\tif game.human_squad and game.elapsed<float(get_meta("harness_cover_next_at",0.0)):\n'
                       '\t\treturn\n'
                       '\tif game.human_squad:set_meta("harness_cover_next_at",game.elapsed+.10)\n'
                       '\tvar started: int=Time.get_ticks_usec()\n'
                       '\t_profile_' + name + '(' + values + ')\n'
                       '\tgame.record_cost("unit_detail/' + name + '",started)\n')
        else:
            source += ('\nfunc ' + name + '(' + args + ') -> void:\n'
                       '\tvar started: int=Time.get_ticks_usec()\n'
                       '\t_profile_' + name + '(' + values + ')\n'
                       '\tgame.record_cost("unit_detail/' + name + '",started)\n')
    for index, line in enumerate([
        '\tvar enemy=game.find_target(self,target_id if target_id!="" else focus_id)',
        '\tenemy=game.find_target(self,target_id if target_id!="" else focus_id)',
        '\t\t\tactor.advance_drive(Vector3(target.x,actor.position.y,target.y),speed,dt,lateral,locomotion)',
    ]):
        if source.count(line) != 1:
            raise RuntimeError('Missing profile call: ' + line)
        indent = line[:len(line)-len(line.lstrip())]
        label = 'target_search' if index < 2 else 'animation_drive'
        source = source.replace(line, indent + 'var measured_' + str(index) + ': int=Time.get_ticks_usec()\n' + line + '\n' + indent + 'game.record_cost("unit_detail/' + label + '",measured_' + str(index) + ')')
    route_loop = '\twhile not route.is_empty():\n\t\tvar can_skip: bool=route.size()>1 and game.field.segment_walkable(pos(),route[1],tank)'
    if source.count(route_loop) != 1:
        raise RuntimeError('Missing route advance profile anchor')
    source = source.replace(route_loop, '\tvar route_advance_started: int=Time.get_ticks_usec()\n' + route_loop)
    moving = '\tvar moving: bool=not route.is_empty()'
    if source.count(moving) != 1:
        raise RuntimeError('Missing movement profile anchor')
    source = source.replace(moving, '\tgame.record_cost("unit_detail/route_advance",route_advance_started)\n\tvar movement_started: int=Time.get_ticks_usec()\n' + moving)
    close_enemy = '\tvar close_enemy=game.closest_enemy(self)'
    if source.count(close_enemy) != 1:
        raise RuntimeError('Missing movement end profile anchor')
    source = source.replace(close_enemy, '\tgame.record_cost("unit_detail/movement",movement_started)\n' + close_enemy)
    posture = '\tupdate_posture(moving)'
    if source.count(posture) != 1:
        raise RuntimeError('Missing posture profile anchor')
    source = source.replace(posture, '\tvar posture_started: int=Time.get_ticks_usec()\n' + posture + '\n\tgame.record_cost("unit_detail/posture",posture_started)')
    steering = '\tif moving:\n\t\tvar target: Vector2=route[0]'
    if source.count(steering) != 1:
        raise RuntimeError('Missing steering profile anchor')
    source = source.replace(steering, '\tvar steering_started: int=Time.get_ticks_usec()\n' + steering)
    source = source.replace('\tgame.record_cost("unit_detail/movement",movement_started)\n' + close_enemy,
                            '\tgame.record_cost("unit_detail/steering",steering_started)\n\tgame.record_cost("unit_detail/movement",movement_started)\n' + close_enemy)
    return source
