# 拟人小队持续执行

本实现用于 Harness 的桌面 1v1 场景。DeepSeek 规划任务和目标区域，JEV 选择小队意图，Godot 持续导航、维护站位与即时自保，Harness 合并引擎事件并激活重新判断。普通入口通过 `config` 命令 `key=human_squad,value=1` 或 `HARNESS_HUMAN_SQUAD=1` 开启；默认旧模式保留。

## 参考与实现边界

参考 Chris Jurney《Company of Heroes Squad Formations Explained》中虚拟队长、未来锚点跟随、行进队形和到达后独立预约站位的思路；实现使用本项目原有 Godot 导航和碰撞系统，未复制《英雄连》源码，也不宣称重现论文全部机制。

- [章节 PDF](https://forum.arongranberg.com/uploads/short-url/rWod3K2KhNWcOEdjewnsLXQKU6A.pdf)
- [GDC 小队战术分享官方摘要](https://www.gdcvault.com/play/1015665/Believable-Tactics-for-Squad)

主要实现是 `scripts/human_squads.gd`。`advance`、`bound` 和 `flank` 沿批准目标行进；具体目标的侧翼关系由规划区域决定，当前引擎没有额外的全局包抄搜索器。`cover`/`hold` 可以暂停并就近保护。`regroup` 在当前小队中心附近分散重整，保留长期目标。

## 持续执行契约

```json
{
  "action":"squad_order", "source":"lm", "faction":"green",
  "unit_ids":["green-1","green-2","green-3"],
  "squad_id":"green-squad", "order_id":"green:plan1:order2",
  "intent":"advance", "position":[0.3,2.1], "radius":0.1,
  "run_id":"current-run", "seen_tick":150, "control_epoch":0
}
```

`intent` 支持 `advance/cover/bound/flank/hold/regroup`。中心必须在原生导航上可行走，半径 `.06–2`。LM 多成员权限只为此动作开放；普通 LM 动作仍限单兵。服务端和引擎都保留阵营、存活、局次、控制权与观测时效校验。每个士兵只能属于一个意图所有者。相同意图和目标的复核只更新 order_id，不清空虚拟队长进度或重新洗牌站位。

执行器每 0.2 游戏秒检查协作，单兵和物理仍逐帧运行。成员按稳定 ID 顺序取队形位置；狭窄处变纵列，开阔地展开；虚拟锚点等待落后成员。到达站位检查跨小队目标、已有掩体预约、真实占位和导航可达性。

交替推进要求实际可射目标、弹药、未换弹、低压制和近期射击。没有真实掩护时不能把“已安排掩护角色”当成火力。为了避免全队在轻武器射程外永久互等，允许一名健康低压成员做最多 0.12 米的可中止短移来建立射位；压制升至 .35 时立即停止。五秒仍无法建立掩护会发出 `route_failed`，交给 Harness 重新判断。

## 感知、事件和姿态

`snapshot.squad_behavior` 提供 `enabled/squads/perception/event_seq/events`。`perception[faction].contacts` 仅包含视距和遮挡允许的目视目标，以及至多 6 秒的旧观测；隐藏后位置与 HP 保持最后观测，不跟随真实单位。视觉闪烁 1.5 秒内重新出现不会反复发新接敌事件。观众使用的原始全场快照仍存在；模型应只使用该感知视图。

事件包括 `contact_acquired/cover_invalidated/ally_down/route_failed/support_lost/arrived/order_started/regrouped`。正常离开完整掩体不会被当成掩体摧毁。小队在交替推进后恢复行军时重新建立当前位置锚点，避免返回旧位置。

拟人模式保留受压移动中的卧倒匍匐，并取消旗点告急强制关闭自保。`combat_fx.gd` 在每次发射时按武器类别采样角度圆盘散布，最终命中仍由逐帧扫掠线段与真实姿态 hit box/掩体碰撞决定。炮弹和火箭使用不同基础散布角；爆炸沿用已有距离和遮挡规则，没有把卧倒改成统一伤害减免。

## 验证

- `tests/human_squad_contract.gd`：24 项原生检查，涵盖权限、稳定队形、单所有者、感知记忆、受压匍匐、无掩护反馈、局部重整、推进恢复，以及实际 hit box 散布统计。
- 4000 个相同种子的正面步枪采样：站立碰撞 3667，卧倒碰撞 2865。这只证明该固定几何条件下较低暴露，不能代表所有距离、角度或爆炸收益。
- `tests/semantic_probe.tscn`：113 项既有检查通过。
- `tests/test_human_squads.py`：3 项接口检查通过；`test_lm.py`：15 项既有 LM 检查通过。

全量 Python 测试另有 Windows SQLite 临时数据库未关闭的清理错误；不能把定向测试成功报告成全部 Python 测试通过。真实模型行为和视觉观感由 Harness 的 1v1 实机记录另行验收。
