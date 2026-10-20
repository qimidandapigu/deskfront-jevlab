"""Public Deskfront SDK extension. Stdlib only; never reads game source files."""
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import time


class BridgeError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class BridgeTransportError(OSError):
    """Transport diagnosis includes method/path, never request bodies or keys."""
    pass


class BridgeDeadlineError(BridgeTransportError):
    """The caller's whole-operation deadline, not a fresh socket allowance."""
    pass


class DeskfrontClient:
    @staticmethod
    def _read_json(response,deadline):
        if deadline is None:return json.load(response)
        parts=[]
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise BridgeDeadlineError('local_bridge_deadline: response_body')
            # urllib's socket timeout is per read. Refresh it to the caller's
            # remaining total time before each non-greedy body chunk.
            raw=getattr(getattr(response,'fp',None),'raw',None)
            socket=getattr(raw,'_sock',None)
            if socket is not None:socket.settimeout(min(5.,remaining))
            read=getattr(response,'read1',None)
            chunk=read(65536) if read else response.read()
            if time.monotonic()>=deadline:raise BridgeDeadlineError('local_bridge_deadline: response_body')
            if not chunk:break
            parts.append(chunk)
            if read is None:break
        return json.loads((b''.join(parts) if not parts or isinstance(parts[0],bytes) else ''.join(parts)))

    def __init__(self, connection):
        value = json.loads(Path(connection).read_text(encoding='utf-8-sig'))
        url = urllib.parse.urlsplit(value.get('url', ''))
        if value.get('protocol') != 'quickplay-bridge/v1' or value.get('status') != 'running':
            raise BridgeError('connection_not_running')
        if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.password:
            raise BridgeError('invalid_local_connection')
        self.url = value['url'].rstrip('/')
        self.instance_id = value['instanceId']
        self.pid = value.get('pid')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        info = self.request('/v1/info')
        if info.get('protocol') != 'quickplay-bridge/v1' or info.get('gameId') != 'deskfront':
            raise BridgeError('protocol_mismatch')
        if 'deskfront-harness/v1' not in info.get('extensions', []):
            raise BridgeError('player_upgrade_required')
        self.info = info

    def request(self, path, body=None, *, deadline=None):
        request = urllib.request.Request(self.url + path,
            data=json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None,
            headers={'Content-Type': 'application/json'})
        # Only GETs are replay-safe. Mutations may already have been accepted;
        # never resend acquire/command/renew automatically after a lost response.
        attempts = 3 if body is None else 1
        for attempt in range(attempts):
            remaining = deadline-time.monotonic() if deadline is not None else 5.
            if remaining <= 0:
                raise BridgeDeadlineError('local_bridge_deadline: '+request.get_method()+' '+path.split('?')[0])
            try:
                with self.opener.open(request, timeout=min(5.,remaining)) as response:
                    result = self._read_json(response,deadline)
                if deadline is not None and time.monotonic() >= deadline:
                    raise BridgeDeadlineError('local_bridge_deadline: '+request.get_method()+' '+path.split('?')[0])
                return result
            except urllib.error.HTTPError as error:
                try: code = json.loads(error.read())['code']
                except (ValueError, KeyError): code = 'http_' + str(error.code)
                raise BridgeError(code) from None
            except BridgeDeadlineError:
                raise
            except (OSError, TimeoutError) as error:
                if deadline is not None and time.monotonic()>=deadline:
                    raise BridgeDeadlineError('local_bridge_deadline: '+request.get_method()+' '+path.split('?')[0]) from error
                if attempt + 1 < attempts:
                    delay=.1*(attempt+1)
                    if deadline is not None:
                        remaining=deadline-time.monotonic()
                        if remaining <= delay:
                            raise BridgeDeadlineError('local_bridge_deadline: '+request.get_method()+' '+path.split('?')[0]) from error
                    time.sleep(delay)
                    continue
                raise BridgeTransportError(
                    f'local_bridge_transport: {request.get_method()} {path.split("?")[0]} '
                    f'failed after {attempts} attempt(s): {error}') from error

    def observe(self, team='green', spectator=False):
        row = self.request('/v1/deskfront/' + ('spectator' if spectator else 'state') + '?team=' + team)
        if row['context']['instanceId'] != self.instance_id:
            raise BridgeError('instance_changed')
        return row

    def acquire(self, context, team, owner, world=False):
        import uuid
        return self.request('/v1/control/acquire', dict(id=uuid.uuid4().hex, context=context,
            ownerId=owner, scope=dict(kind='team', id=team), teamId=team, leaseSeconds=30, worldControl=world))

    def lease_change(self, operation, context, team, lease):
        return self.request('/v1/control/' + operation, dict(context=context, teamId=team,
            leaseId=lease['leaseId'], epoch=lease['epoch'], leaseSeconds=30))

    def command(self, context, team, lease, command, ident, *, deadline=None):
        if command.get('action') == 'grow_world' and 'force_manifest' in command:
            if 'deskfront-forces/v1' not in self.info.get('extensions', []):
                # Older launcher HTTP code can still expose a newer native PCK.
                # Trust only the live engine's explicit schema, never the client version.
                observed = self.observe(team)
                cap = observed.get('state', {}).get('world_growth', {}).get('force_manifest_capability', {})
                if (cap.get('schema') != 'deskfront-forces/v1'
                        or cap.get('deployment_receipt') != 'deskfront-force-receipt/v1'
                        or type(cap.get('max_entities')) is not int or cap['max_entities'] < 1):
                    raise BridgeError('force_manifest_upgrade_required')
        return self.request('/v1/deskfront/commands', dict(id=ident, context=context, teamId=team,
            leaseId=lease['leaseId'], controlEpoch=lease['epoch'], command=command), deadline=deadline)

    def topology(self, context, team, actor):
        import uuid
        return self.request('/v1/query', dict(id=uuid.uuid4().hex, context=context, teamId=team,
            kind='topology', actorIds=[actor], parameters={}))['topology']
