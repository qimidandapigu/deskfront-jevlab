#!/usr/bin/env python3
"""MIT. Loopback-only control plane; Godot is the only simulation authority."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import argparse, json, time, threading, uuid, collections, urllib.parse, math
from command_protocol import validate_command as _validate_command

ROOT=Path(__file__).resolve().parents[1]
SERVICE_VERSION=json.loads((ROOT/'package.json').read_text())['version']
ALLOWED={'soldier_order','unit_emotion','squad_order','demo_step','debug_visualize','scenario','control','move','capture','flank','cover','hold','retreat','attack','pause','speed','camera','reinforce','config','reset','map','equip','grenade','posture','man_at_gun','leave_gun','garrison','leave_building'}
TACTICS={'soldier_order','unit_emotion','squad_order','move','capture','flank','cover','hold','retreat','attack','grenade','posture','man_at_gun','leave_gun','garrison','leave_building'}
TEAMS={'green','blue','red'}

def validate_command(c, agent=False):
    """Compatibility entry point; protocol rules live in command_protocol."""
    return _validate_command(c, agent, allowed=ALLOWED, tactics=TACTICS, teams=TEAMS, root=ROOT)

class State:
    def __init__(self):
        self.lock=threading.Lock();self.state={};self.updated=0;self.pending={};self.results=collections.OrderedDict();self.recorded=0
        self.instance_id=None
        (ROOT/'output').mkdir(exist_ok=True)
    def open_session(self):
        """An explicit dashboard launch owns one engine; late old syncs cannot reclaim it."""
        with self.lock:
            for id in self.pending:
                self.results[id]={'id':id,'accepted':False,'message':'session_replaced'}
            self.pending.clear();self.state={};self.updated=0
            self.instance_id=str(uuid.uuid4())
            while len(self.results)>256:self.results.popitem(last=False)
            return 200,{'instance_id':self.instance_id}
    def record(self,kind,data):
        with (ROOT/'output/session.jsonl').open('a') as f:f.write(json.dumps({'at':time.time(),'kind':kind,'data':data},ensure_ascii=False)+'\n')
        if kind=='snapshot' and STUDIO:STUDIO.observe(data)
    def submit(self,command,agent=False,source=None):
        error=validate_command(command,agent or source=='lm')
        if error:return 400,{'error':error}
        with self.lock:
            if self.instance_id is not None and not agent and source!='lm' and command.get('instance_id')!=self.instance_id:return 409,{'error':'session_replaced'}
            if 'instance_id' in command and command['instance_id']!=self.instance_id:return 409,{'error':'session_replaced'}
            if not self.state or not self.updated or time.monotonic()-self.updated>5:return 409,{'error':'engine_offline'}
            if 'run_id' in command and command['run_id']!=self.state.get('run_id'):return 409,{'error':'stale_run'}
            if len(self.pending)>=64:return 429,{'error':'queue_full'}
            c=dict(command);c['source']=source if source=='lm' else ('agent' if agent else 'console')
            if source=='lm':
                team=c.get('faction','green')
                if self.state.get('control',{}).get(team)!='lm' or c.get('control_epoch')!=self.state.get('control_epochs',{}).get(team,0):return 409,{'error':'lm_authority_changed'}
                if c['action']!='squad_order' and len(c.get('unit_ids',[]))!=1:return 400,{'error':'lm_single_unit_required'}
                alive={u['id'] for u in self.state.get('units',[]) if u.get('faction')==team and u.get('hp',0)>0}
                if any(uid not in alive for uid in c.get('unit_ids',[])):return 400,{'error':'invalid_unit_authority'}
                if c['action']=='squad_order' and not self.state.get('squad_behavior',{}).get('enabled'):return 409,{'error':'human_squad_disabled'}
            c['id']=str(uuid.uuid4());c['_queued']=time.monotonic();c['_run']=self.state.get('run_id')
            self.pending[c['id']]=c
            self.record('command',c)
            return 202,{'id':c['id'],'status':'queued','note':'Wait for Godot acknowledgement'}
    def sync(self,payload):
        if not isinstance(payload,dict) or not isinstance(payload.get('state'),dict):return 400,{'error':'invalid_state'}
        s=payload['state']
        if s.get('schema_version')!=1 or not isinstance(s.get('units'),list):return 400,{'error':'invalid_schema'}
        with self.lock:
            instance=payload.get('instance_id')
            if self.instance_id is not None and instance!=self.instance_id:return 409,{'error':'session_replaced','commands':[]}
            if instance is not None:
                if not isinstance(instance,str) or not instance or len(instance)>128:return 400,{'error':'invalid_instance'}
                self.instance_id=instance
            for ack in payload.get('acks',[]):
                if not isinstance(ack,dict):continue
                if ack.get('id') not in self.pending:continue
                self.pending.pop(ack.get('id'),None);self.results[ack.get('id')]=ack;self.record('ack',ack)
            for id,c in list(self.pending.items()):
                if c['_run']!=s.get('run_id') or time.monotonic()-c['_queued']>10:
                    self.results[id]={'id':id,'accepted':False,'message':'stale_run' if c['_run']!=s.get('run_id') else 'command_timeout'};del self.pending[id]
            self.state=s;self.updated=time.monotonic()
            if self.updated-self.recorded>1:self.record('snapshot',s);self.recorded=self.updated
            while len(self.results)>256:self.results.popitem(last=False)
            return 200,{'commands':[{k:v for k,v in c.items() if not k.startswith('_')} for c in self.pending.values()]}

STATE=State()
LM=None
STUDIO=None

class Handler(SimpleHTTPRequestHandler):
    def log_message(self,fmt,*args):
        if args and '/api/' not in str(args[0]):super().log_message(fmt,*args)
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        super().end_headers()
    def json(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/state':
            with STATE.lock:payload={'instance_id':STATE.instance_id,'engine_live':bool(STATE.updated) and time.monotonic()-STATE.updated<3,'age_seconds':round(time.monotonic()-STATE.updated,2) if STATE.updated else None,'state':STATE.state,'pending':len(STATE.pending),'acks':list(STATE.results.values())[-12:]}
            payload['lm']=LM.snapshot() if LM else {'configured':False}
            self.json(200,payload)
        elif path=='/api/health':self.json(200,{'service':'deskfront-control','version':SERVICE_VERSION,'capabilities':['flag_defeat_warning'],'schema_version':1,'engine_live':bool(STATE.updated) and time.monotonic()-STATE.updated<3})
        elif path.startswith('/api/result/'):
            id=path.rsplit('/',1)[-1]
            with STATE.lock:self.json(200,STATE.results.get(id,{'id':id,'status':'queued' if id in STATE.pending else 'unknown'}))
        elif path=='/api/lm/calls':
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                before=int(query['before'][0]) if 'before' in query else None
                self.json(200,LM.call_log.list(before=before,unit=query.get('unit',[''])[0],run=query.get('run',[''])[0]) if LM else {'items':[],'units':[],'next_before':None})
            except ValueError:self.json(400,{'error':'invalid_cursor'})
        elif path.startswith('/api/lm/calls/'):
            try:row=LM.call_log.get(int(path.rsplit('/',1)[-1])) if LM else None
            except ValueError:row=None
            self.json(200 if row else 404,row or {'error':'call_not_found'})
        elif path=='/api/studio/schema':self.json(200,json.loads((ROOT/'data/studio-scenario.schema.json').read_text()))
        elif path=='/api/studio/catalog':
            from scenario_authoring import catalog
            self.json(200,catalog())
        elif path=='/api/studio/status':self.json(200,STUDIO.status() if STUDIO else {'configured':False,'scenarios':[],'reports':[],'jobs':[]})
        elif path.startswith('/api/studio/'):
            parts=path.strip('/').split('/')
            kinds={'scenarios':'scenario','reports':'report','jobs':'job'}
            row=STUDIO.store.get(kinds[parts[2]],parts[3]) if STUDIO and len(parts)==4 and parts[2] in kinds else None
            self.json(200 if row else 404,row or {'error':'studio_artifact_not_found'})
        elif path=='/api/lm/status':self.json(200,LM.snapshot() if LM else {'configured':False})
        elif path=='/api/action-catalog':self.json(200,json.loads((ROOT/'data/action-catalog.json').read_text()))
        elif path=='/api/schema':self.json(200,{'schema_version':1,'actions':sorted(ALLOWED),'agent_actions':sorted(TACTICS),'factions':sorted(TEAMS),'coordinates':'Godot meters [x,z], +Y up','agent_required':['faction','action','run_id','seen_tick'],'authority':'Godot validates team ownership, units, bounds and observation freshness'})
        else:
            allowed=ROOT/'build/web' if path.startswith('/play/') else ROOT/'dashboard'
            relative=path.removeprefix('/play/') if path.startswith('/play/') else path.lstrip('/')
            target=(allowed/(relative or 'index.html')).resolve()
            if not target.is_relative_to(allowed.resolve()) or not target.is_file():self.send_error(404);return
            self.path='/'+str(target.relative_to(ROOT));super().do_GET()
    def translate_path(self,path):return str(ROOT/urllib.parse.unquote(path).lstrip('/'))
    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':self.json(403,{'error':'origin_denied'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>262144:raise ValueError('invalid_length')
            payload=json.loads(self.rfile.read(length))
        except (ValueError,TypeError):self.json(400,{'error':'invalid_json'});return
        if self.path=='/api/session':status,result=STATE.open_session()
        elif self.path=='/api/sync':
            status,result=STATE.sync(payload)
            if status==200 and STUDIO:STUDIO.maybe_report()
        elif self.path=='/api/demo/choose':
            try:result=STUDIO.demo_director.choose(payload);status=200
            except ValueError as e:status,result=400,{'error':str(e)}
        elif self.path.startswith('/api/studio/'):
            try:
                if not STUDIO or not isinstance(payload,dict):raise ValueError('invalid_studio_request')
                action=self.path.rsplit('/',1)[-1]
                if action in ['generate','import','analyze','report']:
                    result=STUDIO.launch(action,payload);status=202
                elif action=='play':
                    artifact=STUDIO.store.get('scenario',str(payload.get('scenario_id','')))
                    if not artifact:raise ValueError('scenario_not_found')
                    player=payload.get('player_faction','green');opponent=payload.get('opponent_mode','game_ai')
                    if player not in ['green','blue','red','none'] or opponent not in ['game_ai','lm','agent']:raise ValueError('invalid_play_modes')
                    if opponent=='lm' and not LM.ready:raise ValueError('llm_not_configured')
                    modes={t:('player' if t==player else opponent) for t in TEAMS}
                    if payload.get('demo'):modes['blue']='game_ai'
                    status,result=STATE.submit({'action':'scenario','level':artifact['level'],'modes':modes,'demo':bool(payload.get('demo',False)),'demo_driver':LM.config.get('model','') if payload.get('demo_driver')=='model' else 'local_rehearsal','run_id':payload.get('run_id'),'instance_id':payload.get('instance_id')})
                else:raise ValueError('unknown_studio_action')
            except ValueError as e:status,result=400,{'error':str(e)}
        elif self.path in {'/api/command','/api/agent/command'}:
            if isinstance(payload,dict) and payload.get('action')=='control' and payload.get('mode')=='lm' and (not LM or not LM.ready):status,result=409,{'error':'lm_not_configured'}
            else:status,result=STATE.submit(payload,self.path=='/api/agent/command')
        else:status,result=404,{'error':'not_found'}
        self.json(status,result)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8768);parser.add_argument('--lm-env',help='External dotenv path; secrets remain server-side');args=parser.parse_args()
    global LM,STUDIO
    from lm_controller import LMController,load_config
    LM=LMController(STATE,load_config(args.lm_env));LM.start()
    from studio import Studio
    STUDIO=Studio(STATE,LM)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Deskfront: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:STUDIO.close();LM.close();server.server_close()
if __name__=='__main__':main()
