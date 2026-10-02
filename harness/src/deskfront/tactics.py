"""Compatibility facade for Deskfront tactical coordination.

Keep this import path stable for the host and existing integrations while the
implementation is split by responsibility:

* :mod:`tactics_coordination` contains commander plans, state and options.
* :mod:`tactics_controller` contains the LM client/controller lifecycle.
* :mod:`tactics_policy` and :mod:`tactics_payload` remain pure policy/payload
  boundaries.
"""
from tactics_coordination import Coordination
from tactics_controller import CoordinatedClient, CoordinatedController

# Compatibility exports: tactical policy has no controller state.
from tactics_policy import (
    STYLES, ROLES, EXECUTOR_INTERVAL, COMMANDER_INTERVAL,
    COMMANDER_EVENT_COOLDOWN, DecisionSchedule, fit, support_ready, row_waiting,
)

__all__ = [
    'Coordination', 'CoordinatedClient', 'CoordinatedController',
    'STYLES', 'ROLES', 'EXECUTOR_INTERVAL', 'COMMANDER_INTERVAL',
    'COMMANDER_EVENT_COOLDOWN', 'DecisionSchedule', 'fit', 'support_ready',
    'row_waiting',
]
