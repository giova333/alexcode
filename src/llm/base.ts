/** LLM provider interface and stream event types. */

import type { ReasoningConfig } from '../config/schema.js';
import type { ApiMessage, ThinkingBlock } from '../core/message.js';

export interface TextDelta {
  kind: 'text_delta';
  text: string;
}

export interface ThinkingDelta {
  kind: 'thinking_delta';
  text: string;
}

export interface ToolUseEvent {
  kind: 'tool_use';
  id: string;
  name: string;
  input: Record<string, any>;
}

export interface UsageInfo {
  input_tokens: number;
  output_tokens: number;
}

export interface ResponseComplete {
  kind: 'response_complete';
  usage: UsageInfo;
  stop_reason: string;
  thinking_blocks: ThinkingBlock[];
}

export type StreamEvent = TextDelta | ThinkingDelta | ToolUseEvent | ResponseComplete;

export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, any>;
}

export interface StreamParams {
  system: string;
  messages: ApiMessage[];
  tools?: ToolDefinition[] | null;
  maxTokens?: number;
  reasoning?: ReasoningConfig | null;
}

export interface LLMProvider {
  model: string;
  stream(params: StreamParams): AsyncIterable<StreamEvent>;
}

// Convenience constructors keeping call sites terse.
export const textDelta = (text: string): TextDelta => ({ kind: 'text_delta', text });
export const thinkingDelta = (text: string): ThinkingDelta => ({ kind: 'thinking_delta', text });
export const toolUseEvent = (
  id: string,
  name: string,
  input: Record<string, any>,
): ToolUseEvent => ({
  kind: 'tool_use',
  id,
  name,
  input,
});
export const responseComplete = (
  usage: UsageInfo,
  stopReason: string,
  thinkingBlocks: ThinkingBlock[] = [],
): ResponseComplete => ({
  kind: 'response_complete',
  usage,
  stop_reason: stopReason,
  thinking_blocks: thinkingBlocks,
});
