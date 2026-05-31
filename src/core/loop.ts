/** Main agent loop: user -> LLM -> tools -> LLM -> ... -> text response. */

import fs from 'node:fs';
import path from 'node:path';

import type { CLI } from '../cli/types.js';
import { Compactor } from '../compaction/compactor.js';
import type { Config } from '../config/schema.js';
import { MODEL_ALIASES, VALID_EFFORTS } from '../llm/anthropic.js';
import type { LLMProvider, ResponseComplete, ToolDefinition, ToolUseEvent } from '../llm/base.js';
import type { MemoryManager } from '../memory/manager.js';
import { fillPlaceholders, loadSystemPrompt } from '../prompts.js';
import type { SkillLoader } from '../skills/loader.js';
import type { Skill } from '../skills/skill.js';
import type { PlanTool } from '../tools/builtin/plan.js';
import type { ToolExecutor } from '../tools/executor.js';
import type { ToolRegistry } from '../tools/registry.js';
import type { HistoryStorage } from '../history/storage.js';
import { Conversation } from './conversation.js';
import { Message, type ContentBlock } from './message.js';
import { countMessageTokens } from './tokens.js';

export interface AgentLoopOptions {
  config: Config;
  llm: LLMProvider;
  cli: CLI;
  projectDir: string;
  toolRegistry?: ToolRegistry | null;
  toolExecutor?: ToolExecutor | null;
  memoryManager?: MemoryManager | null;
  history?: HistoryStorage | null;
  skillLoader?: SkillLoader | null;
  skills?: Skill[] | null;
  planTool?: PlanTool | null;
}

const PLAN_MODE_BLOCK = `
# Plan Mode
You are in plan mode. Do NOT make any edits, run destructive commands, or modify files.
Only explore the codebase (read files, search, grep) and produce a plan.
Use the \`plan\` tool to create or update plans. Once planning is complete, tell the user to run /plan again to exit plan mode.`;

export class AgentLoop {
  private config: Config;
  private llm: LLMProvider;
  private cli: CLI;
  private projectDir: string;
  private conversation = new Conversation();
  private toolRegistry: ToolRegistry | null;
  private toolExecutor: ToolExecutor | null;
  private memoryManager: MemoryManager | null;
  private history: HistoryStorage | null;
  private sessionId: string;
  private skillLoader: SkillLoader | null;
  private skills: Skill[];
  private planTool: PlanTool | null;
  private planMode = false;
  private compactor: Compactor;
  private shouldExit = false;

  constructor(opts: AgentLoopOptions) {
    this.config = opts.config;
    this.llm = opts.llm;
    this.cli = opts.cli;
    this.projectDir = opts.projectDir;
    this.toolRegistry = opts.toolRegistry ?? null;
    this.toolExecutor = opts.toolExecutor ?? null;
    this.memoryManager = opts.memoryManager ?? null;
    this.history = opts.history ?? null;
    this.sessionId = this.history ? this.history.newSessionId() : '';
    this.skillLoader = opts.skillLoader ?? null;
    this.skills = opts.skills ?? [];
    this.planTool = opts.planTool ?? null;
    this.setupPlanFile();
    this.compactor = new Compactor(this.config.compaction, this.llm, this.conversation);
  }

  get conversationState(): Conversation {
    return this.conversation;
  }

  private planFileForSession(): string {
    return path.join(this.projectDir, '.agent', 'plans', `${this.sessionId}.md`);
  }

  private setupPlanFile(): void {
    if (this.planTool) this.planTool.setPlanFile(this.planFileForSession());
  }

  resumeSession(sessionId: string): boolean {
    if (!this.history) return false;
    const messages = this.history.load(sessionId);
    if (!messages || messages.length === 0) return false;
    this.conversation.loadMessages(messages);
    this.sessionId = sessionId;
    this.setupPlanFile();
    return true;
  }

  async run(): Promise<void> {
    this.cli.printWelcome(this.config.provider, this.config.model);

    const invocable = this.skills.filter((s) => s.userInvocable);
    if (invocable.length > 0) {
      this.cli.printInfo(`Skills: ${invocable.map((s) => '/' + s.name).join(', ')}`);
    }

    while (true) {
      const userInput = await this.cli.getInput();
      if (userInput === null) {
        this.saveHistory();
        this.cli.printInfo('Goodbye!');
        break;
      }

      if (userInput.startsWith('/')) {
        try {
          const handled = await this.handleCommand(userInput);
          if (this.shouldExit) {
            this.saveHistory();
            break;
          }
          if (handled) continue;
        } catch (e: any) {
          this.cli.printError(`Error: ${e?.message ?? e}`);
          continue;
        }
      }

      try {
        await this.processMessage(userInput);
      } catch (e: any) {
        this.cli.printError(`Error: ${e?.message ?? e}`);
        this.saveHistory();
      }
    }
  }

  private async handleCommand(command: string): Promise<boolean> {
    const trimmed = command.trim();
    const spaceIdx = trimmed.indexOf(' ');
    const cmd = (spaceIdx === -1 ? trimmed : trimmed.slice(0, spaceIdx)).toLowerCase();
    const arg = spaceIdx === -1 ? '' : trimmed.slice(spaceIdx + 1).trim();

    if (cmd === '/exit' || cmd === '/quit') {
      this.shouldExit = true;
      return true;
    } else if (cmd === '/clear') {
      this.conversation.clear();
      if (this.history) this.history.clearSession(this.sessionId);
      this.cli.printInfo('Conversation cleared.');
      return true;
    } else if (cmd === '/history') {
      for (const msg of this.conversation.messages) {
        const text = msg.text ? msg.text.slice(0, 100) : '(tool interaction)';
        this.cli.printInfo(`  [${msg.role}] ${text}`);
      }
      return true;
    } else if (cmd === '/tokens') {
      this.cli.printInfo(`Total tokens: ${this.conversation.totalTokens.toLocaleString('en-US')}`);
      return true;
    } else if (cmd === '/tools') {
      for (const d of this.getToolDefinitions()) {
        this.cli.printInfo(`  ${d.name}`);
      }
      return true;
    } else if (cmd === '/sessions') {
      if (this.history) {
        for (const s of this.history.listSessions()) {
          this.cli.printInfo(`  ${s.session_id} (${s.message_count} messages) — ${s.timestamp}`);
        }
      }
      return true;
    } else if (cmd === '/resume') {
      return this.handleResume(arg);
    } else if (cmd === '/compact') {
      const compacted = await this.compactor.maybeCompact(true);
      if (compacted) {
        this.cli.printCompactionNotice();
        if (this.history) this.history.rewrite(this.sessionId, this.conversation.messages);
        this.cli.printInfo(
          `Compacted. Tokens: ${this.conversation.totalTokens.toLocaleString('en-US')}`,
        );
      } else {
        this.cli.printInfo(
          `No compaction needed. Tokens: ${this.conversation.totalTokens.toLocaleString('en-US')}`,
        );
      }
      return true;
    } else if (cmd === '/skills') {
      this.handleSkillsList();
      return true;
    } else if (cmd === '/model') {
      this.handleModel(arg);
      return true;
    } else if (cmd === '/prompt') {
      const system = await this.buildSystemPrompt();
      this.cli.printAssistantText('```\n' + system + '\n```');
      return true;
    } else if (cmd === '/plan') {
      this.planMode = !this.planMode;
      this.cli.printInfo(`Plan mode ${this.planMode ? 'enabled' : 'disabled'}.`);
      return true;
    } else if (cmd === '/effort') {
      this.handleEffort(arg);
      return true;
    } else if (cmd === '/help') {
      this.cli.printInfo(
        'Commands: /exit /clear /history /tokens /tools /sessions /resume [id] /compact /skills /model /effort /plan /prompt /help',
      );
      if (invocableSkills(this.skills).length > 0) {
        this.cli.printInfo(
          `Skills: ${invocableSkills(this.skills)
            .map((s) => '/' + s.name)
            .join(', ')}`,
        );
      }
      return true;
    } else {
      const skillName = cmd.slice(1);
      if (this.skillLoader) {
        const skill = this.skillLoader.getByName(skillName, this.skills);
        if (skill && skill.userInvocable) {
          await this.invokeSkill(skill, arg);
          return true;
        }
      }
    }
    return false;
  }

  private handleResume(arg: string): boolean {
    if (!this.history) {
      this.cli.printError('History storage not configured.');
      return true;
    }
    const sessionId = arg ? this.history.findSession(arg) : this.history.getLatestSessionId();
    if (!sessionId) {
      this.cli.printError(arg ? 'Session not found.' : 'No previous sessions.');
      return true;
    }
    this.saveHistory();
    if (this.resumeSession(sessionId)) {
      const msgCount = this.conversation.messages.length;
      this.cli.printInfo(
        `Resumed session: ${sessionId} (${msgCount} messages, ${this.conversation.totalTokens.toLocaleString('en-US')} tokens)`,
      );
      const recent = this.conversation.messages.filter((m) => m.text).slice(-3);
      for (const m of recent) {
        const preview = m.text.length > 120 ? m.text.slice(0, 120) + '...' : m.text;
        this.cli.printInfo(`  [${m.role}] ${preview}`);
      }
    } else {
      this.cli.printError(`Failed to load session: ${sessionId}`);
    }
    return true;
  }

  private handleSkillsList(): void {
    const invocable = this.skills.filter((s) => s.userInvocable);
    const modelOnly = this.skills.filter((s) => !s.userInvocable && !s.disableModelInvocation);
    if (invocable.length > 0) {
      this.cli.printInfo('  User-invocable skills:');
      for (const s of invocable) {
        const hint = s.argumentHint ? ` ${s.argumentHint}` : '';
        this.cli.printInfo(`    /${s.name}${hint} — ${s.description}`);
      }
    }
    if (modelOnly.length > 0) {
      this.cli.printInfo('  Background skills (auto-activated by LLM):');
      for (const s of modelOnly) {
        this.cli.printInfo(`    ${s.name} — ${s.description}`);
      }
    }
    if (invocable.length === 0 && modelOnly.length === 0) {
      this.cli.printInfo('  No skills loaded.');
    }
  }

  private handleModel(arg: string): void {
    if (!arg) {
      this.cli.printInfo(`Current model: ${this.config.model}`);
      this.cli.printInfo('Usage: /model <name>');
      this.cli.printInfo(`Shortcuts: ${Object.keys(MODEL_ALIASES).join(', ')}`);
      return;
    }
    const newModel = MODEL_ALIASES[arg.toLowerCase()] ?? arg;
    this.config.model = newModel;
    this.llm.model = newModel;
    this.cli.printInfo(`Switched to model: ${newModel}`);
  }

  private handleEffort(arg: string): void {
    if (!arg) {
      this.cli.printInfo(`Current effort: ${this.config.reasoning.effort}`);
      this.cli.printInfo(`Usage: /effort <${VALID_EFFORTS.join('|')}>`);
      return;
    }
    const newEffort = arg.toLowerCase();
    if (!(VALID_EFFORTS as readonly string[]).includes(newEffort)) {
      this.cli.printError(`Invalid effort '${arg}'. Choose one of: ${VALID_EFFORTS.join(', ')}`);
      return;
    }
    this.config.reasoning.effort = newEffort;
    this.cli.printInfo(`Reasoning effort set to: ${newEffort}`);
  }

  private async invokeSkill(skill: Skill, args: string): Promise<void> {
    const rendered = skill.render(args);
    if (!rendered) {
      this.cli.printError(`Skill '${skill.name}' has no instructions.`);
      return;
    }
    this.cli.printInfo(`Running skill: ${skill.name}`);
    await this.processMessage(rendered);
  }

  private expandFileReferences(text: string): string {
    const pattern = /(?:^|(?<=\s))@(\S+)/g;
    const matches = [...text.matchAll(pattern)];
    if (matches.length === 0) return text;

    const attachments: string[] = [];
    for (const match of matches) {
      const ref = match[1]!;
      const fullPath = path.join(this.projectDir, ref);
      try {
        const stat = fs.statSync(fullPath);
        if (stat.isFile()) {
          let content = fs.readFileSync(fullPath, 'utf-8');
          if (content.length > 50_000) content = content.slice(0, 50_000) + '\n... (truncated)';
          attachments.push(`<file path="${ref}">\n${content}\n</file>`);
        } else if (stat.isDirectory()) {
          const entries = fs.readdirSync(fullPath).sort();
          const listing = entries
            .filter((e) => !e.startsWith('.'))
            .map((e) => {
              const isDir = fs.statSync(path.join(fullPath, e)).isDirectory();
              return `  ${isDir ? '[dir] ' : ''}${e}`;
            })
            .join('\n');
          attachments.push(`<directory path="${ref}">\n${listing}\n</directory>`);
        }
      } catch {
        continue;
      }
    }

    if (attachments.length > 0) {
      return text + '\n\n' + attachments.join('\n\n');
    }
    return text;
  }

  private async maybeCompact(): Promise<void> {
    if (await this.compactor.maybeCompact()) {
      this.cli.printCompactionNotice();
      if (this.history) this.history.rewrite(this.sessionId, this.conversation.messages);
    }
  }

  async processMessage(userInput: string): Promise<void> {
    const expanded = this.expandFileReferences(userInput);
    const userMsg = Message.user(expanded);
    userMsg.tokenCount = countMessageTokens(userMsg.toDict());
    this.conversation.append(userMsg);

    await this.maybeCompact();

    const assistantMsgs = await this.runLlmCycle();
    if (this.memoryManager) this.memoryManager.ingestTurn(userMsg, assistantMsgs);
    this.saveHistory();
  }

  private async runLlmCycle(): Promise<Message[]> {
    const assistantMsgs: Message[] = [];
    while (true) {
      const system = await this.buildSystemPrompt();
      const tools = this.getToolDefinitions();

      const textParts: string[] = [];
      const toolUses: ToolUseEvent[] = [];
      let usageInfo: ResponseComplete | null = null;
      let isThinking = false;

      const reasoningCfg = this.config.reasoning.enabled ? this.config.reasoning : null;

      this.cli.startResponse();

      for await (const event of this.llm.stream({
        system,
        messages: this.conversation.toApiMessages(),
        tools: tools.length > 0 ? tools : null,
        maxTokens: this.config.max_tokens,
        reasoning: reasoningCfg,
      })) {
        if (event.kind === 'thinking_delta') {
          if (!isThinking) {
            isThinking = true;
            this.cli.startThinking();
          }
          if (this.config.reasoning.show_thinking) this.cli.printThinkingDelta(event.text);
        } else if (event.kind === 'text_delta') {
          if (isThinking) {
            isThinking = false;
            this.cli.endThinking();
          }
          textParts.push(event.text);
          this.cli.printTextDelta(event.text);
        } else if (event.kind === 'tool_use') {
          if (isThinking) {
            isThinking = false;
            this.cli.endThinking();
          }
          toolUses.push(event);
        } else if (event.kind === 'response_complete') {
          if (isThinking) {
            isThinking = false;
            this.cli.endThinking();
          }
          usageInfo = event;
        }
      }

      this.cli.endResponse();

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
        assistantMsgs.push(assistantMsg);
      }

      if (usageInfo) {
        this.cli.printUsage(usageInfo.usage.input_tokens, usageInfo.usage.output_tokens);
        // Sync to the API's input_tokens, which reflects the true context size.
        this.conversation.totalTokens = usageInfo.usage.input_tokens;
      }

      if (toolUses.length === 0) {
        return assistantMsgs;
      }

      const toolResultBlocks: ContentBlock[] = [];
      for (const tu of toolUses) {
        let resultText: string;
        let isError: boolean;
        try {
          this.cli.printToolUse(tu.name, tu.input);
          [resultText, isError] = await this.executeTool(tu.name, tu.input);
          this.cli.printToolResult(tu.name, resultText, isError);
        } catch (e: any) {
          resultText = `Internal error during tool execution: ${e?.message ?? e}`;
          isError = true;
          this.cli.printToolResult(tu.name, resultText, isError);
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

      await this.maybeCompact();
    }
  }

  private async executeTool(name: string, input: Record<string, any>): Promise<[string, boolean]> {
    if (this.toolExecutor === null) {
      return [`Tool '${name}' not available (no tools registered).`, true];
    }
    try {
      const result = await this.toolExecutor.execute(name, input);
      return [result, false];
    } catch (e: any) {
      return [`Error executing ${name}: ${e?.message ?? e}`, true];
    }
  }

  private loadAgentsMd(): string {
    const parts: string[] = [];
    for (const candidate of [
      path.join(this.projectDir, '.agent', 'AGENTS.md'),
      path.join(this.projectDir, 'AGENTS.md'),
    ]) {
      if (fs.existsSync(candidate)) {
        const content = fs.readFileSync(candidate, 'utf-8').trim();
        if (content) parts.push(content);
      }
    }
    return parts.join('\n\n');
  }

  private async buildSystemPrompt(): Promise<string> {
    const system = fillPlaceholders(loadSystemPrompt());
    const parts = [system];

    const agentsMd = this.loadAgentsMd();
    if (agentsMd) {
      parts.push(`\n# Project Instructions (AGENTS.md)\n${agentsMd}`);
    }

    if (this.memoryManager) {
      try {
        const memoryContext = await this.memoryManager.loadContext();
        if (memoryContext) parts.push(`\n# Memory\n${memoryContext}`);
      } catch {
        /* ignore */
      }
    }

    if (this.skillLoader) {
      const modelSkills = this.skillLoader.getModelAvailable(this.skills);
      if (modelSkills.length > 0) {
        parts.push('\n# Available Skills');
        parts.push(
          'The following skills can be suggested to the user via slash commands (e.g., /skill-name).',
        );
        for (const skill of modelSkills) {
          const desc = skill.description ? `: ${skill.description}` : '';
          parts.push(`- ${skill.name}${desc}`);
        }
      }
    }

    if (this.planMode) {
      parts.push(PLAN_MODE_BLOCK);
    }

    return parts.join('\n');
  }

  private getToolDefinitions(): ToolDefinition[] {
    if (this.toolRegistry === null) return [];
    return this.toolRegistry.allDefinitions();
  }

  private saveHistory(): void {
    if (this.history && this.conversation.messages.length > 0) {
      this.history.save(this.sessionId, this.conversation.messages);
    }
  }
}

function invocableSkills(skills: Skill[]): Skill[] {
  return skills.filter((s) => s.userInvocable);
}
