#!/usr/bin/env node
/** Entry point for the alexcode CLI. */

import { Command } from 'commander';

import { runApp } from './bootstrap.js';

function main(): void {
  const program = new Command();
  program
    .name('alexcode')
    .description('AI coding agent with tool use, memory, and MCP support')
    .option('--model <name>', 'Override the configured model')
    .option(
      '--resume [session]',
      'Resume a previous session (optionally provide a session ID or prefix)',
    )
    .action(async (opts: { model?: string; resume?: string | boolean }) => {
      const resume =
        opts.resume === true
          ? '__latest__'
          : typeof opts.resume === 'string'
            ? opts.resume
            : undefined;
      await runApp({ model: opts.model, resume });
    });

  program.parseAsync(process.argv).catch((err) => {
    console.error(err);
    process.exitCode = 1;
  });
}

main();
