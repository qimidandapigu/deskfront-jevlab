"""Keep staged survival consistent with the native incoming-fire contract.

The anti-armor charge adapter already suppresses ``incoming_fire`` while a
validated satchel rush is active. Outside that explicit action, a real
incoming-fire observation must immediately enter the native safety path.
"""

from .stage import apply_hooks


def install(source: str) -> str:
    return apply_hooks(source, [dict(
        name='real incoming fire keeps native immediate survival',
        before='\tvar danger: bool=incoming_fire or outmatched or compromised or (under_fire and (hp/max_hp<game.config.tactics.survival_hp or suppression>.72))',
        after='\tvar danger: bool=incoming_fire or outmatched or compromised or (under_fire and (hp/max_hp<game.config.tactics.survival_hp or suppression>.72))',
    )])
