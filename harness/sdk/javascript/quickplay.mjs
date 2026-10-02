import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { EventEmitter } from 'node:events';

export const PROTOCOL = 'quickplay-game/v1';

/** Standard-library SDK; no provider configuration or simulation loop is required. */
export class Game extends EventEmitter {
  static async connect() {
    const game = new Game();
    await game.ready;
    return game;
  }

  constructor() {
    super();
    this.stopped = false;
    this.pending = new Map();
    this.ready = new Promise((resolve, reject) => { this.resolveReady = resolve; this.rejectReady = reject; });
    this.lines = createInterface({ input: process.stdin });
    this.lines.on('line', line => {
      try {
        const message = JSON.parse(line);
        if (!this.config) {
          if (message.type !== 'start' || message.protocol !== PROTOCOL) throw new Error('Protocol mismatch');
          this.config = message.config; this.sessionId = message.sessionId;
          this.send({ type: 'ready', protocol: PROTOCOL }); this.resolveReady(); return;
        }
        if (message.type === 'stop') { this.close(); return; }
        if (message.type === 'input' || message.type === 'action') { this.emit(message.type, message.body); return; }
        if (message.type === 'response') {
          const pending = this.pending.get(message.id); this.pending.delete(message.id);
          if (pending) message.error ? pending.reject(new Error(message.error)) : pending.resolve({ ...message.response, requestId: message.id });
        }
      } catch (error) { this.rejectReady(error); this.close(); }
    });
    this.lines.on('close', () => this.close());
  }

  send(message) { process.stdout.write(JSON.stringify(message) + '\n'); }
  publish(observation, payload = null) { if (!this.stopped) this.send({ type: 'state', observation, payload }); }
  record(record) { if (!this.stopped) this.send({ type: 'record', record }); }
  ask(state, questions) {
    if (this.stopped) return Promise.reject(new Error('session_stopped'));
    const id = randomUUID();
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject }); this.send({ type: 'request', id, state, questions });
    });
  }
  finish(outcome, error) { if (!this.stopped) this.send({ type: 'end', outcome, ...(error ? { error } : {}) }); }
  close() {
    if (this.stopped) return;
    this.stopped = true;
    this.rejectReady(new Error('session_stopped'));
    for (const pending of this.pending.values()) pending.reject(new Error('session_stopped'));
    this.pending.clear(); this.emit('stop'); this.lines.close(); process.stdin.pause();
  }
}
