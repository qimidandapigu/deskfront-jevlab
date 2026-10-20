import type { IncomingMessage } from 'node:http';

/** The small transport boundary shared by viewer route modules. */
export type SendResponse = (status: number, body: string | Buffer, type?: string) => void;

export function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => { data += chunk; });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

export function sendJson(send: SendResponse, status: number, value: unknown): void {
  send(status, JSON.stringify(value), 'application/json');
}
