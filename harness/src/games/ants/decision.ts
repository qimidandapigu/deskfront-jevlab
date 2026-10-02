import { DIRECTIONS, LEVELS, transform, type State } from './engine.js';
import type { Question } from '../../systemone/types.js';

/** Describe geometry and local force effects, without giving a route or choosing for the model. */
export function antDecision(state: State, ant: number) {
  const level = LEVELS[state.level - 1]!;
  const grip = transform(level.grips[ant]!, state.pose);
  const rx = grip.x - state.pose.x, ry = grip.y - state.pose.y;
  const names: Record<string, string> = { east: '右', west: '左', north: '上', south: '下', ne: '右上', nw: '左上', se: '右下', sw: '左下', stop: '松力' };
  const criteria = Object.fromEntries(Object.entries(DIRECTIONS).filter(([k]) => k !== 'stop').map(([key, f]) => {
    const torque = rx * f.y - ry * f.x;
    return [key, `向${names[key]}拉：产生${Math.abs(torque) < 1 ? '近乎零' : torque > 0 ? '顺时针' : '逆时针'}力矩（${torque.toFixed(1)}），并把物体向${names[key]}移动。`];
  }));
  criteria.stop = '暂时不出力。仅在你的拉力会阻碍队友正在进行的有效动作时选择；所有成员都停止不会产生任何进展。';
  return {
    observation: {
      mission: '六只蚂蚁共同把刚性食物搬入终点。你只控制自己，其他五只独立决策。主动贡献有效拉力，不要因为其他蚂蚁静止就等待它们。没有自动转向或自动寻路。',
      coordinates: '屏幕坐标：x 向右，y 向下。旋转角度为弧度，正角顺时针。',
      ant: ant + 1, myWorldPosition: grip, myLeverArm: { x: rx, y: ry },
      load: { center: state.pose, worldParts: level.shape.map(r => [
        { x: r.x, y: r.y }, { x: r.x + r.w, y: r.y }, { x: r.x + r.w, y: r.y + r.h }, { x: r.x, y: r.y + r.h },
      ].map(p => transform(p, state.pose))) },
      walls: level.walls, goal: level.goal,
      teammates: state.ants.map((a, i) => ({ ant: i + 1, position: transform(level.grips[i]!, state.pose), force: a.force ?? DIRECTIONS[a.action] })),
      allStopped: state.ants.every(a => a.action === 'stop'),
      collisionFeedback: { accumulatedBlockedSeconds: state.blocked, explanation: '碰壁时间增加表示拉力被墙挡住，不是接口失效。反复同向拉不能解决尺寸或角度不匹配，需要根据几何选择旋转或退让。' },
      elapsedSeconds: state.time,
    },
    questions: { force: { type: 'choice', instructions: '现在选择你这只蚂蚁最有助于完成搬运的拉力。根据物体、窄门、自己的世界位置与力矩方向，决定平移、转动或后退。平移时可同向拉，旋转时两端需要相反方向。不要把「等待其他人先动」当作计划。', criteria } } satisfies Record<string, Question>,
  };
}
