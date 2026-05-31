/**
 * LLM-as-judge: grades a solution against a rubric using the Anthropic API.
 *
 * The verdict is collected via a forced tool call so the output is always a
 * structured object rather than free-form prose. Used for qualitative criteria
 * that can't be checked deterministically (e.g. "is this a genuine binary
 * search and not a linear scan?").
 */

import Anthropic from '@anthropic-ai/sdk';

export interface JudgeVerdict {
  pass: boolean;
  /** 1 (poor) .. 5 (excellent). */
  score: number;
  reasoning: string;
}

export interface JudgeRequest {
  /** The instruction the candidate agent was given. */
  task: string;
  /** Criteria the solution must satisfy (all must hold to pass). */
  rubric: string[];
  /** The artifact under evaluation (source code, an answer, etc.). */
  artifact: string;
  artifactLabel?: string;
}

const VERDICT_TOOL = {
  name: 'submit_verdict',
  description: 'Submit the grading verdict for the candidate solution.',
  input_schema: {
    type: 'object' as const,
    properties: {
      pass: { type: 'boolean', description: 'Whether every rubric item is satisfied.' },
      score: { type: 'integer', description: 'Overall quality from 1 (poor) to 5 (excellent).' },
      reasoning: { type: 'string', description: 'Concise justification referencing the rubric.' },
    },
    required: ['pass', 'score', 'reasoning'],
  },
};

export async function judge(req: JudgeRequest): Promise<JudgeVerdict> {
  const model = process.env.EVAL_JUDGE_MODEL ?? 'claude-sonnet-4-6';
  const client = new Anthropic(
    process.env.ANTHROPIC_API_KEY ? { apiKey: process.env.ANTHROPIC_API_KEY } : {},
  );

  const rubric = req.rubric.map((r, i) => `${i + 1}. ${r}`).join('\n');
  const userText =
    `Task given to the candidate:\n${req.task}\n\n` +
    `Rubric — ALL items must hold for a pass:\n${rubric}\n\n` +
    `${req.artifactLabel ?? 'Candidate solution'}:\n\n\`\`\`\n${req.artifact}\n\`\`\`\n\n` +
    `Grade strictly against the rubric and submit your verdict.`;

  const res = await client.messages.create({
    model,
    max_tokens: 1024,
    temperature: 0,
    system:
      'You are a strict, fair senior engineer grading a candidate solution. ' +
      'Judge only against the provided rubric. Do not reward effort or verbosity.',
    messages: [{ role: 'user', content: userText }],
    tools: [VERDICT_TOOL],
    tool_choice: { type: 'tool', name: 'submit_verdict' },
  });

  const block = res.content.find((b) => b.type === 'tool_use');
  if (!block || block.type !== 'tool_use') {
    return { pass: false, score: 0, reasoning: 'judge did not return a verdict' };
  }
  const input = block.input as { pass?: unknown; score?: unknown; reasoning?: unknown };
  return {
    pass: Boolean(input.pass),
    score: Number(input.score) || 0,
    reasoning: typeof input.reasoning === 'string' ? input.reasoning : '',
  };
}
