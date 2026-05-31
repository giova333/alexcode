/** Lightweight agent loop for subagent task execution. */

import type { CLI } from '../cli/types.js';
import { Compactor } from '../compaction/compactor.js';
import type { Config } from '../config/schema.js';
import { Conversation } from '../core/conversation.js';
import { Message, type ContentBlock } from '../core/message.js';
import { countMessageTokens } from '../core/tokens.js';
import type { LLMProvider, ResponseComplete, ToolUseEvent } from '../llm/base.js';
import type { ToolExecutor } from '../tools/executor.js';
import type { ToolRegistry } from '../tools/registry.js';

const MAX_ITERATIONS = 50;

/**
 * Runs a single task to completion using an ephemeral conversation.
 *
 * A stripped-down version of AgentLoop's cycle with no history persistence,
 * no plan mode, and no memory writes. When `cli` is provided, streaming output
 * is displayed in the terminal in real time.
 */
export class SubagentRunner {
  private conversation = new Conversation();
  private compactor: Compactor;

  constructor(
    private llm: LLMProvider,
    private toolRegistry: ToolRegistry,
    private toolExecutor: ToolExecutor,
    private config: Config,
    private systemPrompt: string,
    private cli: CLI | null = null,
  ) {
    this.compactor = new Compactor(config.compaction, llm, this.conversation);
  }

  async run(task: string): Promise<string> {
    const userMsg = Message.user(task);
    userMsg.tokenCount = countMessageTokens(userMsg.toDict());
    this.conversation.append(userMsg);
    return this.runLlmCycle();
  }

  private async runLlmCycle(): Promise<string> {
    const tools = this.toolRegistry.allDefinitions();

    for (let iteration = 0; iteration < MAX_ITERATIONS; iteration++) {
      const textParts: string[] = [];
      const toolUses: ToolUseEvent[] = [];
      let usageInfo: ResponseComplete | null = null;
      let isThinking = false;

      const reasoningCfg = this.config.reasoning.enabled ? this.config.reasoning : null;

      this.cli?.startResponse();

      for await (const event of this.llm.stream({
        system: this.systemPrompt,
        messages: this.conversation.toApiMessages(),
        tools: tools.length > 0 ? tools : null,
        maxTokens: this.config.max_tokens,
        reasoning: reasoningCfg,
      })) {
        if (event.kind === 'thinking_delta') {
          if (this.cli) {
            if (!isThinking) {
              isThinking = true;
              this.cli.startThinking();
            }
            if (this.config.reasoning.show_thinking) this.cli.printThinkingDelta(event.text);
          }
        } else if (event.kind === 'text_delta') {
          if (this.cli && isThinking) {
            isThinking = false;
            this.cli.endThinking();
          }
          textParts.push(event.text);
          this.cli?.printTextDelta(event.text);
        } else if (event.kind === 'tool_use') {
          if (this.cli && isThinking) {
            isThinking = false;
            this.cli.endThinking();
          }
          toolUses.push(event);
        } else if (event.kind === 'response_complete') {
          if (this.cli && isThinking) {
            isThinking = false;
            this.cli.endThinking();
          }
          usageInfo = event;
        }
      }

      this.cli?.endResponse();

      const contentBlocks: ContentBlock[] = [];
      if (usageInfo && usageInfo.thinking_blocks.length > 0) {
        contentBlocks.push(...usageInfo.thinking_blocks);
      }
      const fullText = textParts.join('');
      if (fullText) contentBlocks.push({ type: 'text', text: fullText });
      for (const tu of toolUses) {
        contentBlocks.push({ type: 'tool_use', id: tu.id, name: tu.name, input: tu.input });
      }

      if (contentBlocks.length > 0) {
        const assistantMsg = new Message('assistant', contentBlocks);
        assistantMsg.tokenCount = countMessageTokens(assistantMsg.toDict());
        this.conversation.append(assistantMsg);
      }

      if (usageInfo) {
        this.conversation.totalTokens = usageInfo.usage.input_tokens;
        this.cli?.printUsage(usageInfo.usage.input_tokens, usageInfo.usage.output_tokens);
      }

      if (toolUses.length === 0) {
        return fullText;
      }

      const toolResultBlocks: ContentBlock[] = [];
      for (const tu of toolUses) {
        let resultText: string;
        let isError: boolean;
        try {
          this.cli?.printToolUse(tu.name, tu.input);
          resultText = await this.toolExecutor.execute(tu.name, tu.input);
          isError = false;
          this.cli?.printToolResult(tu.name, resultText, isError);
        } catch (e: any) {
          resultText = `Error executing ${tu.name}: ${e?.message ?? e}`;
          isError = true;
          this.cli?.printToolResult(tu.name, resultText, isError);
        }
        toolResultBlocks.push({
          type: 'tool_result',
          tool_use_id: tu.id,
          content: resultText,
          is_error: isError,
        });
      }

      const resultMsg = new Message('user', toolResultBlocks);
      resultMsg.tokenCount = countMessageTokens(resultMsg.toDict());
      this.conversation.append(resultMsg);

      await this.compactor.maybeCompact();
    }

    return 'Subagent reached maximum iterations without completing the task.';
  }
}
