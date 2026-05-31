import { describe, it, expect } from 'vitest';

import { Conversation, sanitizeToolPairs } from '../src/core/conversation.js';
import { Message } from '../src/core/message.js';
import { countMessageTokens, countTokens } from '../src/core/tokens.js';

describe('Message', () => {
  it('creates user and assistant messages', () => {
    const u = Message.user('hello');
    expect(u.role).toBe('user');
    expect(u.text).toBe('hello');
    const a = Message.assistant('hi');
    expect(a.role).toBe('assistant');
    expect(a.text).toBe('hi');
  });

  it('creates tool_result messages', () => {
    const m = Message.toolResult('t1', 'output', true);
    expect(m.role).toBe('user');
    expect(m.content[0]).toEqual({
      type: 'tool_result',
      tool_use_id: 't1',
      content: 'output',
      is_error: true,
    });
  });

  it('concatenates text blocks for .text', () => {
    const m = new Message('assistant', [
      { type: 'text', text: 'a' },
      { type: 'tool_use', id: 'x', name: 'bash', input: {} },
      { type: 'text', text: 'b' },
    ]);
    expect(m.text).toBe('ab');
  });

  it('serializes to API format', () => {
    const m = Message.user('hi');
    expect(m.toDict()).toEqual({ role: 'user', content: [{ type: 'text', text: 'hi' }] });
  });
});

describe('Conversation', () => {
  it('tracks total tokens on append', () => {
    const c = new Conversation();
    const m = Message.user('hi');
    m.tokenCount = 7;
    c.append(m);
    expect(c.totalTokens).toBe(7);
    expect(c.messages).toHaveLength(1);
  });

  it('clears state', () => {
    const c = new Conversation();
    const m = Message.user('hi');
    m.tokenCount = 3;
    c.append(m);
    c.clear();
    expect(c.messages).toHaveLength(0);
    expect(c.totalTokens).toBe(0);
  });

  it('loadMessages recalculates tokens', () => {
    const c = new Conversation();
    const a = Message.user('x');
    a.tokenCount = 2;
    const b = Message.assistant('y');
    b.tokenCount = 5;
    c.loadMessages([a, b]);
    expect(c.totalTokens).toBe(7);
  });
});

describe('sanitizeToolPairs', () => {
  it('keeps valid tool_use/tool_result pairs', () => {
    const assistant = new Message('assistant', [
      { type: 'tool_use', id: 't1', name: 'bash', input: {} },
    ]);
    const result = new Message('user', [
      { type: 'tool_result', tool_use_id: 't1', content: 'ok', is_error: false },
    ]);
    const out = sanitizeToolPairs([assistant, result]);
    expect(out).toHaveLength(2);
    expect(out[1]!.content[0]!.type).toBe('tool_result');
  });

  it('converts orphaned tool_result to text', () => {
    const result = new Message('user', [
      { type: 'tool_result', tool_use_id: 'missing', content: 'orphan', is_error: false },
    ]);
    const out = sanitizeToolPairs([result]);
    expect(out).toHaveLength(1);
    expect(out[0]!.content[0]!.type).toBe('text');
    expect(out[0]!.text).toContain('orphan');
  });
});

describe('tokens', () => {
  it('counts tokens in text', () => {
    expect(countTokens('hello world')).toBeGreaterThan(0);
  });

  it('adds per-message overhead', () => {
    const m = Message.user('hello');
    const count = countMessageTokens(m.toDict());
    expect(count).toBeGreaterThanOrEqual(4);
  });
});
