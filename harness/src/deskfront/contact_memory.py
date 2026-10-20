"""Bounded faction search clues, separate from live combat contacts."""
import copy
import math

from human_squad_validation import _position


class ContactMemory:
    def __init__(self, limit=32):
        self.limit = limit
        self.scope = None
        self.time = None
        self.records = {}

    def observe(self, world, team):
        now = world.get('time', 0.)
        growth = world.get('world_growth', {})
        scope = (world.get('run_id'), team,
                 world.get('control_epochs', {}).get(team),
                 world.get('control', {}).get(team),
                 growth.get('revision') if growth.get('enabled') else None)
        if scope != self.scope or (self.time is not None and now < self.time):
            self.records.clear()
        self.scope, self.time = scope, now
        dead = {u.get('id') for u in world.get('units', []) if u.get('hp', 0) <= 0}
        contacts = world.get('squad_behavior', {}).get('perception', {}).get(team, {}).get('contacts', [])
        if isinstance(contacts, dict):
            contacts = list(contacts.values())
        visible = set()
        for contact in contacts:
            uid = contact.get('id')
            seen = contact.get('last_seen', now if contact.get('visible') else None)
            if (not uid or uid in dead or not _position(contact.get('position'))
                    or not isinstance(seen, (int, float)) or not math.isfinite(seen)
                    or seen > now):
                continue
            if contact.get('visible'):
                visible.add(uid)
            # A native recent report is legitimate when this controller starts
            # between sighting and loss. Never seed memory from old raw units.
            if not contact.get('visible') and now - seen > 6.:
                continue
            old = self.records.get(uid)
            if old is None or seen > old['last_seen']:
                self.records[uid] = {key: copy.deepcopy(contact[key])
                                     for key in ('id', 'position', 'kind', 'weapon') if key in contact}
                self.records[uid]['last_seen'] = seen
        for uid in dead:
            self.records.pop(uid, None)
        self.records = dict(sorted(self.records.items(),
                                   key=lambda item: item[1]['last_seen'], reverse=True)[:self.limit])
        return [dict(copy.deepcopy(row), visible=False,
                     age_s=round(now - row['last_seen'], 1),
                     status='last_seen_unconfirmed', position_basis='last_visible_report')
                for uid, row in self.records.items() if uid not in visible]
