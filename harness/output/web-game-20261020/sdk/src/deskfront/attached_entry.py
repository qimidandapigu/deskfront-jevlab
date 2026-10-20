"""Web-only lifecycle adapter over the unchanged public SDK and controllers."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'sdk/python'))
from quickplay import Game
from deskfront_bridge import DeskfrontClient, BridgeError
import attached_host
from lease_keepalive import LeaseKeepalive, LeaseKeepaliveError
import urllib.parse

def main():
    game=Game()
    class BrowserClient(DeskfrontClient):
        def observe(self,*args,**kwargs):
            waiting=False
            while not game.stopped.is_set():
                try:
                    value=super().observe(*args,**kwargs)
                    if waiting:game.record(dict(type='web-observation-resumed',runId=value['context']['runId']))
                    return value
                except BridgeError as error:
                    if error.code!='engine_offline':raise
                    if not waiting:game.record(dict(type='web-observation-paused',reason='awaiting_fresh_browser_tick'));waiting=True
                    if game.stopped.wait(.25):break
            raise BridgeError('web_session_stopped')
    attached_host.DeskfrontClient=BrowserClient
    class BrowserKeepalive(LeaseKeepalive):
        def tick(self,context,world):
            try:return super().tick(context,world)
            except LeaseKeepaliveError as error:
                if str(error) not in ('lease_renew_unconfirmed','lease_expired','lease_control_changed'):raise
                native=self.client.request('/v1/control/'+urllib.parse.quote(self.lease['leaseId'],safe=''))
                if native.get('ownerId')!=game.session_id or native.get('context',{}).get('runId')!=context.get('runId'):raise
                if native.get('status')=='active' and native.get('expiresAtRealTime',0)>self.lease.get('expiresAtRealTime',0):
                    self.replace(native);self._event('web_renewal_confirmed_by_read');return
                if native.get('status')=='active':
                    self._event('web_awaiting_native_lease_resolution');return
                fresh=self.client.observe(self.team)
                if native.get('status')!='expired' or fresh['state'].get('control',{}).get(self.team)!='game_ai':raise
                # A confirmed browser pause expiry is a new acquisition, never a
                # replay of an uncertain mutation or a takeover from a player.
                value=self.client.acquire(fresh['context'],self.team,game.session_id,world=self.team=='green')
                self.replace(value);self._event('web_expired_connection_reacquired',leaseId=value['leaseId'])
    attached_host.LeaseKeepalive=BrowserKeepalive
    attached_host.run(game)

if __name__=='__main__':main()
