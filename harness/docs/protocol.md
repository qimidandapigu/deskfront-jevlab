# JGP — Jev Game Protocol, v1

新外部游戏请使用 [Quickplay 公共游戏协议](external-game-protocol.md) 和 [SDK 接入流程](unified-harness.md)。下文 JGP v1 是已有玩具兵/stdio 接入的兼容协议，也由公共会话服务托管。

JGP 是游戏与 jev harness 之间的协议：游戏上报结构化战场状态
（**WorldState**），harness 用 TypeSafe Jev 模型（System One，毫秒级类型化
应答）做决策，回发逐实体的 **Action**。协议即契约 —— 游戏侧接入方按本文档
实现即可。

Version: **v1**（每个载荷带 `protocolVersion: "v1"`）。

参考实现：`src/jgp/protocol.ts`（类型 + runtime guards）、
`src/jgp/stdio.ts`（stdio 传输）、`src/jgp/engine.ts`（决策引擎）。

本协议只管**外部游戏**。内置玩具游戏（注册进 registry、进 viewer 观测站的
插件）走另一套体系 JEP，见 [docs/plugin-api.md](plugin-api.md)。

## GameAdapter

一个游戏接入实现三个方法：

```ts
interface GameAdapter {
  capabilities(): Capabilities | Promise<Capabilities>;  // 握手
  getState(): WorldState | Promise<WorldState>;          // 每 tick 拉快照
  execute(actions: Action[], entities?: EntityAnnotation[]): void | Promise<void>;      // 接收决策；entities 为 harness 回写（可选）
}
```

三种接法：

1. **stdio 子进程（主传输，推荐）** — harness spawn 游戏进程，
   `createStdioAdapter(command)` 把它包装成 GameAdapter（`src/jgp/stdio.ts`）。
2. **进程内直接调用** — 游戏在本进程内时，把 adapter 对象直接传给
   `createEngine({ adapter, ... })`（demo 狼群就是这么接的）。
3. **WebSocket（将来可选）** — 见文末。

## stdio 传输（主传输）

harness 父进程 `spawn` 游戏子进程：

- 协议帧走子进程 **stdout**：每行一个 JSON 对象（NDJSON）。
- 决策走子进程 **stdin**：同样每行一个 JSON 对象。
- **stdout 只走协议**；日志、调试输出一律写 stderr（harness 原样透传）。
- 每条消息写完必须 **flush**（行缓冲不够时要显式 flush）。

消息类型只有五种。

游戏 → harness：

| 消息 | 内容 |
|---|---|
| `hello` | `{ "type": "hello", "capabilities": Capabilities }` — 必须是第一条消息 |
| `state` | `{ "type": "state", "state": WorldState }` — 按游戏 tick 频率推送 |

harness → 游戏：

| 消息 | 内容 |
|---|---|
| `hello_ack` | `{ "type": "hello_ack", "protocolVersion": "v1" }` |
| `actions` | `{ "type": "actions", "tick": 1234, "actions": Action[], "entities": EntityAnnotation[]? }` — 每处理完一帧 state 后发送；`tick` 为被处理那帧 state 的 tick；`entities` 可选，携带 harness 回写 |
| `error` | `{ "type": "error", "message": "..." }` — 载荷非法；连接保持 |

harness 对每条入站消息做 runtime guard 校验（`isGameMessage`）；非法消息
回 `error` 帧并丢弃。游戏侧可用 `isHarnessMessage` 校验 harness 回包。

回路：`hello → hello_ack → (state → actions)* → 游戏退出`。

## Schemas

坐标用游戏自己的 2D 网格单位，原点在左上。

### Capabilities（hello）

```jsonc
{
  "protocolVersion": "v1",
  "game": "my-game",
  "tickRateHz": 20,
  "maxActionsPerTick": 64,
  "features": ["grid", "hp"]        // 自由形式的能力标记
}
```

### WorldState（game → harness）

```jsonc
{
  "protocolVersion": "v1",
  "tick": 1234,
  "timeMs": 61700,
  "bounds": { "w": 40, "h": 20 },
  "entities": [
    {
      "id": "player", "kind": "player", "faction": "player",
      "pos": { "x": 20, "y": 10 }, "vel": { "x": 1, "y": 0 },
      "hp": 80, "maxHp": 100,
      // 以下为 harness 的输出字段（游戏上报时无需包含；游戏可忽略）：
      // 进程内接法由 harness 直接回写到实体上；stdio 接法经 actions 帧的 entities 字段下发
      "aware": true,                 // 该敌人是否已注意到玩家
      "morale": 0.7,                 // 0..1 士气
      "swarmOrder": { "type": "focus_fire", "targetId": "player", "issuedAtTick": 1200 }
    }
  ],
  "events": [                        // 自上一帧快照以来
    { "tick": 1233, "type": "damage", "entityId": "wolf-7", "message": "wolf-7 took 5 dmg" }
  ]
}
```

### Action（harness → game）

```jsonc
{
  "entityId": "wolf-7",
  "type": "move",                    // move | attack | flee | hold | patrol
  "dir": { "x": 0.7, "y": -0.7 },    // move/flee/patrol 用
  "targetId": "player",              // attack/move 用
  "speed": 1.0                       // 0..1 速度倍率
}
```

### EntityAnnotation（actions 帧可选字段，harness → game）

```jsonc
[
  {
    "id": "wolf-7",
    "aware": true,
    "morale": 0.7,
    "swarmOrder": { "type": "focus_fire", "targetId": "player", "issuedAtTick": 1200 }
  }
]
```

## 接入示例

### JavaScript / TypeScript（Node 20+）

```js
// game.js — 最小 JGP 游戏：stdout 只写协议行，日志走 stderr
const readline = require("node:readline");

function send(msg) { process.stdout.write(JSON.stringify(msg) + "\n"); }

const state = makeInitialState(); // { protocolVersion: "v1", tick, ... }
send({ type: "hello", capabilities: {
  protocolVersion: "v1", game: "my-game", tickRateHz: 20,
  maxActionsPerTick: 64, features: ["grid"],
}});

const lines = readline.createInterface({ input: process.stdin });
lines.on("line", (line) => {
  const msg = JSON.parse(line);           // hello_ack | actions | error
  if (msg.type === "actions") applyActions(msg.actions);
  if (msg.type === "error") console.error("harness:", msg.message);
});

setInterval(() => {                       // 按 tickRateHz 推 state
  stepWorld(state);
  send({ type: "state", state });
}, 50);
```

### Python（3.10+）

```python
import json, sys, threading

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()                      # 必须 flush

state = make_initial_state()                # {"protocolVersion": "v1", "tick": 0, ...}
send({"type": "hello", "capabilities": {
    "protocolVersion": "v1", "game": "my-game", "tickRateHz": 20,
    "maxActionsPerTick": 64, "features": ["grid"],
}})

def read_actions():
    for line in sys.stdin:                  # hello_ack | actions | error
        msg = json.loads(line)
        if msg["type"] == "actions":
            apply_actions(msg["actions"])

threading.Thread(target=read_actions, daemon=True).start()
while True:                                 # 按 tickRateHz 推 state
    step_world(state)
    send({"type": "state", "state": state})
```

两个例子都依赖你自己实现 `makeInitialState` / `applyActions` / `stepWorld`
等游戏逻辑；协议部分只有收发 JSON 行。日志请用 `console.error` /
`print(..., file=sys.stderr)`。

## WebSocket 传输（将来可选）

v1 不随带 WS 服务端实现，但协议消息形状与传输无关：把上面的 NDJSON 行换
成"每帧一个 JSON 文本消息"即可（游戏作 WS client，harness 作 server；
握手与 state/actions 流向完全一致）。需要时可按 `src/jgp/stdio.ts` 的
模式自行实现一个 WS mount。

## 接入注意事项

- 需要 harness 驱动的实体必须 `faction: "enemy"`；`faction: "player"`
  的实体有且仅应有一个。
- harness 会丢弃形状非法或超出 `maxActionsPerTick` 的 action
  （记决策日志，reason: `invalid` / `over_limit`）。
- `hp <= 0` 的实体视为死亡，不会收到 action。
- 敌人身上的 `aware`、`morale`、`swarmOrder` 是 harness 的输出（进程内接法
  直接回写到实体；stdio 接法通过 `actions` 帧的 `entities` 字段下发），游戏可以忽略。


### 公共后端和执行审计（2026-09-20）

JGP 的真实 SystemOne 桥接使用主项目的请求超时、取消与完整答案校验；dispose 会取消在途等待。
日志新增 quickplay-execution-v1 投影。发出的 Action 保留在 proposedAction，状态为 pending；
外部游戏尚无执行回执时不宣称 applied。原有 JGP 节流、群组和 Boids 回退规则不变。
