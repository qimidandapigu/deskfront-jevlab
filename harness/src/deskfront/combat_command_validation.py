"""Validate staged combat extensions while retaining the native control-plane checks."""

from soldier_emotions import EMOTIONS


SITE_INTENTS = {'move_to_site', 'rush_to_site', 'prone_approach',
                'occupy_cover', 'peek_fire'}
SELECTED_INTENTS = SITE_INTENTS | {'focus_fire', 'satchel'}


def validate(command, agent, native_validate):
    if not agent or not isinstance(command, dict):
        return native_validate(command, agent)

    action = command.get('action')
    if action == 'unit_emotion' and command.get('emotion') in EMOTIONS:
        # The native validator knows the common envelope but has an older
        # emotion vocabulary. The staged engine validates the real choice.
        return native_validate(dict(command, emotion='calm'), agent)

    if action == 'soldier_order' and command.get('intent') in SELECTED_INTENTS:
        intent = command['intent']
        if intent in SITE_INTENTS:
            if not isinstance(command.get('site_id'), str) or not command['site_id']:
                return 'site_id_required'
            if not isinstance(command.get('candidate_query_id'), str) or not command['candidate_query_id']:
                return 'candidate_query_id_required'
        if intent in {'peek_fire', 'focus_fire', 'satchel'}:
            if not isinstance(command.get('target_id'), str) or not command['target_id']:
                return 'target_required'
        return native_validate(dict(command, intent='adjust_position'), agent)

    return native_validate(command, agent)
