/**
 * Eval: a non-trivial coding task (binary search) graded with a hybrid strategy.
 *
 *   1. Execution gate — run the agent's code against hidden test cases (the
 *      deterministic, gold-standard correctness check).
 *   2. LLM-as-judge — grade what execution can't: is it a genuine O(log n)
 *      binary search (not a linear scan), are edge cases handled, is it clean.
 *
 * Final pass = tests pass AND the judge approves.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import type { EvalScenario } from '../harness.js';
import { judge } from '../judge.js';

const SOLUTION_FILE = 'binarySearch.js';

const TASK =
  `Implement binary search. Create a CommonJS file named ${SOLUTION_FILE} in the ` +
  `current directory that exports a function \`binarySearch(arr, target)\` via ` +
  `module.exports. \`arr\` is an array of numbers sorted in ascending order; the ` +
  `function returns the index of \`target\`, or -1 if it is not present. Use an ` +
  `efficient O(log n) algorithm.`;

// CommonJS runner that loads the candidate file and checks correctness. Prints a
// single JSON line: {"allPassed":bool,"failures":[...]}.
const RUNNER_SRC = `
const mod = require('./${SOLUTION_FILE}');
const fn = typeof mod === 'function' ? mod : (mod && (mod.binarySearch || mod.default));
const failures = [];
if (typeof fn !== 'function') {
  console.log(JSON.stringify({ allPassed: false, failures: ['no binarySearch function exported'] }));
  process.exit(0);
}
const range = (n) => Array.from({ length: n }, (_, i) => i * 2); // [0,2,4,...]
const cases = [
  { arr: [], target: 5, want: -1 },
  { arr: [1], target: 1, want: 0 },
  { arr: [1], target: 2, want: -1 },
  { arr: [1, 3, 5, 7, 9], target: 1, want: 0 },
  { arr: [1, 3, 5, 7, 9], target: 9, want: 4 },
  { arr: [1, 3, 5, 7, 9], target: 5, want: 2 },
  { arr: [1, 3, 5, 7, 9], target: 4, want: -1 },
  { arr: range(1000), target: 0, want: 0 },
  { arr: range(1000), target: 1998, want: 999 },
  { arr: range(1000), target: 1000, want: 500 },
  { arr: range(1000), target: 1001, want: -1 },
];
for (const c of cases) {
  let got;
  try {
    got = fn(c.arr, c.target);
  } catch (e) {
    failures.push('threw on target=' + c.target + ': ' + e.message);
    continue;
  }
  if (got !== c.want) {
    failures.push('target=' + c.target + ' (len ' + c.arr.length + '): want ' + c.want + ', got ' + got);
  }
}
console.log(JSON.stringify({ allPassed: failures.length === 0, failures }));
`;

export const binarySearch: EvalScenario = {
  name: 'binary-search',
  description: 'Implement binary search; graded by execution + LLM-as-judge.',
  prompt: TASK,
  grade: async ({ workspace }) => {
    const file = path.join(workspace, SOLUTION_FILE);
    if (!fs.existsSync(file)) {
      return { pass: false, detail: `${SOLUTION_FILE} was not created` };
    }
    const source = fs.readFileSync(file, 'utf-8');

    // 1. Execution gate.
    fs.writeFileSync(path.join(workspace, '__runner.cjs'), RUNNER_SRC);
    let exec: { allPassed: boolean; failures: string[] };
    try {
      const out = execFileSync('node', ['__runner.cjs'], {
        cwd: workspace,
        timeout: 10_000,
        encoding: 'utf-8',
      });
      const lastLine = out.trim().split('\n').pop() ?? '{}';
      exec = JSON.parse(lastLine);
    } catch (e: any) {
      const msg = (e?.stderr || e?.message || String(e)).toString().slice(0, 200);
      return { pass: false, detail: `execution failed: ${msg}` };
    }
    if (!exec.allPassed) {
      return { pass: false, detail: `failing cases: ${exec.failures.slice(0, 3).join(' | ')}` };
    }

    // 2. LLM-as-judge for approach + quality.
    const verdict = await judge({
      task: TASK,
      rubric: [
        'The algorithm is a genuine binary search that halves the search range each step (O(log n)) — NOT a linear scan, Array.prototype.indexOf, includes, or filter.',
        'Edge cases are handled correctly: empty array, single element, target absent, and the first/last elements.',
        'The code is clean and free of obvious bugs (e.g. correct mid computation and loop bounds).',
      ],
      artifact: source,
      artifactLabel: `Candidate ${SOLUTION_FILE}`,
    });

    const pass = verdict.pass && verdict.score >= 4;
    return {
      pass,
      detail: `tests passed; judge ${verdict.score}/5 ${verdict.pass ? '✓' : '✗'} — ${verdict.reasoning.slice(0, 160)}`,
    };
  },
};
