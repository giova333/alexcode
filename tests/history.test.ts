import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';

import { Message } from '../src/core/message.js';
import { HistoryStorage } from '../src/history/storage.js';
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

describe('HistoryStorage', () => {
  it('saves and loads a session', () => {
    const h = new HistoryStorage('.agent/history/', newDir());
    const sid = h.newSessionId();
    const m1 = Message.user('hi');
    m1.tokenCount = 5;
    const m2 = Message.assistant('hello');
    m2.tokenCount = 6;
    h.save(sid, [m1, m2]);

    const loaded = h.load(sid)!;
    expect(loaded).toHaveLength(2);
    expect(loaded[0]!.role).toBe('user');
    expect(loaded[0]!.text).toBe('hi');
    expect(loaded[1]!.tokenCount).toBe(6);
  });

  it('appends only new messages on repeated saves', () => {
    const dir = newDir();
    const h = new HistoryStorage('.agent/history/', dir);
    const sid = h.newSessionId();
    const m1 = Message.user('one');
    h.save(sid, [m1]);
    const m2 = Message.assistant('two');
    h.save(sid, [m1, m2]);
    expect(h.load(sid)!).toHaveLength(2);
  });

  it('clears a session to header-only', () => {
    const h = new HistoryStorage('.agent/history/', newDir());
    const sid = h.newSessionId();
    h.save(sid, [Message.user('x')]);
    h.clearSession(sid);
    expect(h.load(sid)).toBeNull();
  });

  it('lists, finds, and resolves the latest session', () => {
    const h = new HistoryStorage('.agent/history/', newDir());
    const sid = h.newSessionId();
    h.save(sid, [Message.user('hi')]);
    const sessions = h.listSessions();
    expect(sessions[0]!.session_id).toBe(sid);
    expect(sessions[0]!.message_count).toBe(1);
    expect(h.findSession(sid.slice(0, 8))).toBe(sid);
    expect(h.getLatestSessionId()).toBe(sid);
  });

  it('rewrites a session from scratch', () => {
    const h = new HistoryStorage('.agent/history/', newDir());
    const sid = h.newSessionId();
    h.save(sid, [Message.user('a'), Message.assistant('b')]);
    h.rewrite(sid, [Message.user('only')]);
    const loaded = h.load(sid)!;
    expect(loaded).toHaveLength(1);
    expect(loaded[0]!.text).toBe('only');
  });
});
