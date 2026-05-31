import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { Message } from '../src/core/message.js';
import { MemoryFiles } from '../src/memory/files.js';
import { MemoryManager } from '../src/memory/manager.js';
import type { MemoryProvider, MemorySearchResult } from '../src/memory/provider.js';
import { makeTestConfig, tmpDir } from './fakes.js';

const dirs: string[] = [];
function newDir(): string {
  const d = tmpDir();
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

describe('MemoryFiles', () => {
  it('reads empty when missing and appends with separators', () => {
    const d = newDir();
    const files = new MemoryFiles('.agent/MEMORY.md', d);
    expect(files.read()).toBe('');
    files.append('first');
    files.append('second');
    const text = files.read();
    expect(text).toContain('first');
    expect(text).toContain('second');
    expect(fs.existsSync(path.join(d, '.agent', 'MEMORY.md'))).toBe(true);
  });
});

describe('MemoryManager', () => {
  it('saves to and loads from MEMORY.md', async () => {
    const d = newDir();
    const mgr = new MemoryManager(makeTestConfig().memory, d, null);
    await mgr.saveMain('a durable fact');
    expect(await mgr.loadContext()).toContain('a durable fact');
  });

  it('returns [] when no provider configured', async () => {
    const d = newDir();
    const mgr = new MemoryManager(makeTestConfig().memory, d, null);
    expect(await mgr.search('anything')).toEqual([]);
  });

  it('delegates search and ingest to a provider', async () => {
    const d = newDir();
    const ingested: Message[][] = [];
    const provider: MemoryProvider = {
      scope: 'project',
      async search(): Promise<MemorySearchResult[]> {
        return [{ text: 'remembered', source: 'project', score: 0.9 }];
      },
      enqueueTurn(messages) {
        ingested.push(messages);
      },
      async close() {},
    };
    const mgr = new MemoryManager(makeTestConfig().memory, d, provider);
    const results = await mgr.search('q');
    expect(results[0]!.text).toBe('remembered');

    mgr.ingestTurn(Message.user('u'), [Message.assistant('a')]);
    expect(ingested[0]).toHaveLength(2);
  });
});
