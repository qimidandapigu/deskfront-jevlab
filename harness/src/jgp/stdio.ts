import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import {
  PROTOCOL_VERSION,
  isGameMessage,
  type Capabilities,
  type GameAdapter,
  type HarnessMessage,
  type WorldState,
} from "./protocol.js";

export interface StdioAdapter extends GameAdapter {
  /** Resolves once the game has completed the hello handshake. */
  ready(): Promise<void>;
  /** Exit code once the child has exited, else null. */
  exitCode(): number | null;
  dispose(): void;
}

/**
 * JGP stdio transport (see docs/protocol.md): spawns the game as a child
 * process and wraps it in a GameAdapter. Protocol frames are NDJSON lines on
 * the child's stdout; actions are written as NDJSON lines to its stdin;
 * the child's stderr is passed through to ours.
 */
export function createStdioAdapter(command: string[]): StdioAdapter {
  if (command.length === 0) throw new Error("stdio adapter: empty command");
  const child: ChildProcess = spawn(command[0]!, command.slice(1), {
    stdio: ["pipe", "pipe", "inherit"],
  });

  let caps: Capabilities | null = null;
  let lastTick = 0;
  /** 最近一次经 getState 交付给引擎的 state 的 tick；actions 帧以此为准。 */
  let deliveredTick: number | null = null;
  let lastState: WorldState | null = null;
  let stateWaiters: Array<{ resolve: (s: WorldState) => void; reject: (e: Error) => void }> = [];
  let exitCode: number | null = null;
  let disposed = false;
  let readyResolve!: () => void;
  let readyReject!: (e: Error) => void;
  const readyPromise = new Promise<void>((res, rej) => { readyResolve = res; readyReject = rej; });

  function send(msg: HarnessMessage): void {
    if (child.stdin?.writable) child.stdin.write(JSON.stringify(msg) + "\n");
  }

  function failAll(e: Error): void {
    const waiters = stateWaiters;
    stateWaiters = [];
    for (const w of waiters) w.reject(e);
    readyReject(e);
  }

  const lines = createInterface({ input: child.stdout! });
  lines.on("line", (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      send({ type: "error", message: "invalid JSON line" });
      return;
    }
    if (!isGameMessage(parsed)) {
      send({ type: "error", message: "invalid message shape (see docs/protocol.md v1)" });
      return;
    }
    if (parsed.type === "hello") {
      caps = parsed.capabilities;
      send({ type: "hello_ack", protocolVersion: PROTOCOL_VERSION });
      readyResolve();
      return;
    }
    if (!caps) {
      send({ type: "error", message: "expected hello first" });
      return;
    }
    lastTick = parsed.state.tick;
    lastState = parsed.state;
    const waiters = stateWaiters;
    stateWaiters = [];
    if (waiters.length > 0) deliveredTick = parsed.state.tick;
    for (const w of waiters) w.resolve(parsed.state);
  });

  child.on("error", (e) => failAll(e));
  child.on("exit", (code) => {
    exitCode = code;
    failAll(new Error(`game process exited (code ${code ?? "null"})`));
  });

  return {
    capabilities() {
      if (!caps) throw new Error("game has not sent hello yet");
      return caps;
    },
    getState(): Promise<WorldState> {
      if (exitCode !== null) return Promise.reject(new Error(`game process exited (code ${exitCode})`));
      if (lastState) {
        const s = lastState;
        lastState = null;
        deliveredTick = s.tick;
        return Promise.resolve(s);
      }
      return new Promise<WorldState>((resolve, reject) => stateWaiters.push({ resolve, reject }));
    },
    execute(actions, entities) {
      // tick 取被处理那帧 state（最近一次交付），而非最新到达的 state
      send({ type: "actions", tick: deliveredTick ?? lastTick, actions, ...(entities ? { entities } : {}) });
    },
    ready: () => readyPromise,
    exitCode: () => exitCode,
    dispose() {
      if (disposed) return;
      disposed = true;
      failAll(new Error('adapter-disposed'));
      lines.close();
      child.stdin?.destroy();
      child.stdout?.destroy();
      child.kill();
      child.unref();
    },
  };
}
