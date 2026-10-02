# Deskfront 1v1：只通过 Harness 接入

游戏仓库保持原样。`src/deskfront/duel.py` 调用现有 `scenario` 和 `demo_step`
指令，逐步布置、部署并开战，每一步等待 Godot 的真实回执。

大厅选择 Deskfront → **1v1 · 模型对游戏 AI**，后端选择 JEV。
`modelFaction` 选择 green 或 red，换边重赛。也可运行：

```powershell
npm run play -- deskfront --variant duel --backend jev --max-requests 100 --duration-ms 180000
```

绿色与红色各三名步兵，使用原版的步枪、冲锋枪和火箭筒；只有所选阵营经 Harness
请求模型，另一方用原版游戏 AI。蓝队和坦克按原版演示规则停放、不参战。
模型是逐兵战术选择，寻路、射击、换弹及紧急自保仍由原版引擎执行。

出生点和可配置掩体对称；原版固定小楼、反坦克炮等不能通过场景接口删除，仍保留。
这与此前已撤回的游戏改版场景不同，旧版 45.8 秒胜局不计入此次评测。
建议同一参数下反复换边，以真实 winner、调用错误、回退、拒绝回执衡量效果。

模型配置由 Harness 管理；适配器不读取游戏的 `.env`。
会话日志包含真实引擎快照、模型回答及回执。无 API Key 的验收使用 mock，不能当 JEV 实战。

```powershell
$env:DESKFRONT_LIVE_TEST='1'
$env:PYTHONUTF8='1'
node --import tsx --test test/deskfront-duel.test.ts
```

## Harness JEV 对原生 JEV

`opponent=native_jev` 使用游戏目录 `.env` 中的原生 TypeSafe 配置，运行未修改的
`LMController` 和 `JevClient`。另一个阵营通过 Quickplay SDK 请求 Harness 的 TypeSafe 后端。
双方各有独立调度器、每局预算、并发和日志，观察中仍保留全部真实单位信息。
Harness 侧状态视图只限制该控制器可以调度哪个阵营，不写回引擎，也不修改游戏代码。

换边各一局、双方固定原生模型版本、每方 100 次请求上限：

```powershell
node --import tsx src/deskfront/compare.ts
```

比较报告在 `output/deskfront-jev-comparison-*/report.json`，每局保留
`engine.jsonl`、`calls.sqlite3`、`native-calls.sqlite3` 和 `battle-result.json`。
原生 API Key 只由原生客户端读取，不经 stdio 发送给游戏进程。
当前 Harness 复用游戏的观察、候选动作和调度器，因此这是接入链路的对比，
不应描述成两套独立战术策略；两局结果也不是稳定胜率估计。
