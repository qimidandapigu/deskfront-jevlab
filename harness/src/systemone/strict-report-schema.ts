import { createHash } from 'node:crypto';

type Node = Record<string, unknown>;
export interface ReportSchema {
  providerSchema: Node;
  responseSchemaSha256: string;
  providerSchemaSha256: string;
  /** First violation path only; never includes response values. No coercion/defaults. */
  check(value: unknown): string | null;
}
const record = (value: unknown): value is Node => !!value && typeof value === 'object' && !Array.isArray(value);
const LOCAL_BOUNDS = new Set(['minLength', 'maxLength', 'minItems', 'maxItems']);
const COMMON = ['type', 'description', 'enum'];
const FIELDS: Record<string, string[]> = {
  object: ['properties', 'required', 'additionalProperties'], array: ['items', 'minItems', 'maxItems'],
  string: ['pattern', 'minLength', 'maxLength'], boolean: [],
  number: ['minimum', 'maximum'], integer: ['minimum', 'maximum'],
};
const sha = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex');

/** Deliberately small supported schema dialect. Unknown assertions fail closed.
 * DeepSeek beta does not support string/array length bounds: only those four
 * assertions are removed from the wire schema; local acceptance keeps them.
 * https://api-docs.deepseek.com/guides/tool_calls/
 */
export function compileReportSchema(input: unknown): ReportSchema {
  if (!record(input) || input.type !== 'object') throw new Error('strict-report-schema-root-object-required');
  let bytes: string;
  try { bytes = JSON.stringify(input); } catch { throw new Error('strict-report-schema-not-json'); }
  if (Buffer.byteLength(bytes) > 65536) throw new Error('strict-report-schema-too-large');
  const schema = JSON.parse(bytes) as Node;
  let nodes = 0;
  function compile(node: unknown, depth: number): { wire: Node; check: (value: unknown, path: string) => string | null } {
    if (++nodes > 1024 || depth > 16 || !record(node) || typeof node.type !== 'string' || !Object.hasOwn(FIELDS, node.type))
      throw new Error('unsupported-strict-report-schema');
    const type = node.type;
    const allowed = new Set([...COMMON, ...FIELDS[type]!]);
    if (Object.keys(node).some(key => !allowed.has(key)) || (node.description !== undefined && typeof node.description !== 'string'))
      throw new Error('unsupported-strict-report-schema-keyword');
    if (node.enum !== undefined && (!Array.isArray(node.enum) || !node.enum.length || node.enum.length > 128 ||
        node.enum.some(v => !['string', 'number', 'boolean'].includes(typeof v) || typeof v === 'number' && !Number.isFinite(v))))
      throw new Error('invalid-strict-report-schema-enum');
    for (const key of ['minimum', 'maximum']) if (node[key] !== undefined && (typeof node[key] !== 'number' || !Number.isFinite(node[key])))
      throw new Error('invalid-strict-report-schema-number-bound');
    if (typeof node.minimum === 'number' && typeof node.maximum === 'number' && node.minimum > node.maximum)
      throw new Error('invalid-strict-report-schema-bound-order');
    for (const key of LOCAL_BOUNDS) if (node[key] !== undefined && (!Number.isSafeInteger(node[key]) || (node[key] as number) < 0))
      throw new Error('invalid-strict-report-schema-length-bound');
    for (const [low, high] of [['minLength', 'maxLength'], ['minItems', 'maxItems']])
      if (typeof node[low!] === 'number' && typeof node[high!] === 'number' && (node[low!] as number) > (node[high!] as number))
        throw new Error('invalid-strict-report-schema-bound-order');
    let pattern: RegExp | undefined;
    if (node.pattern !== undefined) {
      if (typeof node.pattern !== 'string' || node.pattern.length > 512) throw new Error('invalid-strict-report-schema-pattern');
      try { pattern = new RegExp(node.pattern); } catch { throw new Error('invalid-strict-report-schema-pattern'); }
    }
    const wire = Object.fromEntries(Object.entries(node).filter(([key]) => !LOCAL_BOUNDS.has(key)));
    let children: Record<string, ReturnType<typeof compile>> = {};
    let item: ReturnType<typeof compile> | undefined;
    if (type === 'object') {
      if (!record(node.properties) || node.additionalProperties !== false || !Array.isArray(node.required) ||
          node.required.some(key => typeof key !== 'string') || new Set(node.required).size !== node.required.length ||
          node.required.length !== Object.keys(node.properties).length || Object.keys(node.properties).some(key => !(node.required as string[]).includes(key)))
        throw new Error('strict-report-schema-all-properties-required-and-closed');
      children = Object.fromEntries(Object.entries(node.properties).map(([key, child]) => [key, compile(child, depth + 1)]));
      wire.properties = Object.fromEntries(Object.entries(children).map(([key, child]) => [key, child.wire]));
    } else if (type === 'array') { item = compile(node.items, depth + 1); wire.items = item.wire; }
    return { wire, check(value, path) {
      if (node.enum !== undefined && !(node.enum as unknown[]).includes(value)) return path + ':enum';
      if (type === 'object') {
        if (!record(value)) return path + ':object';
        if (Object.keys(value).some(key => !Object.hasOwn(children, key))) return path + ':additionalProperties';
        for (const [key, child] of Object.entries(children)) {
          if (!Object.hasOwn(value, key)) return path + ':required';
          const error = child.check(value[key], path + '.' + key); if (error) return error;
        }
      } else if (type === 'array') {
        if (!Array.isArray(value)) return path + ':array';
        if (typeof node.minItems === 'number' && value.length < node.minItems || typeof node.maxItems === 'number' && value.length > node.maxItems) return path + ':items-length';
        for (let i = 0; i < value.length; i++) { const error = item!.check(value[i], path + '[' + i + ']'); if (error) return error; }
      } else if (type === 'string') {
        if (typeof value !== 'string') return path + ':string';
        const length = Array.from(value).length;
        if (typeof node.minLength === 'number' && length < node.minLength || typeof node.maxLength === 'number' && length > node.maxLength) return path + ':string-length';
        if (pattern && !pattern.test(value)) return path + ':pattern';
      } else if (type === 'boolean') { if (typeof value !== 'boolean') return path + ':boolean'; }
      else {
        if (typeof value !== 'number' || !Number.isFinite(value) || type === 'integer' && !Number.isInteger(value)) return path + ':number';
        if (typeof node.minimum === 'number' && value < node.minimum || typeof node.maximum === 'number' && value > node.maximum) return path + ':number-bound';
      }
      return null;
    } };
  }
  const compiled = compile(schema, 0);
  return { providerSchema: compiled.wire, responseSchemaSha256: sha(schema), providerSchemaSha256: sha(compiled.wire),
    check: value => compiled.check(value, '$') };
}

/** Parse one complete JSON object and reject duplicate keys rather than letting
 * JSON.parse silently choose the last menu. Never repairs or extracts braces.
 */
export function parseReportArguments(text: string): Record<string, unknown> {
  if (!text.trim() || Buffer.byteLength(text) > 65536) throw new Error('invalid-report-arguments-size');
  const value: unknown = JSON.parse(text);
  if (!record(value)) throw new Error('report-arguments-object-required');
  let at = 0;
  const ws = () => { while (/\s/.test(text[at] ?? '') && at < text.length) at++; };
  const string = () => {
    const start = at++; let escaped = false;
    while (at < text.length) { const c = text[at++]!; if (escaped) escaped = false; else if (c === '\\') escaped = true; else if (c === '"') return JSON.parse(text.slice(start, at)) as string; }
    throw new Error('incomplete-report-string');
  };
  function visit(depth: number): void {
    if (depth > 32) throw new Error('report-arguments-too-deep');
    ws(); const c = text[at];
    if (c === '{') {
      at++; ws(); const keys = new Set<string>();
      if (text[at] === '}') { at++; return; }
      do { ws(); const key = string(); if (keys.has(key)) throw new Error('duplicate-report-key'); keys.add(key); ws(); at++; visit(depth + 1); ws(); if (text[at] === '}') { at++; return; } at++; } while (at < text.length);
    } else if (c === '[') {
      at++; ws(); if (text[at] === ']') { at++; return; }
      do { visit(depth + 1); ws(); if (text[at] === ']') { at++; return; } at++; } while (at < text.length);
    } else if (c === '"') { string(); return; }
    else { while (at < text.length && !/[\s,}\]]/.test(text[at]!)) at++; return; }
    throw new Error('incomplete-report-arguments');
  }
  visit(0); ws(); if (at !== text.length) throw new Error('trailing-report-arguments');
  return value;
}
