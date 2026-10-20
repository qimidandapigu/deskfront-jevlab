import { existsSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { spawn, type ChildProcess } from 'node:child_process';
export async function startNativeAnnie(gamePid: number, url: string, folder: string): Promise<ChildProcess> {
  if (process.platform !== 'win32') throw Error('annie-native-windows-required');
  const executable=fileURLToPath(new URL('../../tools/deskfront-presenter/bin/DeskfrontAnnieHost.exe',import.meta.url));
  if (!existsSync(executable)) throw Error('annie-native-host-not-built: python scripts/build-deskfront-presenter.py');
  if (!Number.isSafeInteger(gamePid)||gamePid<1) throw Error('annie-game-pid-invalid');
  const address=new URL(url);if(address.protocol!=='http:'||address.hostname!=='127.0.0.1')throw Error('annie-local-viewer-required');
  await mkdir(resolve(folder),{recursive:true});
  return spawn(executable,[String(gamePid),url,resolve(folder)],{windowsHide:true,stdio:'ignore'});
}
