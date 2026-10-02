"""Pure HTTP command validation for the Deskfront control plane.

The server keeps the public action constants and the compatibility wrapper;
this module owns only the structural checks so protocol changes do not grow
inside the request handler.
"""

import json
import math
from pathlib import Path


def validate_command(c, agent=False, *, allowed, tactics, teams, root=None):
    """Return a stable protocol error string, or ``None`` when valid.

    ``allowed``/``tactics``/``teams`` are supplied by ``server`` so the
    release checker can keep its literal action catalog in one compatibility
    entry point.
    """
    if not isinstance(c, dict):
        return 'command_must_be_object'
    if c.get('action') not in (tactics if agent else allowed):
        return 'unknown_or_forbidden_action'
    if c.get('faction', 'green') not in teams:
        return 'unknown_faction'
    if 'unit_ids' in c and (not isinstance(c['unit_ids'], list) or len(c['unit_ids']) > 10 or not all(isinstance(x, str) for x in c['unit_ids'])):
        return 'invalid_unit_ids'
    if 'position' in c:
        p = c['position']
        if not isinstance(p, list) or len(p) != 2 or not all(type(x) in (int, float) and math.isfinite(x) for x in p):
            return 'invalid_position'
    if c['action'] == 'unit_emotion' and (len(c.get('unit_ids', [])) != 1 or c.get('emotion') not in {'calm', 'alert', 'nervous', 'afraid', 'determined', 'relieved'}):
        return 'invalid_emotion'
    if c['action'] == 'soldier_order':
        if len(c.get('unit_ids', [])) != 1 or c.get('intent') not in {'adjust_position', 'take_cover', 'wait_support', 'report_blocked'}:
            return 'invalid_soldier_intent'
        if not isinstance(c.get('squad_id'), str) or not isinstance(c.get('order_id'), str):
            return 'invalid_squad_identity'
    if c['action'] == 'squad_order':
        if c.get('intent') not in {'advance', 'cover', 'bound', 'flank', 'hold', 'regroup'}:
            return 'invalid_squad_intent'
        if not isinstance(c.get('squad_id'), str) or not 1 <= len(c['squad_id']) <= 100 or not isinstance(c.get('order_id'), str) or not 1 <= len(c['order_id']) <= 160:
            return 'invalid_squad_identity'
        if not c.get('unit_ids') or len(set(c['unit_ids'])) != len(c['unit_ids']):
            return 'invalid_squad_members'
        if 'position' not in c or type(c.get('radius')) not in (int, float) or not math.isfinite(c['radius']) or not .06 <= c['radius'] <= 2:
            return 'invalid_squad_region'
    if c['action'] == 'demo_step' and (not isinstance(c.get('step_id'), str) or len(c['step_id']) > 100):
        return 'invalid_demo_step'
    if c['action'] == 'move' and 'position' not in c:
        return 'position_required'
    if c['action'] in {'speed', 'config'} and (type(c.get('value')) not in (int, float) or not math.isfinite(c['value'])):
        return 'invalid_value'
    if c['action'] == 'pause' and 'value' in c and type(c['value']) is not bool:
        return 'invalid_pause'
    if c['action'] == 'debug_visualize' and (type(c.get('value')) is not bool or not isinstance(c.get('unit', ''), str)):
        return 'invalid_debug_options'
    if c['action'] == 'control' and c.get('mode') not in {'game_ai', 'player', 'agent', 'lm'}:
        return 'invalid_mode'
    if 'floor' in c and (type(c['floor']) is not int or c['floor'] not in (1, 2)):
        return 'invalid_floor'
    if 'gun_id' in c and not isinstance(c['gun_id'], str):
        return 'invalid_gun_id'
    if c['action'] == 'attack' and not isinstance(c.get('target_id'), str):
        return 'target_required'
    if c['action'] == 'scenario' and (not isinstance(c.get('level'), dict) or not isinstance(c.get('modes', {}), dict)):
        return 'invalid_scenario'
    if c['action'] == 'map':
        map_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        levels = json.loads((map_root / 'data/sandbox-maps.json').read_text())['levels']
        if type(c.get('index')) is not int or c['index'] not in range(len(levels)):
            return 'invalid_map'
    if c['action'] == 'posture' and c.get('posture') not in {'auto', 'stand', 'crouch', 'prone'}:
        return 'invalid_posture'
    if c['action'] == 'equip' and c.get('weapon') not in {'rifle', 'smg', 'rocket', 'pistol'}:
        return 'invalid_weapon'
    if agent and (not isinstance(c.get('run_id'), str) or type(c.get('seen_tick')) is not int):
        return 'observation_required'
    return None
