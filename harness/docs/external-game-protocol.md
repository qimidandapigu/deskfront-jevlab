# Quickplay Game Protocol v1

稳定标识：`quickplay-game/v1`。传输：子进程 stdio，每行一个 UTF-8 JSON 对象。stdout 仅发协议；日志写 stderr。语言与引擎不受限制。SDK 和接入步骤见 [统一 Harness](unified-harness.md)。

## 握手

Harness 首先发送：

```json
{"type":"start","protocol":"quickplay-game/v1","sessionId":"unique-id","config":{"backend":"mock","mode":"ai","gameOptions":{},"runtime":{"maxRequests":100}}}
```

游戏回复：

```json
{"type":"ready","protocol":"quickplay-game/v1"}
```

ready 表示协议已就绪，不表示引擎已加载或战斗开始。真实状态必须来自后续 state。版本不匹配、重复握手、握手前业务消息会结束会话并记录错误。默认握手期限 10 秒，可由清单调整。

## 游戏 → Harness

| type | 必需字段 | 含义 |
|---|---|---|
| `state` | `observation` | 引擎真实观测，结构由游戏定义；可附 `payload` |
| `request` | `id`, `state`, `questions` | 一次模型请求；id 在会话内唯一 |
| `record` | `record` 对象 | 执行回执、效果、调试或游戏事件 |
| `end` | `outcome` 字符串 | 游戏结束；可附 `error` 字符串 |

`questions` 为名称到问题定义的映射：choice 使用 `criteria` 字符串映射；score 使用 `levels` 字符串映射；noul 表示 0–1 概率。各题包含 `instructions` 字符串。对应类型位于 `src/systemone/types.ts`，线协议类型位于 `src/external/protocol.ts`。

## Harness → 游戏

| type | 字段 | 含义 |
|---|---|---|
| `response` | `id`, `response` 或 `error` | 对应请求的答案/错误，允许乱序返回 |
| `input` | `body` | 玩家输入 |
| `action` | `body` | 游戏级操作 |
| `stop` | 无 | 停止引擎、取消等待、释放资源并退出 |

`response` 保留公共 `ModelResponse` 的 answers、usage、usageComplete、requestedModel、resolvedModel；缺失值不代表零成本或已知模型版本。模型请求失败时游戏可以按自己的规则回退，但要明确记录回退。

默认每局 100 次模型请求，最多 16 个并发等待、10,000 个请求 ID。请求预算耗尽后返回错误，不会替游戏捏造动作或胜负。每行上限 2 MB。停止会立即取消 Harness 内的模型等待；游戏应停止其拥有的子进程，4 秒未退出时 Harness 强制结束托管进程。进程未发送 end 就退出，记为错误。

## 执行证据

Harness 收到模型回答后只记录 `pending`。游戏真正执行后再发送关联请求 ID 的回执。例如：

```json
{
  "type":"record",
  "record":{
    "execution":{
      "schema":"quickplay-execution-v1",
      "id":"the-request-id",
      "status":"applied",
      "rawAnswers":{},
      "executedAnswers":{},
      "action":{"command":"advance","disposition":"accepted"}
    }
  }
}
```

示意里的空对象应换成真实答案。只有引擎确认接受后才使用 applied；未确认时保持 pending，拒绝时使用 rejected。applied 不代表动作达成目标；后续效果另行记录。若游戏会过滤过时答案、改写危险动作或回退，要同时保留原始回答、实际执行输入和原因。

公共层不猜测各游戏的单位坐标、帧时钟、合法路径或战术含义；这些由游戏适配器根据真实引擎状态提供。
