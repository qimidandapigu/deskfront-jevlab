"""Choice validation owned by the open Harness; no native provider import."""
import math


def checked_choice(answer, options):
    if not isinstance(answer, dict) or answer.get('type') != 'choice' or answer.get('choice') not in options:
        raise ValueError('invalid_jev_choice')
    probs, confidence = answer.get('probabilities'), answer.get('confidence')
    valid = lambda v: type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
    if not valid(confidence) or not isinstance(probs, dict) or set(probs) != set(options) or not all(valid(v) for v in probs.values()) or abs(sum(probs.values()) - 1) > .02:
        raise ValueError('invalid_jev_probabilities')
    return answer['choice']
