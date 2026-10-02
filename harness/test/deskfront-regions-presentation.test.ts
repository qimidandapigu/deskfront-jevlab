import assert from 'node:assert/strict';
import { deskfrontPage } from '../src/deskfront/page.js';
import test from 'node:test';
import vm from 'node:vm';


class Element {
  parentElement = { open: false, addEventListener() {} };
  textContent = '';
  style: Record<string, string> = {};
  children: Element[] = [];
  append(...children: Element[]) { this.children.push(...children); }
  replaceChildren(...children: Element[]) { this.children = children; }
}

function page() {
  const elements = new Map<string, Element>();
  const element = (id: string) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id)!;
  };
  const draws: { op: string; args: unknown[] }[] = [];
  const canvasContext = new Proxy<Record<string, unknown>>({}, {
    get(target, name: string) {
      if (name in target) return target[name];
      return (...args: unknown[]) => draws.push({ op: name, args });
    },
    set(target, name: string, value) { target[name] = value; return true; },
  });
  Object.assign(element('map'), {
    getBoundingClientRect: () => ({ width: 600, height: 400 }),
    getContext: () => canvasContext,
  });
  const context = vm.createContext({
    document: { getElementById: element, createElement: () => new Element(), addEventListener() {} },
    location: { search: '' }, URLSearchParams, devicePixelRatio: 1,
    window: { addEventListener() {} }, setTimeout: () => 0, clearTimeout() {},
    canvasContext,
  });
  const script = deskfrontPage().match(/<script>([\s\S]*?)<\/script>/)![1]!;
  new vm.Script(script).runInContext(context);
  return { context, draws, element };
}

const squad = {
  strategic_regions: { A: { center: [1, 1] }, B: { center: [1, 3] }, C: { center: [3, 3] } },
  plan: { tasks: {
    'green-1': { region_path: ['A', 'B', 'C'], region_id: 'C', region_cursor: 1 },
    'green-2': { region_path: ['A', 'B'], region_id: 'B', region_cursor: 1 },
  } },
  units: { 'green-1': { region_navigation: { status: 'ready', next_region: 'B', index: 2 } } },
  route_choices: { left: { points: [[0, 0], [0, 8]] } },
};

test('map draws actual region assignments with unit colors and target/next markers', () => {
  const p = page(); p.context.squad = squad;
  assert.equal(vm.runInContext('drawRegionRoutes(canvasContext,p=>p,squad)', p.context), true);
  assert.match(p.element('map-legend').textContent, /已下达区域序列/);
  assert.match(p.element('map-legend').textContent, /不是实际寻路/);
  const labels = p.element('route-legend').children;
  assert.equal(labels.length, 2);
  assert.match(labels[0]!.textContent, /green-1 · A → B → C/);
  assert.notEqual(labels[0]!.style.color, labels[1]!.style.color);
  assert.ok(p.draws.some(x => x.op === 'strokeRect'));
  assert.ok(p.draws.some(x => x.op === 'arc' && x.args[2] === 10));
});

test('region cards show authoritative cursor, next region, and blocker', () => {
  const p = page(); p.context.parent = new Element();
  p.context.task = squad.plan.tasks['green-1'];
  p.context.row = { region_navigation: { status: 'blocked', next_region: 'B', index: 2, reason: 'corridor_reserved_or_disconnected' } };
  vm.runInContext("renderRegionTask(parent,task,row,'green-1')", p.context);
  const texts = (p.context.parent as Element).children.map(x => x.textContent).join('\n');
  assert.match(texts, /区域序列：A → B → C/);
  assert.match(texts, /目标区：C · 下一域：B · 已进入 2\/3 区/);
  assert.match(texts, /区域推进受阻 · 通路被预约或已断开/);
});

test('missing area coordinates do not draw an invented connection across that area', () => {
  const p = page();
  p.context.squad = { ...squad, strategic_regions: { A: squad.strategic_regions.A, C: squad.strategic_regions.C } };
  assert.equal(vm.runInContext('drawRegionRoutes(canvasContext,p=>p,squad)', p.context), true);
  assert.equal(p.draws.filter(x => x.op === 'lineTo').length, 0);
  assert.match(p.element('route-legend').children[0]!.textContent, /A → B → C/);
});

test('old optional lanes only render when there are no issued region paths', () => {
  const p = page(); p.context.squad = squad;
  p.context.world = { bounds: [0, 0, 10, 10], objective: { position: [5, 5], radius: .2 }, units: [], covers: [] };
  vm.runInContext('latest={payload:{game:{lm:{squad}}}};draw(world)', p.context);
  assert.equal(p.draws.some(x => x.op === 'fillText' && String(x.args[0]).startsWith('可选 ')), false);
  p.context.squad = { route_choices: squad.route_choices, plan: { tasks: {} } };
  p.draws.length = 0;
  vm.runInContext('latest={payload:{game:{lm:{squad}}}};draw(world)', p.context);
  assert.ok(p.draws.some(x => x.op === 'fillText' && x.args[0] === '可选 左路'));
  assert.match(p.element('map-legend').textContent, /仅供参考，未表示已下达/);
});


test('poll skips hidden and completed sessions but permits a new session', async () => {
  const p = page();
  vm.runInContext("var calls=0; api=async()=>{calls++;throw Error('test stop')};id='old';latestId='old';latest={status:'done'}",p.context);
  await vm.runInContext('poll()',p.context);
  assert.equal(vm.runInContext('calls',p.context),0);
  vm.runInContext("id='new';document.hidden=true",p.context);
  await vm.runInContext('poll()',p.context);
  assert.equal(vm.runInContext('calls',p.context),0);
  vm.runInContext('document.hidden=false',p.context);
  await vm.runInContext('poll()',p.context);
  assert.equal(vm.runInContext('calls',p.context),1);
});

test('finished commentary shows ended even if the last engine frame was paused', async () => {
  const p = page();
  vm.runInContext("id='finished';latestId=id;commentarySession=id;commentaryEnabled=true;latest={kind:'ai',status:'done',latest:{observation:{paused:true}}}", p.context);
  await vm.runInContext('commentaryTick()', p.context);
  assert.equal(p.element('commentary-state').textContent, '本局已结束');
});
