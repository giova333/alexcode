/**
 * Live eval runner. Requires ANTHROPIC_API_KEY; skips gracefully without it.
 *
 *   npm run eval                 # run all scenarios
 *   npm run eval edit            # run scenarios whose name includes "edit"
 *   EVAL_VERBOSE=1 npm run eval   # stream the agent's output
 *   EVAL_MODEL=claude-sonnet-4-6 npm run eval
 */

import { runScenario, type EvalScenario, type EvalOutcome } from './harness.js';
import { answerQuestion } from './scenarios/answer-question.js';
import { createFile } from './scenarios/create-file.js';
import { editFile } from './scenarios/edit-file.js';

const SCENARIOS: EvalScenario[] = [createFile, editFile, answerQuestion];

async function main(): Promise<void> {
  if (!process.env.ANTHROPIC_API_KEY) {
    console.log('Skipping evals: set ANTHROPIC_API_KEY to run.');
    process.exit(0);
  }

  const filter = process.argv[2];
  const scenarios = filter ? SCENARIOS.filter((s) => s.name.includes(filter)) : SCENARIOS;

  if (scenarios.length === 0) {
    console.error(
      `No scenarios match "${filter}". Available: ${SCENARIOS.map((s) => s.name).join(', ')}`,
    );
    process.exit(1);
  }

  const model = process.env.EVAL_MODEL ?? 'claude-haiku-4-5-20251001';
  console.log(`Running ${scenarios.length} eval(s) against ${model}\n`);

  const results: EvalOutcome[] = [];
  for (const scenario of scenarios) {
    const outcome = await runScenario(scenario);
    results.push(outcome);
    const mark = outcome.pass ? '✓' : '✗';
    const secs = (outcome.durationMs / 1000).toFixed(1);
    let line = `${mark} ${outcome.name}  (${secs}s) — ${outcome.detail}`;
    if (outcome.error) line += `\n    error: ${outcome.error}`;
    console.log(line);
  }

  const passed = results.filter((r) => r.pass).length;
  console.log(`\n${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
