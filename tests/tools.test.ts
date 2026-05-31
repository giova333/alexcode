import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { BashTool } from '../src/tools/builtin/bash.js';
import { EditTool } from '../src/tools/builtin/edit.js';
import { GlobTool } from '../src/tools/builtin/glob.js';
import { GrepTool } from '../src/tools/builtin/grep.js';
import { ReadTool } from '../src/tools/builtin/read.js';
import { WriteTool } from '../src/tools/builtin/write.js';
import { ToolExecutor } from '../src/tools/executor.js';
import { ToolError } from '../src/tools/base.js';
import { ToolRegistry } from '../src/tools/registry.js';
import { tmpDir } from './fakes.js';

const dirs: string[] = [];
function newDir(): string {
  const d = tmpDir();
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

describe('ToolRegistry', () => {
  it('registers and clones', () => {
    const r = new ToolRegistry();
    r.register(new ReadTool());
    r.register(new WriteTool());
    expect(r.listNames().sort()).toEqual(['read', 'write']);
    expect(r.cloneExcluding(new Set(['write'])).listNames()).toEqual(['read']);
    expect(r.cloneIncluding(new Set(['write'])).listNames()).toEqual(['write']);
    expect(r.allDefinitions()).toHaveLength(2);
  });
});

describe('ToolExecutor', () => {
  it('throws on unknown tool', async () => {
    const r = new ToolRegistry();
    const ex = new ToolExecutor(r);
    await expect(ex.execute('nope', {})).rejects.toBeInstanceOf(ToolError);
  });
});

describe('ReadTool / WriteTool', () => {
  it('writes and reads back with line numbers', async () => {
    const d = newDir();
    const file = path.join(d, 'sub', 'f.txt');
    const write = new WriteTool();
    const msg = await write.execute({ file_path: file, content: 'line1\nline2' });
    expect(msg).toContain('bytes to');
    expect(fs.existsSync(file)).toBe(true);

    const read = new ReadTool();
    const out = await read.execute({ file_path: file });
    expect(out).toContain('line1');
    expect(out).toContain('line2');
    expect(out).toMatch(/^\s+1\t/);
  });

  it('reports missing files', async () => {
    const out = await new ReadTool().execute({ file_path: '/no/such/file.txt' });
    expect(out).toContain('File not found');
  });

  it('honors offset and limit', async () => {
    const d = newDir();
    const file = path.join(d, 'f.txt');
    fs.writeFileSync(file, 'a\nb\nc\nd\n');
    const out = await new ReadTool().execute({ file_path: file, offset: 2, limit: 2 });
    expect(out).toContain('b');
    expect(out).toContain('c');
    expect(out).not.toContain('\td\n');
  });
});

describe('EditTool', () => {
  it('replaces a unique string', async () => {
    const d = newDir();
    const file = path.join(d, 'f.txt');
    fs.writeFileSync(file, 'hello world');
    const out = await new EditTool().execute({
      file_path: file,
      old_string: 'world',
      new_string: 'there',
    });
    expect(out).toContain('Replaced 1');
    expect(fs.readFileSync(file, 'utf-8')).toBe('hello there');
  });

  it('errors on missing string', async () => {
    const d = newDir();
    const file = path.join(d, 'f.txt');
    fs.writeFileSync(file, 'abc');
    const out = await new EditTool().execute({
      file_path: file,
      old_string: 'xyz',
      new_string: 'q',
    });
    expect(out).toContain('not found');
  });

  it('errors on multiple matches without replace_all', async () => {
    const d = newDir();
    const file = path.join(d, 'f.txt');
    fs.writeFileSync(file, 'a a a');
    const out = await new EditTool().execute({ file_path: file, old_string: 'a', new_string: 'b' });
    expect(out).toContain('found 3 times');
  });

  it('replaces all when requested', async () => {
    const d = newDir();
    const file = path.join(d, 'f.txt');
    fs.writeFileSync(file, 'a a a');
    const out = await new EditTool().execute({
      file_path: file,
      old_string: 'a',
      new_string: 'b',
      replace_all: true,
    });
    expect(out).toContain('Replaced 3');
    expect(fs.readFileSync(file, 'utf-8')).toBe('b b b');
  });
});

describe('GlobTool', () => {
  it('finds files by pattern', async () => {
    const d = newDir();
    fs.writeFileSync(path.join(d, 'a.ts'), '');
    fs.writeFileSync(path.join(d, 'b.js'), '');
    const out = await new GlobTool().execute({ pattern: '*.ts', path: d });
    expect(out).toContain('a.ts');
    expect(out).not.toContain('b.js');
  });

  it('reports no matches', async () => {
    const d = newDir();
    const out = await new GlobTool().execute({ pattern: '*.zzz', path: d });
    expect(out).toContain('No files matching');
  });
});

describe('GrepTool', () => {
  it('finds matching lines', async () => {
    const d = newDir();
    fs.writeFileSync(path.join(d, 'f.txt'), 'foo\nbar\nfoobar\n');
    const out = await new GrepTool().execute({ pattern: 'foo', path: d });
    expect(out).toContain('foo');
  });

  it('reports no matches', async () => {
    const d = newDir();
    fs.writeFileSync(path.join(d, 'f.txt'), 'abc\n');
    const out = await new GrepTool().execute({ pattern: 'zzzznope', path: d });
    expect(out).toContain('No matches');
  });
});

describe('BashTool', () => {
  it('captures stdout', async () => {
    const out = await new BashTool(10).execute({ command: 'echo hello' });
    expect(out).toContain('hello');
  });

  it('reports a non-zero exit code', async () => {
    const out = await new BashTool(10).execute({ command: 'exit 3' });
    expect(out).toContain('Exit code: 3');
  });

  it('times out long commands', async () => {
    const out = await new BashTool(1).execute({ command: 'sleep 5' });
    expect(out).toContain('timed out');
  });
});
