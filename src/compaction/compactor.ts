/** Conversation compaction: summarize old messages and truncate oversized tool results. */

import type { CompactionConfig } from '../config/schema.js';
import type { Conversation } from '../core/conversation.js';
import { Message, type ContentBlock } from '../core/message.js';
import { countMessageTokens, countTokens } from '../core/tokens.js';
import type { LLMProvider } from '../llm/base.js';

// Maximum tokens allowed for a single tool_result content block after compaction.
const MAX_TOOL_RESULT_TOKENS = 800;

const SUMMARIZE_PROMPT = `Summarize this conversation concisely. Preserve:
- What tasks were performed
- Key decisions and their rationale
- File paths modified
- Any unresolved items or next steps

Be brief but complete. Format as markdown.`;

export class Compactor {
  constructor(
    private config: CompactionConfig,
    private llm: LLMProvider,
    private conversation: Conversation,
  ) {}

  /** Check threshold and compact if needed. Returns true if compacted. */
  async maybeCompact(force = false): Promise<boolean> {
    if (!force && this.conversation.totalTokens < this.config.threshold_tokens) {
      return false;
    }
    await this.summarizeOldMessages();
    // Always truncate oversized tool results, even when there are too few
    // messages to summarize.
    this.truncateAllToolResults();
    return true;
  }

  private async summarizeOldMessages(): Promise<void> {
    const keep = this.config.keep_recent_messages;
    const messages = this.conversation.messages;
    if (messages.length <= keep) return;

    let split = messages.length - keep;

    // Adjust split so we don't separate tool_use/tool_result pairs.
    while (split > 0 && hasToolResult(messages[split]!)) {
      split -= 1;
    }
    if (split <= 0) return;

    const oldMessages = messages.slice(0, split);
    const recentMessages = messages.slice(split);

    const conversationText = formatConversation(oldMessages);
    const summarizeMessages = [
      {
        role: 'user',
        content: [
          { type: 'text', text: `${SUMMARIZE_PROMPT}\n\n${conversationText}` },
        ] as ContentBlock[],
      },
    ];

    let summary = await this.callLlmSimple(summarizeMessages);
    if (!summary) summary = '(Conversation history was compacted)';

    const summaryMsg = Message.user(`[Previous conversation summary]\n${summary}`);
    summaryMsg.tokenCount = countMessageTokens(summaryMsg.toDict());

    this.conversation.messages = [summaryMsg, ...recentMessages];
    this.conversation.totalTokens = this.conversation.messages.reduce(
      (sum, m) => sum + m.tokenCount,
      0,
    );
  }

  private truncateAllToolResults(): void {
    const newMessages = this.conversation.messages.map((m) => truncateToolResults(m));
    this.conversation.messages = newMessages;
    this.conversation.totalTokens = newMessages.reduce((sum, m) => sum + m.tokenCount, 0);
  }

  private async callLlmSimple(
    messages: Array<{ role: string; content: ContentBlock[] }>,
  ): Promise<string> {
    const parts: string[] = [];
    for await (const event of this.llm.stream({
      system: 'You are a helpful assistant that extracts and summarizes information.',
      messages,
      maxTokens: 2048,
    })) {
      if (event.kind === 'text_delta') parts.push(event.text);
    }
    return parts.join('');
  }
}

function hasToolResult(message: Message): boolean {
  return message.content.some((block) => block.type === 'tool_result');
}

function truncateToolResults(message: Message): Message {
  if (message.role !== 'user') return message;

  let changed = false;
  const newContent: ContentBlock[] = [];
  for (const block of message.content) {
    if (block.type === 'tool_result') {
      const raw = block.content;
      const contentStr = typeof raw === 'string' ? raw : JSON.stringify(raw);
      const tokens = countTokens(contentStr);
      if (tokens > MAX_TOOL_RESULT_TOKENS) {
        const truncated = contentStr.slice(0, 3000);
        newContent.push({
          ...block,
          content: `${truncated}\n\n... [truncated from ${tokens} tokens during compaction]`,
        });
        changed = true;
      } else {
        newContent.push(block);
      }
    } else {
      newContent.push(block);
    }
  }

  if (!changed) return message;

  const newMsg = new Message(message.role, newContent);
  newMsg.tokenCount = countMessageTokens(newMsg.toDict());
  return newMsg;
}

function formatConversation(messages: Message[]): string {
  const parts: string[] = [];
  for (const msg of messages) {
    const role = msg.role.toUpperCase();
    const text = msg.text;
    if (text) {
      parts.push(`[${role}]: ${text}`);
    } else {
      for (const block of msg.content) {
        if (block.type === 'tool_use') {
          parts.push(`[${role}]: Called tool '${block.name}'`);
        } else if (block.type === 'tool_result') {
          const preview = String(block.content ?? '').slice(0, 200);
          parts.push(`[TOOL RESULT]: ${preview}`);
        }
      }
    }
  }
  return parts.join('\n\n');
}
