import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { createExternalGameRuntime, type ExternalGameManifest } from './runtime.js';
import type { RuntimeRegistry } from '../arena/runtime.js';
import { normalizeSessionConfig } from '../arena/session-config.js';

export function loadGameManifest(path: string): ExternalGameManifest {
  const file = resolve(path);
  const manifest = JSON.parse(readFileSync(file, 'utf8')) as ExternalGameManifest;
  if (!manifest || typeof manifest !== 'object' || typeof manifest.name !== 'string' || typeof manifest.description !== 'string') throw new Error('Invalid game manifest metadata');
  for (const key of Object.keys(manifest)) if (!['protocol', 'id', 'name', 'description', 'command', 'cwd', 'env', 'variants', 'capabilities', 'maxSessions', 'startupTimeoutMs', 'options'].includes(key)) throw new Error(`Unknown manifest field: ${key}`);
  if (!manifest.name || manifest.cwd !== undefined && typeof manifest.cwd !== 'string') throw new Error('Invalid manifest name/cwd');
  for (const key of ['human', 'ai', 'seed'] as const) if (typeof manifest.capabilities?.[key] !== 'boolean') throw new Error(`Missing capability: ${key}`);
  if (manifest.env && (typeof manifest.env !== 'object' || Object.values(manifest.env).some(v => typeof v !== 'string'))) throw new Error('env values must be strings');
  if (manifest.variants && (!Array.isArray(manifest.variants) || manifest.variants.some(v => !v || typeof v.id !== 'string' || typeof v.name !== 'string'))) throw new Error('Invalid variants');
  for (const key of ['maxSessions', 'startupTimeoutMs'] as const) if (manifest[key] !== undefined && (!Number.isSafeInteger(manifest[key]) || manifest[key]! < 1)) throw new Error(`Invalid ${key}`);
  if (manifest.options && (typeof manifest.options !== 'object' || Array.isArray(manifest.options))) throw new Error('Invalid options');
  for (const schema of Object.values(manifest.options ?? {})) {
    if (!schema || !['string', 'number', 'integer', 'boolean'].includes(schema.type)) throw new Error('Invalid option schema');
    for (const key of Object.keys(schema)) if (!['type', 'description', 'default', 'enum', 'min', 'max'].includes(key)) throw new Error(`Unknown option schema field: ${key}`);
    for (const bound of [schema.min, schema.max]) if (bound !== undefined && (typeof bound !== 'number' || !Number.isFinite(bound))) throw new Error('Invalid option bounds');
    if (schema.min !== undefined && schema.max !== undefined && schema.min > schema.max) throw new Error('Invalid option range');
    if (schema.enum !== undefined && (!Array.isArray(schema.enum) || !schema.enum.length || schema.enum.some(v => !['string', 'number', 'boolean'].includes(typeof v)))) throw new Error('Invalid option enum');
  }
  normalizeSessionConfig({ id: manifest.id, mode: 'turn', options: manifest.options }, {});
  createExternalGameRuntime(manifest); // Validate protocol and command before registration.
  return { ...manifest, cwd: resolve(dirname(file), manifest.cwd ?? '.') };
}

export function loadRegisteredGames(registry: RuntimeRegistry, configPath = 'games.local.json'): void {
  if (!existsSync(configPath)) return;
  const config = JSON.parse(readFileSync(configPath, 'utf8')) as { manifests: string[] };
  if (!Array.isArray(config.manifests) || config.manifests.some(path => typeof path !== 'string')) throw new Error('games.local.json requires manifests[]');
  for (const path of config.manifests) registry.register(createExternalGameRuntime(loadGameManifest(resolve(dirname(configPath), path))));
}

export function registerGameManifest(path: string, configPath = 'games.local.json', reservedIds: string[] = []) {
  const file = resolve(path), manifest = loadGameManifest(file);
  if (reservedIds.includes(manifest.id)) throw new Error(`Game id is already provided by the host: ${manifest.id}`);
  const config: { manifests: string[] } = existsSync(configPath) ? JSON.parse(readFileSync(configPath, 'utf8')) : { manifests: [] };
  if (!Array.isArray(config.manifests)) throw new Error('games.local.json requires manifests[]');
  const paths = config.manifests.map(p => resolve(dirname(configPath), p));
  for (const other of paths) if (other !== file && loadGameManifest(other).id === manifest.id) throw new Error(`Duplicate game id: ${manifest.id}`);
  if (!paths.includes(file)) config.manifests.push(file);
  writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n');
  return manifest.id;
}
