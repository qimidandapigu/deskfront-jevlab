import type { IncomingMessage } from 'node:http';
import { spawn } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deskfrontPromptPage, deskfrontSymbolMapGuide } from '../deskfront/prompt-page.js';
import { sendJson, type SendResponse } from './http.js';

const inspector = fileURLToPath(new URL('../deskfront/prompt_inspect.py', import.meta.url));
export function listPromptSessions(logDir: string) {
  try {
    return readdirSync(logDir).filter(name => /^deskfront-[\w-]+\.jsonl$/.test(name))
      .map(name => ({ id: name.slice(0, -6), updated: statSync(resolve(logDir, name)).mtimeMs }))
      .sort((a, b) => b.updated - a.updated).slice(0, 40);
  } catch { return []; }
}

export function inspectPrompt(options: Record<string, unknown>, python = process.env.PYTHON_BIN ?? 'python'): Promise<unknown> {
  return new Promise((resolveResult, reject) => {
    const child = spawn(python, ['-X', 'utf8', inspector], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', error = '', bytes = 0;
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    const timer = setTimeout(() => { child.kill(); reject(new Error('提示词读取超时，请重试')); }, 10000);
    child.stdout.on('data', chunk => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > 8 * 1024 * 1024) { child.kill(); reject(new Error('请求记录过大')); }
      else output += chunk;
    });
    child.stderr.on('data', chunk => { if (error.length < 2000) error += chunk; });
    child.stdin.on('error', () => {});
    child.once('error', err => { clearTimeout(timer); reject(err); });
    child.once('close', code => {
      clearTimeout(timer);
      try {
        const value = JSON.parse(output) as { error?: string };
        if (code !== 0 || value.error) reject(new Error(value.error ?? '读取失败'));
        else resolveResult(value);
      } catch { reject(new Error(error || '提示词读取失败；请检查 Python 环境')); }
    });
    child.stdin.end(JSON.stringify(options));
  });
}

async function boundedBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = []; let bytes = 0;
  for await (const chunk of req) {
    bytes += Buffer.byteLength(chunk);
    if (bytes > 24000) throw new Error('请求内容过大');
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString('utf8');
}

export async function handleDeskfrontPromptRoute(req: IncomingMessage, url: URL, send: SendResponse, logDir: string): Promise<boolean> {
  if (req.method === 'GET' && url.pathname === '/runtime/deskfront/maps') {
    send(200, deskfrontSymbolMapGuide()); return true;
  }
  if (req.method === 'GET' && url.pathname === '/runtime/deskfront/prompts') {
    send(200, deskfrontPromptPage()); return true;
  }
  if (req.method === 'GET' && url.pathname === '/api/deskfront/prompts/sessions') {
    sendJson(send, 200, { sessions: listPromptSessions(logDir) }); return true;
  }
  if (req.method !== 'POST' || url.pathname !== '/api/deskfront/prompts') return false;
  try {
    if (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) throw new Error('仅允许本页面读取');
    const body = JSON.parse(await boundedBody(req)) as Record<string, unknown>;
    if (!['commander', 'executor', 'personal'].includes(String(body.role))) throw new Error('未知角色');
    if (!['template', 'log'].includes(String(body.kind))) throw new Error('未知来源');
    const options: Record<string, unknown> = { role: body.role, kind: body.kind };
    if (body.kind === 'log') {
      // No caller-supplied path. IDs must exist in the bounded local inventory.
      const session = listPromptSessions(logDir).find(item => item.id === body.session);
      if (!session) throw new Error('对局日志不存在');
      if (!['green', 'red'].includes(String(body.faction))) throw new Error('未知阵营');
      options.logPath = resolve(logDir, session.id + '.jsonl'); options.faction = body.faction;
      options.sample = body.sample === 'answered' ? 'answered' : 'latest';
      if (body.display === 'world-overlay') {
        options.display = 'world-overlay';
        if (body.run_id !== undefined) {
          if (typeof body.run_id !== 'string' || !body.run_id.trim() || body.run_id.length > 160) throw new Error('战局编号无效');
          options.run_id = body.run_id;
        }
      }
    } else {
      if (!['clear_exit', 'flag'].includes(String(body.mode))) throw new Error('未知模式');
      if (body.script !== undefined && (typeof body.script !== 'string' || body.script.length > 4000)) throw new Error('剧本最多4000字符');
      Object.assign(options, { mode: body.mode, equipment: body.equipment === true, antiArmor: body.antiArmor === true,
        story: body.story === true, script: body.script });
    }
    sendJson(send, 200, await inspectPrompt(options));
  } catch (error) {
    sendJson(send, 400, { error: error instanceof Error ? error.message : String(error) });
  }
  return true;
}
