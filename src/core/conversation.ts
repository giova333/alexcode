/** Conversation state management. */

import { Message, type ApiMessage, type ContentBlock } from './message.js';

export class Conversation {
  messages: Message[] = [];
  systemPrompt = '';
  totalTokens = 0;

  append(message: Message): void {
    this.messages.push(message);
    this.totalTokens += message.tokenCount;
  }

  /** Convert messages to the format expected by LLM APIs. */
  toApiMessages(): ApiMessage[] {
    return this.messages.map((msg) => msg.toDict());
  }

  clear(): void {
    this.messages = [];
    this.totalTokens = 0;
  }

  /** Replace current messages with loaded ones, recalculating token count. */
  loadMessages(messages: Message[]): void {
    this.messages = sanitizeToolPairs([...messages]);
    this.totalTokens = this.messages.reduce((sum, m) => sum + m.tokenCount, 0);
  }
}

function hasToolResults(msg: Message): boolean {
  return msg.content.some((b) => b.type === 'tool_result');
}

/**
 * Fix orphaned tool_result blocks that have no matching tool_use.
 *
 * After compaction or a crash, a user message may contain tool_result blocks
 * whose corresponding assistant tool_use was summarized away. The Anthropic API
 * rejects these. Convert orphaned tool_result messages to plain text so the
 * conversation stays valid.
 */
export function sanitizeToolPairs(messages: Message[]): Message[] {
  const result: Message[] = [];
  for (const msg of messages) {
    if (msg.role !== 'user' || !hasToolResults(msg)) {
      result.push(msg);
      continue;
    }

    // Collect tool_use IDs from the immediately preceding assistant message.
    const prevToolIds = new Set<string>();
    const prev = result[result.length - 1];
    if (prev && prev.role === 'assistant') {
      for (const block of prev.content) {
        if (block.type === 'tool_use') prevToolIds.add(block.id);
      }
    }

    let orphaned = false;
    for (const block of msg.content) {
      if (block.type === 'tool_result' && !prevToolIds.has(block.tool_use_id)) {
        orphaned = true;
        break;
      }
    }

    if (!orphaned) {
      result.push(msg);
    } else {
      const textParts: string[] = [];
      for (const block of msg.content) {
        if (block.type === 'tool_result') {
          const preview = String(block.content ?? '').slice(0, 500);
          textParts.push(`[Tool result]: ${preview}`);
        } else if (block.type === 'text') {
          textParts.push(block.text);
        }
      }
      if (textParts.length > 0) {
        const replacement = Message.user(textParts.join('\n'));
        replacement.tokenCount = msg.tokenCount;
        result.push(replacement);
      }
      // else: drop empty message entirely
    }
  }
  return result;
}

export type { ContentBlock };
