# Evaluations

Live, end-to-end evaluations of the agent. Unlike the Vitest suite in `tests/`
(which is deterministic and scripts the LLM), these evals run the **real**
`AgentLoop` against the **Anthropic API** on a throwaway temp workspace and grade
the result by inspecting the filesystem and/or the agent's final answer.

They are opt-in and **not** part of `npm test` — they require an API key and cost
a small amount of tokens.

## Running

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
npm run eval                 # run all scenarios
npm run eval edit            # only scenarios whose name contains "edit"
```

Without `ANTHROPIC_API_KEY` set, the runner prints a skip notice and exits 0, so
it's safe to wire into scripts.

### Environment knobs

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Required to actually run (otherwise skipped) |
| `EVAL_MODEL` | `claude-haiku-4-5-20251001` | Model under test (Haiku keeps cost low) |
| `EVAL_JUDGE_MODEL` | `claude-sonnet-4-6` | Model used for LLM-as-judge grading |
| `EVAL_VERBOSE` | unset | Set to `1` to stream the agent's output and tool calls |
| `EVAL_TIMEOUT_MS` | `120000` | Per-scenario timeout (guards against runaway loops) |

The runner exits non-zero if any scenario fails.

## Scenarios

| Name | What it checks | Grading |
|------|----------------|---------|
| `create-file` | Writes a new file with exact requested contents (`write`) | Deterministic (read back) |
| `edit-file` | Reads a buggy file and applies a correct fix (`read` + `edit`) | Deterministic (regex on result) |
| `answer-question` | Inspects a seeded repo and answers a factual question (`read`/`grep`/`glob`) | Deterministic (substring) |
| `binary-search` | Implements a non-trivial algorithm | **Hybrid: execution gate + LLM-as-judge** |

Each scenario runs in an isolated `mkdtemp` workspace that is removed afterwards.
The harness `chdir`s into that workspace so the agent's relative file operations
land there.

### Grading strategies

Deterministic checks (file contents, substrings) are preferred where the correct
output is well-defined. For open-ended coding tasks they aren't enough, so
`binary-search` uses a **hybrid** approach:

1. **Execution gate** — the produced `binarySearch.js` is run against hidden test
   cases in a `node` subprocess. This is the gold-standard correctness check:
   deterministic, cheap, no judge bias.
2. **LLM-as-judge** (`judge.ts`) — grades what execution can't: that the solution
   is a *genuine* O(log n) binary search (not a linear scan / `indexOf`), handles
   edge cases, and is clean. The verdict is collected via a **forced tool call**
   (`temperature: 0`) so it's always a structured `{ pass, score, reasoning }`
   object, graded by a stronger model (`EVAL_JUDGE_MODEL`, default Sonnet).

Final pass = execution passes **and** the judge approves (`score ≥ 4`). Combining
the two avoids both flaky judge-only grading and execution-only grading that would
accept a passing-but-not-actually-binary-search implementation.

To reuse the judge in your own scenario, call `judge({ task, rubric, artifact })`
from `evals/judge.ts` inside an async `grade`.

## Adding a scenario

Create `scenarios/<name>.ts` exporting an `EvalScenario`:

```ts
import type { EvalScenario } from '../harness.js';

export const myScenario: EvalScenario = {
  name: 'my-scenario',
  description: 'what it measures',
  setup: (workspace) => {/* seed files (optional) */},
  prompt: 'the instruction sent to the agent',
  grade: ({ workspace, finalText, toolCalls }) => ({
    pass: /* ... */ true,
    detail: 'human-readable explanation',
  }),
};
```

Then register it in the `SCENARIOS` array in `run.ts`.
