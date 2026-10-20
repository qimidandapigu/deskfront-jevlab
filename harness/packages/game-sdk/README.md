# Game SDK（接入契约原型）

与 Harness 配套的独立 TypeScript SDK。协议为 `quickplay-bridge/v1`，提供读取、查询、控制、意图与表达接口；不包含模型调用或游戏逻辑。零运行依赖，使用标准 `fetch`；Node.js 20+。

```powershell
cd C:/game/quickplay-harness/packages/game-sdk
npm install
npm test
npm run example
```

源码导出：`GameClient`、`HttpTransport`、`GameTransport`、`BridgeError` 和公共数据类型。`npm run build` 生成 `dist` JavaScript 与类型声明，消费方不需要 TypeScript。当前包保留 `private: true`；未完成许可证审核和公开发布。

```typescript
import { GameClient } from '@quickplay/game-sdk';

const game = GameClient.http('http://127.0.0.1:8769', { timeoutMs: 3000 });
const info = await game.getInfo();
const observation = await game.observe();
// 根据 info 的能力目录决定查询/动作；不能把不存在的能力当作成功。
```

| 方法 | HTTP |
| --- | --- |
| getInfo / observe / getMap | GET `/v1/info` / `/v1/state` / `/v1/map` |
| query | POST `/v1/query` |
| listEvents / events | GET `/v1/events?cursor=…`（events 显式启动增量轮询） |
| acquireControl / getControl | POST `/v1/control/acquire` / GET `/v1/control/{leaseId}` |
| renewControl / releaseControl | POST `/v1/control/renew` / `/v1/control/release` |
| submitIntent / cancelIntent | POST `/v1/intents` / `/v1/intents/cancel` |
| getReceipt / waitForReceipt | GET `/v1/receipts/{id}` |
| setExpressions / playCommentary / showDanmaku | POST `/v1/presentation/expressions` / `commentary` / `danmaku` |
| getPresentationReceipt | GET `/v1/presentation/receipts/{id}` |

成功返回对应类型的 JSON；失败使用非 2xx 与 `{code,message}`。典型错误：`unsupported_capability`、`stale_run`、`stale_control_epoch`、`invalid_actor`、`stale_candidate`、`receipt_not_found`、`queue_full`。读取仍需遵守游戏端可见性与权限，不允许把“未提供”填成“没有危险”。

SDK 不隐式申请控制，不自动把 pending 升为 active，不补写任务版本，不自动重试 POST。网络超时后结果未知，使用同一命令 ID 查询回执；重提同一 ID 的幂等处理由游戏适配服务负责。`waitForReceipt` 等待终态，超时不取消游戏动作。`events` 按页返回，保留 cursor 与 gap；调用方在 gap 后重新读取观察并重建事件上下文。

`examples/reference-service.mjs` 是可运行的简化协议参考环境，只有一个点沿一维移动，可验证内置算法、接管与回执。它不是 Deskfront，不调用 AI，不生成实际表情、音频或弹幕。没有能力的接口返回明确错误。`local-demo.mjs` 演示申请控制、提交移动、观察终态、交还控制。

此 SDK 尚不能直接连接 Deskfront 旧 `/api/*` 服务。真实游戏适配与发行包迁移见项目 `docs/open-source/release-bridge-design.md`；不能把示例通过视作 Godot 游戏验收。

Deskfront Windows 发行包现在提供独立 `/v1/*` 服务，可直接连接本 SDK。启动游戏后，在项目根目录运行 `npm run deskfront:inspect`，只读取连接、能力、地图和状态，不申请控制或调用模型。多局并存时用 `-- --connection <本局 connection.json>` 指定实例。完整现有 Harness 仍需迁移状态、个人行动和表达接口，不能把 SDK 连接成功当成全部 AI 流程已接入。详见 `docs/open-source/deskfront-harness-attach.md`。
