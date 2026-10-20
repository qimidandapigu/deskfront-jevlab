# 当前完整 Web 运行版（2026-10-20）

本目录带有真正的 Godot Web 游戏：`output/web-releases/deskfront-20261020/game.wasm`、`game.pck`、`game.js` 及资源。也包含当前 Harness、看板、回放和关卡生成运行组件。**不用重新导出 Godot，不用安装 Godot 编辑器，不运行独立 EXE。**

Node.js、Python、npm 依赖和真实模型密钥不进仓库，由使用者自行安装或配置。

## 启动

1. 安装 Node.js 22.19+（推荐24 LTS）和 **Python 3.13**。宿主和关卡组件采用 CPython 3.13 字节码，因此不能换成3.12/3.14。浏览器需支持WebGL2。
2. 在本目录执行 `npm ci`。
3. 将 `config.local.example.json` 复制为 `config.local.json`，填写自己的密钥。JEV 使用 TypeSafe；DeepSeek 和 analyst 使用各自配置的服务与模型，可以共用同一枚 DeepSeek 密钥。配置模板中的 provider/model 是可编辑项，须与自己的账号权限匹配。
4. `npm run web:check` 检查游戏文件、Python与宿主/关卡运行模块，不调用模型。
5. `npm run web`，打开终端输出的 `http://127.0.0.1:50205/?view=beginner`。选队伍、开始游戏后才会请求模型，并产生相应服务费用。端口被占用时可设置 `VIEWER_PORT=0` 使用空闲端口。

PowerShell示例：

```powershell
cd harness
npm ci
Copy-Item config.local.example.json config.local.json
# 编辑 config.local.json 填入自己的密钥
npm run web:check
npm run web
```

需要语音时另按 `.env.example` 与解说组件说明填写自己的语音配置。未配置语音不会自动借用作者的账号。退出服务用 Ctrl+C。

## 回放

开局页顶部“观看回放”进入历史列表。新网页对局自动录制游戏画布；支持从头、进度、倍速和全屏。安装FFmpeg并加入PATH后才能封装可跳转WebM；缺FFmpeg时游戏仍可运行。画布录像暂不包含声音和DOM人物浮层。录像、会话日志与密钥只留在各自电脑，不随Git分发。

## 包的边界

- 这是浏览器版完整运行包，不能用仓库根部旧Godot工程的版本号代替本包的快照。
- 当前关卡生成器随包提供**编译后的运行组件**，没有把其 `.py` 实现源码混入公共SDK。可以运行不表示字节码无法被分析；也不额外授予生成器源代码开源许可。
- `runtime-manifest.json`记录运行文件哈希；`versions/current.json`只使用仓库内相对路径。所有真实密钥为空，不能承诺任意第三方模型账号都有相同可用性。
- 原版根目录Godot工程和资产保持不变。本包继续使用Godot为战斗状态真相源；展示不能证明游戏后程性能或完整十关稳定性。
- Windows x64为本次验证环境。其他系统可以安装对应Node/Python后检查，未声称完成各平台实战验收。

资源与组件许可沿用仓库原许可及各组件随附许可；Noto字体OFL、安妮模型与动作许可保留在运行包中。
