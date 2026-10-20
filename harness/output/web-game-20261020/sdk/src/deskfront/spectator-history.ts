import type { BattleFrame, Fact } from './commentary.js';
import { spectatorEquipmentFacts } from './spectator-story.js';
import { publicMortars, publicSpectatorText } from './spectator-observation.js';

type Row = Record<string, any>;
const names: Record<string, string> = { green: '绿队', red: '红队', blue: '蓝队' };
const infantry = (u: Row) => u.kind !== 'tank' && u.tank !== true;
const alive = (u: Row) => u.hp > 0 && u.combat_ready !== false;
export interface HistoricalFact extends Fact { time: number; stage?: number; equipmentId?: string }

/** Bounded engine evidence across stages. Observed independently of speech scheduling. */
export class SpectatorHistory {
  private previous?: BattleFrame;
  private movement?: BattleFrame;
  private sequence = 0;
  private events: HistoricalFact[] = [];
  private stages = new Map<number, HistoricalFact>();
  private spoken: { time: number; text: string }[] = [];

  observe(frame: BattleFrame): HistoricalFact[] {
    const w = frame.world;
    if (typeof w.time !== 'number') return [];
    if (this.previous && (this.previous.world.run_id !== w.run_id || w.time < this.previous.world.time)) {
      this.previous = undefined; this.movement = undefined; this.events = []; this.stages.clear(); this.spoken = []; this.sequence = 0;
    }
    if (this.previous?.world.time === w.time) return [];
    const added: HistoricalFact[] = [], old = this.previous?.world;
    const stage = w.world_growth?.mission?.index;
    const add = (text: string, urgent = false, routine = false, equipmentId?: string) => {
      const event = { id: `h${++this.sequence}`, time: w.time, stage, text, urgent, routine, ...(equipmentId ? { equipmentId } : {}) };
      added.push(event); this.events.push(event);
    };
    const fresh = !old || old.world_growth?.revision !== w.world_growth?.revision;
    if (fresh && stage) add(`第${stage}关已经开始。`);
    if (!fresh && old) {
      const previous = new Map<string, Row>((old.units ?? []).map((u: Row) => [u.id, u]));
      for (const [team, name] of Object.entries(names)) {
        const rows: Row[] = (w.units ?? []).filter((u: Row) => u.faction === team && infantry(u));
        const losses = rows.filter(u => u.hp <= 0 && (previous.get(u.id)?.hp ?? 0) > 0).length;
        if (losses) add(`${name}新增${losses}名士兵阵亡，当前${rows.filter(alive).length}名士兵仍在战斗。`, true);
      }
      if (w.world_growth?.mission?.status === 'completed' && old.world_growth?.mission?.status !== 'completed') add(`第${stage ?? '当前'}关任务已经完成。`, true);
      if (w.world_growth?.mission?.status === 'failed' && old.world_growth?.mission?.status !== 'failed') add('绿队本段推进失败。', true);
    }
    const equipment = spectatorEquipmentFacts(frame, this.previous);
    const priorMortars = new Map(publicMortars(!fresh ? old?.world_growth : undefined).map(gun => [gun.id, gun]));
    for (const fact of equipment.facts) {
      if (fact.id.startsWith('equipment-tank-destroyed-') || fact.id.startsWith('equipment-mortar-captured-')
        || fact.id.startsWith('equipment-satchel-') || fact.id.startsWith('equipment-mortar-shot-')
        || fact.id.startsWith('equipment-mortar-crew-')
        || (fresh && fact.id.startsWith('equipment-tank-')) || (fresh && fact.id.startsWith('equipment-mortar-owner-'))
        || (fact.id.startsWith('equipment-mortar-unmanned-') && priorMortars.get(fact.equipmentId ?? '')?.capturable !== true)) add(fact.text, !!fact.urgent, !!fact.routine, fact.equipmentId);
    }
    if (!fresh && old) {
      const previous = new Map<string, Row>((old.units ?? []).map((u: Row) => [u.id, u]));
      for (const u of (w.units ?? [])) {
        const p = previous.get(u.id);
        if (!infantry(u) && alive(u) && p && typeof u.last_shot_at === 'number' && u.last_shot_at > (p.last_shot_at ?? -1))
          add(`${names[u.faction] ?? '未知阵营'}坦克开火。`, false, (p.last_shot_at ?? -1) >= 0);
      }
    }
    // Coarse team movement is measured over several seconds, not animation/path flags.
    if (!this.movement || fresh) this.movement = this.compact(frame);
    else if (w.time - this.movement.world.time >= 5) {
      const anchor = new Map<string, Row>(this.movement.world.units.map((u: Row) => [u.id, u]));
      for (const [team, name] of Object.entries(names)) {
        const moved = (w.units ?? []).filter((u: Row) => {
          const p = anchor.get(u.id);
          return u.faction === team && infantry(u) && alive(u) && !!p && p.hp > 0
            && Array.isArray(u.position) && Array.isArray(p.position)
            && Math.hypot(u.position[0] - p.position[0], u.position[1] - p.position[1]) >= .18;
        });
        if (moved.length >= 2) {
          const goal = team === 'green' ? w.world_growth?.mission?.target : w.world_growth?.mission?.entry;
          const toward = Array.isArray(goal) ? moved.filter((u: Row) => {
            const p = anchor.get(u.id)!;
            return Math.hypot(p.position[0] - goal[0], p.position[1] - goal[1])
              - Math.hypot(u.position[0] - goal[0], u.position[1] - goal[1]) >= .12;
          }).length : 0;
          const away = Array.isArray(goal) ? moved.filter((u: Row) => {
            const p = anchor.get(u.id)!;
            return Math.hypot(u.position[0] - goal[0], u.position[1] - goal[1])
              - Math.hypot(p.position[0] - goal[0], p.position[1] - goal[1]) >= .12;
          }).length : 0;
          if (toward >= 2 && toward > moved.length / 2) add(`${name}有${toward}名士兵朝本关交战目标推进。`);
          else if (away >= 2 && away > moved.length / 2) add(`${name}有${away}名士兵从本关交战目标方向后撤。`);
          else add(`${name}有${moved.length}名士兵换了位置。`, false, true);
        }
      }
      this.movement = this.compact(frame);
    }
    for (const result of (w.world_growth?.mission_results ?? []).slice(-12)) {
      if (typeof result.index !== 'number' || this.stages.has(result.index)) continue;
      const start = result.green_start?.alive, end = result.green_end?.alive;
      const health = typeof result.green_end?.hp_total === 'number' && typeof result.green_start?.hp_total === 'number'
        ? `入场总血量${result.green_start.hp_total}，结束总血量${result.green_end.hp_total}。` : '';
      const fact: HistoricalFact = { id: `stage-${result.index}`, time: result.ended ?? w.time, stage: result.index,
        text: `第${result.index}关结果：${result.status === 'completed' ? '任务完成' : result.status}，用时${result.duration_seconds ?? '未知'}秒；绿队入场${start ?? '未知'}人，结束时存活${end ?? '未知'}人。${health}` };
      this.stages.set(result.index, fact);
    }
    this.stages = new Map([...this.stages].slice(-12));
    this.events = this.events.slice(-96);
    this.previous = this.compact(frame);
    return added;
  }

  markSpoken(time: number, text: string) { if (publicSpectatorText(text)) this.spoken = [...this.spoken, { time, text }].slice(-16); }
  snapshot(time: number) {
    return { completed_stages: [...this.stages.values()],
      timeline: this.events.filter(e => e.urgent || time - e.time <= 60).slice(-24),
      spoken_commentary: [...this.spoken],
      evidence_limits: '历史是已观察到的真实引擎事实；已播解说不是新的战况证据。意图与移动不等于战术成功，发射不等于命中。' };
  }
  private compact(frame: BattleFrame): BattleFrame {
    const w = frame.world;
    return { kind: frame.kind, status: frame.status, world: structuredClone({
      run_id: w.run_id, time: w.time,
      units: (w.units ?? []).map((u: Row) => ({ id: u.id, faction: u.faction, kind: u.kind, tank: u.tank, hp: u.hp,
        combat_ready: u.combat_ready, position: u.position, last_shot_at: u.last_shot_at,
        combat: { satchel: ['launched', 'detonated'].includes(u.combat?.satchel?.status) ? { status: u.combat.satchel.status, time: u.combat.satchel.time } : undefined } })),
      world_growth: { revision: w.world_growth?.revision, mission: { index: w.world_growth?.mission?.index, status: w.world_growth?.mission?.status, entry: w.world_growth?.mission?.entry, target: w.world_growth?.mission?.target }, mortar_supports: publicMortars(w.world_growth) },
    }) };
  }
}
