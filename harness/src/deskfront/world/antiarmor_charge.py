"""Keep a short, validated satchel charge from becoming an armor retreat loop."""

from .stage import apply_hooks


def install(source: str) -> str:
    return apply_hooks(source, [
        dict(
            name='committed satchel approach does not flee merely from tank proximity',
            before='\tvar outmatched:bool=armor_threat!=null and weapon not in ["rocket","cannon"] and game.field.line_of_sight(armor_threat.pos(),pos()) and armor_threat.pos().distance_to(pos())<.85',
            after='\tvar antiarmor_charge: bool=has_method("harness_antiarmor_commit_active") and bool(call("harness_antiarmor_commit_active"))\n'
                  '\tvar outmatched:bool=armor_threat!=null and weapon not in ["rocket","cannon"] and game.field.line_of_sight(armor_threat.pos(),pos()) and armor_threat.pos().distance_to(pos())<.85 and not antiarmor_charge',
        ),
        dict(
            name='committed satchel approach tolerates ordinary incoming fire',
            before='\tvar incoming_fire: bool=game.human_squad and game.elapsed-last_threat_at<1.5',
            after='\tvar incoming_fire: bool=game.human_squad and game.elapsed-last_threat_at<1.5 and not antiarmor_charge',
        ),
    ])
