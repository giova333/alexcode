/** Message data structures for the conversation. */

export interface TextBlock {
  type: 'text';
  text: string;
}

export interface ToolUseBlock {
  type: 'tool_use';
  id: string;
  name: string;
  input: Record<string, any>;
}

export interface ToolResultBlock {
  type: 'tool_result';
  tool_use_id: string;
  content: string;
  is_error: boolean;
}

export interface ThinkingBlock {
  type: 'thinking';
  thinking: string;
  signature: string;
}

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock;

export type Role = 'user' | 'assistant';

export interface ApiMessage {
  role: string;
  content: ContentBlock[];
}

/**
 * A single message in the conversation.
 *
 * Content follows Anthropic's content block format.
 */
export class Message {
  role: string;
  content: ContentBlock[];
  tokenCount: number;

  constructor(role: string, content: ContentBlock[] = [], tokenCount = 0) {
    this.role = role;
    this.content = content;
    this.tokenCount = tokenCount;
  }

  static user(text: string): Message {
    return new Message('user', [{ type: 'text', text }]);
  }

  static assistant(text: string): Message {
    return new Message('assistant', [{ type: 'text', text }]);
  }

  static toolResult(toolUseId: string, content: string, isError = false): Message {
    return new Message('user', [
      { type: 'tool_result', tool_use_id: toolUseId, content, is_error: isError },
    ]);
  }

  /** Concatenated text from all text content blocks. */
  get text(): string {
    const parts: string[] = [];
    for (const block of this.content) {
      if (block.type === 'text') parts.push(block.text);
    }
    return parts.join('');
  }

  toDict(): ApiMessage {
    return { role: this.role, content: this.content };
  }
}
