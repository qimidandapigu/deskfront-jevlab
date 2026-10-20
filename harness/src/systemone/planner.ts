/** 规划模型占位：负责把长期目标拆解成执行模型的决策输入（SystemOne 的 state/questions）。
 *  目前未接入任何后端。执行模型见 index.ts 的 createSystemOne（mock | deepseek | jev 可切换）。 */
export function createPlanner(): never {
  throw new Error('规划模型尚未接入（占位）');
}
