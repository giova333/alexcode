/** Terminal UI: input via readline, output via chalk + marked-terminal. */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import chalk from 'chalk';
import { marked } from 'marked';
import { markedTerminal } from 'marked-terminal';

import { AgentCompleter } from './completer.js';
import type { CLI as CLIInterface } from './types.js';

marked.use(markedTerminal() as any);

const HISTORY_PATH = path.join(os.homedir(), '.config', 'agent', 'input_history');
const MAX_HISTORY = 1000;

export class CLI implements CLIInterface {
  private completer: AgentCompleter;
  private rl: readline.Interface | null = null;
  private closed = false;
  private historyEntries: string[];

  constructor(workingDir?: string) {
    this.completer = new AgentCompleter(workingDir);
    this.historyEntries = loadHistory();
  }

  // Readline binds to stdin and keeps the event loop alive, so it's created
  // lazily — non-interactive modes (e.g. `-p`) never touch stdin.
  private ensureReadline(): readline.Interface {
    if (this.rl) return this.rl;
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: true,
      completer: (line: string) => this.completer.complete(line),
      historySize: MAX_HISTORY,
    });
    // Seed readline's in-memory history (most-recent-first).
    (rl as any).history = [...this.historyEntries].reverse();
    rl.on('close', () => {
      this.closed = true;
    });
    this.rl = rl;
    return rl;
  }

  setSkills(skills: Array<[string, string]>): void {
    this.completer.setSkills(skills);
  }

  printWelcome(provider: string, model: string): void {
    const kitten = chalk.cyan(
      ['    /\\_/\\  ', '   ( o.o ) ', '    > ^ <  ', '   /|   |\\ ', '  (_|   |_)'].join('\n'),
    );
    const info =
      chalk.bold.white('alexcode') +
      chalk.dim(` — ${provider}/${model}`) +
      '\n\n' +
      chalk.dim(
        'Type your message and press Enter. Use \\ for multiline.\n' +
          'Commands: /exit, /clear, /history, /model\n' +
          'Use @ for file references, / for commands. Tab to select.',
      );
    process.stdout.write('\n' + kitten + '\n' + info + '\n\n');
  }

  private question(prompt: string): Promise<string | null> {
    return new Promise((resolve) => {
      if (this.closed) {
        resolve(null);
        return;
      }
      this.ensureReadline().question(prompt, (answer) => resolve(answer));
    });
  }

  async getInput(): Promise<string | null> {
    const lines: string[] = [];
    while (true) {
      const prompt = lines.length === 0 ? '>>> ' : '... ';
      const line = await this.question(prompt);
      if (line === null) return null;
      if (line.endsWith('\\')) {
        lines.push(line.slice(0, -1));
        continue;
      }
      lines.push(line);
      break;
    }
    const result = lines.join('\n').trim();
    if (result) this.recordHistory(result);
    return result || null;
  }

  private recordHistory(entry: string): void {
    this.historyEntries.push(entry);
    if (this.historyEntries.length > MAX_HISTORY) {
      this.historyEntries = this.historyEntries.slice(-MAX_HISTORY);
    }
    try {
      fs.mkdirSync(path.dirname(HISTORY_PATH), { recursive: true });
      fs.appendFileSync(HISTORY_PATH, entry.replace(/\n/g, ' ') + '\n');
    } catch {
      /* ignore */
    }
  }

  printAssistantText(text: string): void {
    process.stdout.write('\n' + String(marked.parse(text)).trimEnd() + '\n\n');
  }

  printTextDelta(text: string): void {
    process.stdout.write(text);
  }

  printThinkingDelta(text: string): void {
    process.stdout.write(chalk.dim.italic(text));
  }

  startThinking(): void {
    process.stdout.write(chalk.dim.italic('  Thinking...') + '\n');
  }

  endThinking(): void {
    process.stdout.write('\n');
  }

  startResponse(): void {
    process.stdout.write('\n');
  }

  endResponse(): void {
    process.stdout.write('\n\n');
  }

  printToolUse(name: string, _input: Record<string, any>): void {
    process.stdout.write(chalk.bold.yellow(`  ⚡ ${name}`) + '\n');
  }

  printToolResult(_name: string, result: string, isError: boolean): void {
    const preview = result.length > 200 ? result.slice(0, 200) + '...' : result;
    const styled = isError ? chalk.red(`  ← ${preview}`) : chalk.dim(`  ← ${preview}`);
    process.stdout.write(styled + '\n');
  }

  printQuestion(question: string): void {
    process.stdout.write('\n' + chalk.bold.cyan(`? ${question}`) + '\n');
  }

  printError(message: string): void {
    process.stdout.write(chalk.bold.red('Error:') + ` ${message}\n`);
  }

  printInfo(message: string): void {
    process.stdout.write(chalk.dim(message) + '\n');
  }

  printCompactionNotice(): void {
    process.stdout.write(chalk.dim('📦 Compacting conversation...') + '\n');
  }

  printUsage(inputTokens: number, outputTokens: number): void {
    const total = inputTokens + outputTokens;
    const fmt = (n: number) => n.toLocaleString('en-US');
    process.stdout.write(
      chalk.dim(`tokens: ${fmt(inputTokens)} in / ${fmt(outputTokens)} out / ${fmt(total)} total`) +
        '\n',
    );
  }

  close(): void {
    this.rl?.close();
  }
}

function loadHistory(): string[] {
  try {
    const text = fs.readFileSync(HISTORY_PATH, 'utf-8');
    return text
      .split('\n')
      .filter((l) => l.length > 0)
      .slice(-MAX_HISTORY);
  } catch {
    return [];
  }
}
