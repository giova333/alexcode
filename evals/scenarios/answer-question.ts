/** Eval: the agent inspects a small repo and answers a factual question. */

import fs from 'node:fs';
import path from 'node:path';

import type { EvalScenario } from '../harness.js';

const PROJECT_NAME = 'widget-factory-9000';

export const answerQuestion: EvalScenario = {
  name: 'answer-question',
  description: 'Agent reads files to answer a factual question about the repo.',
  setup: (workspace) => {
    fs.writeFileSync(
      path.join(workspace, 'package.json'),
      JSON.stringify({ name: PROJECT_NAME, version: '1.2.3', private: true }, null, 2),
    );
    fs.mkdirSync(path.join(workspace, 'src'), { recursive: true });
    fs.writeFileSync(path.join(workspace, 'src', 'index.js'), "console.log('hi');\n");
    fs.writeFileSync(path.join(workspace, 'README.md'), '# A project\n');
  },
  prompt:
    'What is the value of the "name" field in package.json? ' +
    'Reply with just the name and nothing else.',
  grade: ({ finalText, toolCalls }) => {
    const found = finalText.toLowerCase().includes(PROJECT_NAME.toLowerCase());
    if (found) {
      return {
        pass: true,
        detail: `answer mentions "${PROJECT_NAME}" (tools: ${toolCalls.join(', ') || 'none'})`,
      };
    }
    return {
      pass: false,
      detail: `expected "${PROJECT_NAME}" in answer; got "${finalText.slice(0, 100)}"`,
    };
  },
};
