/** AskUser tool: prompt the user for clarification mid-conversation. */

import type { CLI } from '../../cli/types.js';
import type { Tool } from '../base.js';

export class AskUserTool implements Tool {
  constructor(private cli: CLI) {}

  get name(): string {
    return 'ask_user';
  }

  get description(): string {
    return (
      'Ask the user a question when you need clarification before proceeding. ' +
      'Use this when the request is ambiguous, you need to choose between multiple ' +
      "approaches, or you need information you can't determine from the codebase."
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        question: {
          type: 'string',
          description: 'The question to ask the user.',
        },
      },
      required: ['question'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const question: string = params.question;
    this.cli.printQuestion(question);
    const answer = await this.cli.getInput();
    if (answer === null) {
      return '(user did not provide an answer)';
    }
    return answer;
  }
}
