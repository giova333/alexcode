/** Anthropic Claude LLM provider. */

import Anthropic from '@anthropic-ai/sdk';

import type { AnthropicConfig } from '../config/schema.js';
import type { ThinkingBlock } from '../core/message.js';
import {
  responseComplete,
  textDelta,
  thinkingDelta,
  toolUseEvent,
  type LLMProvider,
  type StreamEvent,
  type StreamParams,
} from './base.js';

// Effort levels accepted by the Anthropic adaptive-thinking output_config.
// "auto" is a sentinel — when selected we omit output_config so the API picks
// its own adaptive level rather than us biasing it.
export const VALID_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max', 'auto'] as const;

// Shortcuts for the /model command — maps aliases to full Anthropic model IDs.
export const MODEL_ALIASES: Record<string, string> = {
  opus: 'claude-opus-4-7',
  sonnet: 'claude-sonnet-4-6',
  haiku: 'claude-haiku-4-5-20251001',
};

export class AnthropicProvider implements LLMProvider {
  model: string;
  private client: Anthropic;

  constructor(config: AnthropicConfig, model: string) {
    this.model = model;
    this.client = new Anthropic(config.api_key ? { apiKey: config.api_key } : {});
  }

  async *stream(params: StreamParams): AsyncIterable<StreamEvent> {
    const { system, messages, tools, maxTokens = 8192, reasoning } = params;

    const kwargs: Record<string, any> = {
      model: this.model,
      max_tokens: maxTokens,
      messages,
    };
    if (system) kwargs.system = system;
    if (tools && tools.length > 0) kwargs.tools = tools;

    // Adaptive thinking. On Opus 4.7+, thinking.display defaults to "omitted"
    // (signature-only); we ask for summarized text whenever thinking is surfaced.
    if (reasoning && reasoning.enabled) {
      const display = reasoning.show_thinking ? 'summarized' : 'omitted';
      kwargs.thinking = { type: 'adaptive', display };
      const effort = (VALID_EFFORTS as readonly string[]).includes(reasoning.effort)
        ? reasoning.effort
        : 'high';
      if (effort !== 'auto') {
        kwargs.output_config = { effort };
      }
    }

    const stream = this.client.messages.stream(kwargs as any);

    let currentBlockType = '';
    let currentToolId = '';
    let currentToolName = '';
    let toolInputJson = '';

    for await (const event of stream) {
      if (event.type === 'content_block_start') {
        const block = event.content_block;
        if (block.type === 'tool_use') {
          currentBlockType = 'tool_use';
          currentToolId = block.id;
          currentToolName = block.name;
          toolInputJson = '';
        } else if (block.type === 'thinking') {
          currentBlockType = 'thinking';
        } else if (block.type === 'text') {
          currentBlockType = 'text';
        }
      } else if (event.type === 'content_block_delta') {
        const delta = event.delta as any;
        if (delta.type === 'text_delta') {
          yield textDelta(delta.text);
        } else if (delta.type === 'thinking_delta') {
          yield thinkingDelta(delta.thinking);
        } else if (delta.type === 'input_json_delta') {
          toolInputJson += delta.partial_json;
        }
      } else if (event.type === 'content_block_stop') {
        if (currentBlockType === 'tool_use' && currentToolName) {
          let input: Record<string, any> = {};
          if (toolInputJson) {
            try {
              input = JSON.parse(toolInputJson);
            } catch {
              input = {};
            }
          }
          yield toolUseEvent(currentToolId, currentToolName, input);
        }
        currentBlockType = '';
        currentToolId = '';
        currentToolName = '';
        toolInputJson = '';
      }
    }

    // Final message for usage and thinking blocks (with signatures).
    const final = await stream.finalMessage();
    const thinkingBlocks: ThinkingBlock[] = [];
    for (const block of final.content) {
      if (block.type === 'thinking') {
        thinkingBlocks.push({
          type: 'thinking',
          thinking: block.thinking,
          signature: block.signature,
        });
      }
    }
    yield responseComplete(
      {
        input_tokens: final.usage.input_tokens,
        output_tokens: final.usage.output_tokens,
      },
      final.stop_reason ?? '',
      thinkingBlocks,
    );
  }
}
