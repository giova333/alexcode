import { describe, expect, it } from 'vitest';

import { Compactor } from '../src/compaction/compactor.js';
import { Conversation } from '../src/core/conversation.js';
import { Message } from '../src/core/message.js';
import { countMessageTokens } from '../src/core/tokens.js';
import { FakeLLMProvider, makeTestConfig } from './fakes.js';

function addText(c: Conversation, role: string, text: string): void {
  const m = new Message(role, [{ type: 'text', text }]);
  m.tokenCount = countMessageTokens(m.toDict());
  c.append(m);
}

describe('Compactor', () => {
  it('does nothing below the threshold', async () => {
    const conv = new Conversation();
    addText(conv, 'user', 'hi');
    const llm = new FakeLLMProvider();
    const compactor = new Compactor(makeTestConfig().compaction, llm, conv);
    const did = await compactor.maybeCompact();
    expect(did).toBe(false);
    expect(conv.messages).toHaveLength(1);
  });

  it('summarizes old messages when forced', async () => {
    const conv = new Conversation();
    for (let i = 0; i < 10; i++) addText(conv, i % 2 === 0 ? 'user' : 'assistant', `message ${i}`);
    const llm = new FakeLLMProvider();
    llm.setTextResponse('SUMMARY TEXT');
    const config = makeTestConfig({ compaction: { threshold_tokens: 1, keep_recent_messages: 4 } });
    const compactor = new Compactor(config.compaction, llm, conv);

    const did = await compactor.maybeCompact(true);
    expect(did).toBe(true);
    expect(conv.messages[0]!.text).toContain('[Previous conversation summary]');
    expect(conv.messages[0]!.text).toContain('SUMMARY TEXT');
    // summary + last 4 kept
    expect(conv.messages).toHaveLength(5);
  });

  it('truncates oversized tool results', async () => {
    const conv = new Conversation();
    // Realistic large result: many short words/lines (not one giant token run,
    // which is pathological for pure-JS BPE tokenizers).
    const big = Array.from({ length: 4000 }, (_, i) => `line ${i} of tool output`).join('\n');
    const assistant = new Message('assistant', [
      { type: 'tool_use', id: 't1', name: 'bash', input: {} },
    ]);
    assistant.tokenCount = countMessageTokens(assistant.toDict());
    conv.append(assistant);
    const toolMsg = new Message('user', [
      { type: 'tool_result', tool_use_id: 't1', content: big, is_error: false },
    ]);
    toolMsg.tokenCount = countMessageTokens(toolMsg.toDict());
    conv.append(toolMsg);

    const llm = new FakeLLMProvider();
    llm.setTextResponse('s');
    const config = makeTestConfig({
      compaction: { threshold_tokens: 1, keep_recent_messages: 50 },
    });
    const compactor = new Compactor(config.compaction, llm, conv);
    await compactor.maybeCompact(true);

    const truncated = conv.messages.find((m) => m.content.some((b) => b.type === 'tool_result'))!;
    const block = truncated.content.find((b) => b.type === 'tool_result')!;
    if (block.type === 'tool_result') {
      expect(block.content).toContain('truncated from');
      expect(block.content.length).toBeLessThan(big.length);
    }
  });
});
