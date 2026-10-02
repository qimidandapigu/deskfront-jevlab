"""Scope a stock controller's scheduling to one faction without mutating engine state."""
import copy


class FactionState:
    def __init__(self, base, faction):
        self.base, self.faction = base, faction

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def state(self):
        snapshot = copy.deepcopy(self.base.state)
        # This view is used only by LMController's eligibility check. The complete
        # units/terrain/observations and real control epochs remain unchanged.
        snapshot['control'] = {t: mode if t == self.faction else 'game_ai'
                               for t, mode in snapshot.get('control', {}).items()}
        return snapshot

    def submit(self, command, *args, **kwargs):
        if command.get('faction') != self.faction:
            return 403, {'error': 'controller_faction_mismatch'}
        return self.base.submit(command, *args, **kwargs)
