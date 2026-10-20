"""Loopback host for a browser-owned Godot instance, using the accepted SDK code."""
from pathlib import Path
import argparse, json, time, sys, threading, uuid, urllib.parse
from http.server import ThreadingHTTPServer

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,required=True);parser.add_argument('--code',type=Path,required=True)
    args=parser.parse_args();folder=args.job.resolve();config=json.loads((folder/'web-config.json').read_text(encoding='utf-8'))
    sys.path.insert(0,str(args.code.resolve()))
    from release_runtime import State,handler
    class WebState(State):
        def __init__(self,*args):super().__init__(*args);self.request_local=threading.local()
        def submit(self,*args,**kwargs):
            code,value=super().submit(*args,**kwargs)
            if code==202:self.request_local.queued=value['id']
            return code,value
    state=WebState(config['instanceId'],folder);base=handler(state)
    class WebHandler(base):
        def json(self,code,value):
            if code==504 and value.get('code')=='ack_timeout' and self.path!='/v1/query':
                # Wait longer for this exact queued operation, without ever
                # replaying it. Commands still expire in the original queue.
                ident=getattr(state.request_local,'queued',None);until=time.monotonic()+8
                while ident and time.monotonic()<until:
                    with state.lock:ack=state.results.get(ident)
                    if ack:
                        code,value=(200,ack['sdk_result']) if ack.get('accepted') else (409,{'code':ack.get('message','rejected'),'message':'Engine rejected bridge operation'})
                        break
                    time.sleep(.02)
            return super().json(code,value)
        def do_GET(self):
            if self.path=='/web/health':
                with state.lock:
                    snapshot=state.state
                    payload={'live':bool(state.updated) and time.monotonic()-state.updated<5,'age':time.monotonic()-state.updated if state.updated else None,'runId':snapshot.get('run_id'),'tick':snapshot.get('tick'),'gameTime':snapshot.get('time'),'fps':snapshot.get('fps'),'boot':getattr(state,'web_boot',None),'world':snapshot.get('world_growth',{}).get('revision')}
                return self.json(200,payload)
            return super().do_GET()
        def do_POST(self):
            state.request_local.queued=None
            if self.path!='/api/sync':return super().do_POST()
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8*1024*1024:raise ValueError('invalid_length')
                payload=json.loads(self.rfile.read(length))
                boot=payload.get('web_boot')
                if not isinstance(boot,str) or not 8<=len(boot)<=80:raise ValueError('invalid_web_boot')
                with state.lock:
                    owner=getattr(state,'web_boot',None)
                    if owner and owner!=boot and time.monotonic()-state.updated<10:
                        return self.json(409,{'error':'web_instance_already_open','commands':[]})
                    state.web_boot=boot
                code,result=state.sync(payload)
            except (ValueError,TypeError):code,result=400,{'error':'invalid_sync'}
            return self.json(code,result)
    server=ThreadingHTTPServer(('127.0.0.1',0),WebHandler);server.daemon_threads=True
    discovery={'protocol':'quickplay-bridge/v1','url':'http://127.0.0.1:'+str(server.server_port),'instanceId':config['instanceId'],'status':'running','pid':None,'mode':'godot-web','modelRequests':0}
    # Browser games have no native game PID. Never present the host as a game EXE.
    (folder/'connection.json').write_text(json.dumps(discovery,indent=2),encoding='utf-8')
    print(json.dumps({'url':discovery['url'],'mode':'godot-web'}),flush=True)
    try:server.serve_forever(poll_interval=.1)
    finally:
        discovery['status']='closed';(folder/'connection.json').write_text(json.dumps(discovery,indent=2),encoding='utf-8');server.server_close()

if __name__=='__main__':main()
