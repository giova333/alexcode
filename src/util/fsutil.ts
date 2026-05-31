/** Small filesystem path helpers shared by tools. */

import os from 'node:os';
import path from 'node:path';

/** Expand a leading ~ to the user's home directory (mirrors Path.expanduser). */
export function expandUser(p: string): string {
  if (p === '~') return os.homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) {
    return path.join(os.homedir(), p.slice(2));
  }
  return p;
}
