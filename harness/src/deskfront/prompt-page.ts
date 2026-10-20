import { readFileSync } from 'node:fs';

/** Reading UI only. Prompt text is fetched from the Python source composer. */
export function deskfrontPromptPage(): string {
  return readFileSync(new URL('./prompt-page.html', import.meta.url), 'utf8');
}

/** Read-only real log cases, with an optional static teaching example. */
export function deskfrontSymbolMapGuide(): string {
  return readFileSync(new URL('./symbol-map-guide.html', import.meta.url), 'utf8');
}
