/** Eval: the agent creates a new file with exact contents. */

import fs from 'node:fs';
import path from 'node:path';

import type { EvalScenario } from '../harness.js';

const EXPECTED = 'Hello from alexcode';

export const createFile: EvalScenario = {
  name: 'create-file',
  description: 'Agent writes a new file with the requested exact contents.',
  prompt:
    `Create a file named greeting.txt in the current directory whose entire contents ` +
    `are exactly the following line, with no extra text, quotes, or trailing commentary:\n` +
    `${EXPECTED}`,
  grade: ({ workspace }) => {
    const file = path.join(workspace, 'greeting.txt');
    if (!fs.existsSync(file)) {
      return { pass: false, detail: 'greeting.txt was not created' };
    }
    const actual = fs.readFileSync(file, 'utf-8').trim();
    if (actual === EXPECTED) {
      return { pass: true, detail: 'greeting.txt matches expected contents' };
    }
    return { pass: false, detail: `expected "${EXPECTED}", got "${actual.slice(0, 80)}"` };
  },
};
