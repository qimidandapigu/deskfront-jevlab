import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

/** Hash the actual working source, including uncommitted rules; never read credentials. */
export function sourceProvenance(root = process.cwd()) {
  const files: string[] = [];
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) walk(path); else if (entry.isFile()) files.push(path);
    }
  };
  walk(join(root, 'src'));
  files.push(join(root, 'package.json'), join(root, 'package-lock.json'));
  const hashes = Object.fromEntries(files.sort().map(path => [relative(root, path).replaceAll('\\', '/'), createHash('sha256').update(readFileSync(path)).digest('hex')]));
  let commit: string | null = null;
  try { commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); } catch { /* Unversioned exports still have a content digest. */ }
  return { schema: 'quickplay-source-v1', commit, sourceSha256: createHash('sha256').update(JSON.stringify(hashes)).digest('hex'), files: hashes };
}
