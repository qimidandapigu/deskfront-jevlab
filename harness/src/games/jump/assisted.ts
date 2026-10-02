import type { RealtimeGame } from '../../arena/plugin.js';
import { createJumpGame, type JumpState, INPUTS } from './adapter.js';
import { searchRoute, replayActions, type Action, type Level } from './engine.js';

interface AssistedState extends JumpState {
  receipt?: { disposition: 'accepted' | 'retained' | 'rejected'; reason?: string };
  selectedLanding?: string;
  routeQueue?: Action[];
  routeMode?: boolean;
  routeStatus?: string;
  routeVisits?: Record<string, number>;
}
interface Landing { id: string; actions: Action[]; x: number; y: number; frames: number; coins: number; key: boolean; switchOn: boolean; won: boolean }
const signature = (s: JumpState) => JSON.stringify([s.actor.x,s.actor.y,s.actor.grounded,s.actor.held,s.progress]);

/** Model chooses a verified landing; deterministic physics executes every frame. */
export function createAssistedJumpGame(level: Level): RealtimeGame<AssistedState> {
  const base = createJumpGame(level);
  let cachedKey = '', cached: Landing[] = [];
  function landings(s: AssistedState): Landing[] {
    const key = signature(s);
    if (key === cachedKey) return cached;
    cachedKey = key; cached = [];
    if (!s.actor.grounded || s.progress.won) return cached;
    const route = searchRoute(level, s.actor, s.progress, { maxNodes: 18000 });
    if (!route.verified || !route.actions) return cached;
    let frames = 0;
    const prefix: Action[] = [];
    for (const action of route.actions) {
      prefix.push({...action}); frames += action.frames;
      if (frames < (cached.length + 1) * 60 && frames < (route.frames ?? Infinity)) continue;
      const end = replayActions(level, s.actor, s.progress, prefix);
      if (!end.actor.grounded || end.actor.dead) continue;
      // Release on solid ground so a slow response cannot move or cut a jump.
      const actions = [...prefix.map(a => ({...a})), {move: 0 as const, jump: false, frames: 1}];
      const stable = replayActions(level, s.actor, s.progress, actions);
      if (!stable.actor.grounded || stable.actor.dead) continue;
      if (Math.abs(stable.actor.x-s.actor.x)<1 && stable.actor.y===s.actor.y && JSON.stringify(stable.progress)===JSON.stringify(s.progress)) continue;
      const hash = [...key].reduce((h,c)=>Math.imul(h,31)+c.charCodeAt(0)|0,0) >>> 0;
      cached.push({id:`landing-${hash}-${cached.length}`,actions,x:stable.actor.x,y:stable.actor.y,frames:frames+1,coins:stable.progress.coins.length-s.progress.coins.length,key:stable.progress.key,switchOn:stable.progress.switchOn,won:stable.progress.won});
      if (cached.length===3 || stable.progress.won) break;
    }
    return cached;
  }
  return {
    ...base,
    decision: {
      ...base.decision!,
      maxAgeMs: 5000,
      recover(s, answers) {
        const answer = answers.control;
        if (answer?.type !== 'choice') return null;
        const choices = landings(s), selected = choices.find(l => l.id === answer.choice);
        if (!selected || (s.routeVisits?.[`${Math.round(selected.x)},${selected.y}`] ?? 0) < 2) return null;
        const alternative = choices.find(l => (s.routeVisits?.[`${Math.round(l.x)},${l.y}`] ?? 0) < 2) ?? choices.at(-1)!;
        if (alternative.id === selected.id) return null;
        return { answers: { ...answers, control: { ...answer, choice: alternative.id } }, reason: 'local-loop-recovery' };
      },
      contextKey: signature,
      schedule: { ready: s => s.routeQueue?.length ? false : s.routeMode ? s.actor.grounded : base.decisionReady?.(s), canInterrupt: s => !s.routeQueue?.length && s.actor.grounded, eventKey: s => String(s.deaths) },
      describe: s => ({ disposition: s.receipt?.disposition ?? 'accepted', reason: s.receipt?.reason, command: { controller: 'assisted-landings-v1', landing: s.selectedLanding ?? null, route: s.routeQueue ?? [] },
        expiresAt: s.frames + (s.remainingFrames ?? 0),
        ...(s.routeStatus?.startsWith('本地防循环') ? { reason: 'local-loop-recovery' } : {}) }),
      release: s => ({ ...base.decision!.release!(s), routeQueue: [], routeMode: true }) as AssistedState,
    },
    initialState: () => ({...base.initialState(), routeVisits:{}}),
    decisionReady: s => s.routeQueue?.length ? false : s.routeMode ? s.actor.grounded : base.decisionReady?.(s),
    observe(s, opts) {
      const obs = base.observe(s, {live:true}) as Record<string, unknown>;
      return {...obs, controller: 'assisted-landings-v1', routeStatus:s.routeStatus ?? '等待选择落脚点',
        ...(!opts?.live ? { landings:landings(s).map(({actions,...l})=>({...l,visits:s.routeVisits?.[`${Math.round(l.x)},${l.y}`] ?? 0})) } : {})};
    },
    questions(s) {
      const choices=landings(s);
      return {control:{type:'choice',label:'下一处落脚点',instructions:'Choose a landing from landings. Local physics executes the complete route including jumps and waits on solid ground. Prefer gaining the key, activating the switch, collecting all coins, then reaching the goal. All supplied routes are verified prefixes of a solution. Prefer progress and fewer revisits; a longer route reduces API waiting. Do not plan individual key presses.',criteria:choices.length ? Object.fromEntries(choices.map(l=>[l.id,`落点 (${Math.round(l.x)}, ${l.y})，${(l.frames/60).toFixed(1)}秒，新增金币 ${l.coins}，钥匙 ${l.key}，机关 ${l.switchOn}，通关 ${l.won}`])) : {wait:'No verified route available. Stay safe and retry planning.'}}};
    },
    act(s, answers) {
      const answer=answers.control;
      if(answer?.type==='choice' && (answer.choice.startsWith('landing-') || answer.choice==='wait')) {
        if(s.routeQueue?.length) return {...s,receipt:{disposition:'retained',reason:'route-in-progress'}};
        const choices=landings(s);
        let selected=choices.find(l=>l.id===answer.choice);
        if(!selected) return {...s,selectedLanding:undefined,remainingFrames:0,routeQueue:undefined,receipt:{disposition:answer.choice==='wait' ? 'accepted' : 'rejected',reason:answer.choice==='wait' ? 'no-verified-route-wait' : 'landing-unavailable'},routeMode:true,input:INPUTS.idle!,routeStatus:'局面已变化，重新规划'};
        const destination=`${Math.round(selected.x)},${selected.y}`;
        const repeats=(s.routeVisits?.[destination] ?? 0);
        if(repeats>=2) selected=choices.find(l=>(s.routeVisits?.[`${Math.round(l.x)},${l.y}`] ?? 0)<2) ?? choices.at(-1)!;
        const dest=`${Math.round(selected.x)},${selected.y}`;
        return {...s,receipt:{disposition:'accepted'},selectedLanding:selected.id,routeMode:true,routeQueue:selected.actions.map(a=>({...a})),remainingFrames:selected.frames,
          routeVisits:{...s.routeVisits,[dest]:(s.routeVisits?.[dest] ?? 0)+1},
          routeStatus:repeats>=2 ? '本地防循环：更换落脚点' : `前往落脚点 (${Math.round(selected.x)}, ${selected.y})`};
      }
      // Human controls and legacy deterministic test bots keep direct input semantics.
      return {...base.act(s,answers),routeQueue:undefined,routeMode:false,receipt:undefined} as AssistedState;
    },
    step(s) {
      const command=s.routeQueue?.[0];
      if(command) s.input={move:command.move,jump:command.jump};
      const deaths=s.deaths;
      const next=base.step(s) as AssistedState;
      if(next.deaths!==deaths){next.routeQueue=[];next.input=INPUTS.idle!;next.routeStatus='落水后重新规划';return next;}
      if(command) {
        command.frames--;
        if(command.frames===0) next.routeQueue!.shift();
        if(!next.routeQueue!.length){next.input=INPUTS.idle!;next.routeStatus='已落稳，等待模型选择';}
      }
      return next;
    },
  };
}
