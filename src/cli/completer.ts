/** Completer for @ file references and / commands (Node readline style). */

import fs from 'node:fs';
import path from 'node:path';

export const BUILTIN_COMMANDS: Record<string, string> = {
  '/exit': 'Exit the agent',
  '/quit': 'Exit the agent',
  '/clear': 'Clear conversation',
  '/history': 'Show message history',
  '/tokens': 'Show token count',
  '/tools': 'List available tools',
  '/sessions': 'List saved sessions',
  '/resume': 'Resume a previous session',
  '/compact': 'Compact conversation',
  '/skills': 'List available skills',
  '/model': 'Switch LLM model',
  '/effort': 'Set reasoning effort (low|medium|high|xhigh|max|auto)',
  '/prompt': 'Show system prompt',
  '/help': 'Show available commands',
  '/plan': 'Toggle plan mode',
};

export class AgentCompleter {
  private workingDir: string;
  private skillCommands: Record<string, string> = {};

  constructor(workingDir?: string) {
    this.workingDir = workingDir ?? process.cwd();
  }

  setSkills(skills: Array<[string, string]>): void {
    this.skillCommands = {};
    for (const [name, desc] of skills) {
      this.skillCommands[`/${name}`] = desc;
    }
  }

  /** Node readline completer: returns [completions, originalToken]. */
  complete(line: string): [string[], string] {
    if (line.startsWith('/')) {
      const all = { ...BUILTIN_COMMANDS, ...this.skillCommands };
      const hits = Object.keys(all)
        .filter((c) => c.startsWith(line.toLowerCase()))
        .sort();
      return [hits.length > 0 ? hits : Object.keys(all).sort(), line];
    }

    const atIdx = line.lastIndexOf('@');
    if (atIdx !== -1 && (atIdx === 0 || line[atIdx - 1] === ' ' || line[atIdx - 1] === '\t')) {
      const partial = line.slice(atIdx + 1);
      const completions = this.completePaths(partial).map((c) => line.slice(0, atIdx + 1) + c);
      return [completions, line];
    }

    return [[], line];
  }

  private completePaths(partial: string): string[] {
    try {
      let dirname: string;
      let basename: string;
      let searchDir: string;
      if (partial.includes('/') || partial.includes(path.sep)) {
        dirname = path.dirname(partial);
        basename = path.basename(partial);
        searchDir = path.join(this.workingDir, dirname);
      } else {
        dirname = '';
        basename = partial;
        searchDir = this.workingDir;
      }

      if (!fs.statSync(searchDir).isDirectory()) return [];

      let entries = fs.readdirSync(searchDir);
      const showHidden = basename.startsWith('.');
      if (!showHidden) entries = entries.filter((e) => !e.startsWith('.'));

      const out: string[] = [];
      for (const name of entries) {
        if (!name.toLowerCase().startsWith(basename.toLowerCase())) continue;
        const isDir = fs.statSync(path.join(searchDir, name)).isDirectory();
        let relPath = dirname ? path.join(dirname, name) : name;
        if (isDir) relPath += '/';
        out.push(relPath);
      }
      return out.sort();
    } catch {
      return [];
    }
  }
}
