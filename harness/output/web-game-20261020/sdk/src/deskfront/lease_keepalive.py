"""Bounded asynchronous maintenance of an already acquired native lease.

No acquire, command retry or control takeover occurs here. A lost renewal reply
has unknown outcome; only the native read endpoint may confirm its new expiry.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import math
import time
import urllib.parse


class LeaseKeepaliveError(ValueError):
    pass


def _expiry(lease):
    value = lease.get('expiresAtRealTime')
    return float(value) / 1000 if type(value) in (int, float) and math.isfinite(value) else None


class LeaseKeepalive:
    def __init__(self, client, team, lease, *, record=None, clock=time.monotonic,
                 wall_clock=time.time, executor=None):
        self.client, self.team = client, team
        self.clock, self.wall_clock = clock, wall_clock
        self.record = record or (lambda row: None)
        self.pool = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='lease-' + team)
        self.pending = None
        self.generation = 0
        self.unknown = None
        self.next_probe = 0
        self.closed = False
        self.replace(lease)

    def _event(self, kind, **fields):
        self.record(dict(type='lease-keepalive', faction=self.team, event=kind, **fields))

    def replace(self, lease):
        if _expiry(lease) is None or lease.get('status') != 'active':
            raise LeaseKeepaliveError('lease_invalid_initial_state')
        self.lease = copy.deepcopy(lease)
        self.generation += 1
        self.unknown = None
        self.next_probe = 0
        # An old real Future keeps this team's only lane until completion.

    def _validate(self, value, prior, context):
        if not isinstance(value, dict):raise LeaseKeepaliveError('lease_invalid_native_reply')
        if (value.get('leaseId') != prior.get('leaseId') or value.get('epoch') != prior.get('epoch')
                or value.get('context', {}).get('runId') != context.get('runId')
                or value.get('context', {}).get('instanceId') != context.get('instanceId')
                or value.get('context', {}).get('instanceId') != prior.get('context', {}).get('instanceId')
                or value.get('scope') != prior.get('scope') or value.get('ownerId') != prior.get('ownerId')):
            raise LeaseKeepaliveError('lease_identity_changed')
        if value.get('status') != 'active':raise LeaseKeepaliveError('lease_' + str(value.get('status', 'unavailable')))
        if _expiry(value) is None:raise LeaseKeepaliveError('lease_invalid_native_expiry')
        return _expiry(value) > _expiry(prior)

    def _renew(self, context, lease):
        try:
            return dict(kind='renewed', value=self.client.lease_change('renew', context, self.team, lease))
        except Exception as error:
            # The native operation may already have run. Never replay it.
            code = getattr(error, 'code', None)
            if code == 'ack_timeout' or isinstance(error, (OSError, TimeoutError)):
                return dict(kind='unknown', error=code or type(error).__name__)
            raise

    def _probe(self, lease):
        return dict(kind='observed', value=self.client.request('/v1/control/' + urllib.parse.quote(lease['leaseId'], safe='')))

    def tick(self, context, world):
        if self.closed:return
        if (context.get('runId') != self.lease.get('context', {}).get('runId')
                or context.get('instanceId') != self.lease.get('context', {}).get('instanceId')
                or world.get('control', {}).get(self.team) != 'agent'
                or world.get('control_epochs', {}).get(self.team) != self.lease.get('epoch')):
            self._event('control_changed')
            raise LeaseKeepaliveError('lease_control_changed')
        now = self.clock()
        if self.pending and self.pending['future'].done():
            pending, self.pending = self.pending, None
            if pending['generation'] != self.generation:
                self._event('old_result_discarded')
            else:
                try:
                    result = pending['future'].result()
                    if result['kind'] == 'unknown':
                        self.unknown = dict(prior=pending['lease'], context=pending['context'])
                        self._event('renewal_outcome_unknown', error=result['error'])
                    else:
                        renewed = self._validate(result['value'], pending['lease'], pending['context'])
                        if renewed:
                            self.lease = copy.deepcopy(result['value'])
                            self.unknown = None
                            self._event('renewal_confirmed', confirmation='native_read' if result['kind'] == 'observed' else 'native_ack',
                                        expiresAtRealTime=self.lease['expiresAtRealTime'])
                        elif result['kind'] == 'renewed':
                            # A successful HTTP response without a later native
                            # deadline is not proof that this renewal succeeded.
                            self.unknown = dict(prior=pending['lease'], context=pending['context'])
                            self._event('renewal_outcome_unknown', error='expiry_not_extended')
                except Exception as error:
                    code = getattr(error, 'code', None)
                    if pending['kind'] == 'probe' and (isinstance(error, (OSError, TimeoutError)) or code in ('ack_timeout', 'engine_offline')):
                        self._event('confirmation_read_unavailable', error=code or type(error).__name__)
                    else:
                        self._event('maintenance_failed', error=code or str(error)[:100])
                        raise LeaseKeepaliveError('lease_maintenance_failed:' + str(code or error)) from error
        if self.wall_clock() >= _expiry(self.lease):
            self._event('expired_unconfirmed' if self.unknown else 'expired')
            raise LeaseKeepaliveError('lease_renew_unconfirmed' if self.unknown else 'lease_expired')
        if self.pending:return
        if self.unknown:
            if now < self.next_probe:return
            self.next_probe = now + 1
            prior = self.unknown['prior']
            self.pending = dict(kind='probe', future=self.pool.submit(self._probe, copy.deepcopy(prior)),
                                generation=self.generation, lease=copy.deepcopy(prior), context=copy.deepcopy(context))
            return
        if _expiry(self.lease) - self.wall_clock() > 20:return
        prior = copy.deepcopy(self.lease)
        self.pending = dict(kind='renew', future=self.pool.submit(self._renew, copy.deepcopy(context), prior),
                            generation=self.generation, lease=prior, context=copy.deepcopy(context))
        self._event('renewal_started', expiresAtRealTime=prior['expiresAtRealTime'])

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
