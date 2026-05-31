/** Eval: the agent reads a buggy file and fixes it with a targeted edit. */

import fs from 'node:fs';
import path from 'node:path';

import type { EvalScenario } from '../harness.js';

const BUGGY = `function add(a, b) {
  return a - b;
}

module.exports = { add };
`;

export const editFile: EvalScenario = {
  name: 'edit-file',
  description: 'Agent reads a buggy file and corrects the logic error.',
  setup: (workspace) => {
    fs.writeFileSync(path.join(workspace, 'math.js'), BUGGY);
  },
  prompt:
    'There is a bug in math.js: the add function subtracts instead of adds. ' +
    'Read the file and fix it so add returns the sum of its arguments.',
  grade: ({ workspace }) => {
    const file = path.join(workspace, 'math.js');
    if (!fs.existsSync(file)) {
      return { pass: false, detail: 'math.js is missing' };
    }
    const content = fs.readFileSync(file, 'utf-8');
    const fixed = /return\s+a\s*\+\s*b/.test(content);
    const stillBuggy = /return\s+a\s*-\s*b/.test(content);
    if (fixed && !stillBuggy) {
      return { pass: true, detail: 'add now returns a + b' };
    }
    return {
      pass: false,
      detail: `expected "return a + b"; fixed=${fixed} stillBuggy=${stillBuggy}`,
    };
  },
};
