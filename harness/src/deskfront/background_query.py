"""Pure compatibility and bounded-deadline helpers; no world or model policy."""
import inspect


def optional_kwargs(function, values):
    """Pass optional transport metadata once, without TypeError retry calls."""
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return values
    return {key:value for key,value in values.items() if key in parameters
            and parameters[key].kind != inspect.Parameter.POSITIONAL_ONLY}


def receipt_unknown(receipt):
    if not isinstance(receipt, dict):return False
    return (receipt.get('accepted') is None or receipt.get('message') in (
        'ack_timeout','command_timeout','receipt_pending','ack_unresolved','receipt_missing')
        or receipt.get('status') in ('pending','unknown','unresolved'))
