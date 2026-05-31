/** Terminal UI interface, implemented by the real CLI and test fakes. */

export interface CLI {
  printWelcome(provider: string, model: string): void;
  printInfo(message: string): void;
  printError(message: string): void;
  printQuestion(question: string): void;
  printTextDelta(text: string): void;
  printThinkingDelta(text: string): void;
  printAssistantText(text: string): void;
  printToolUse(name: string, input: Record<string, any>): void;
  printToolResult(name: string, result: string, isError: boolean): void;
  printUsage(inputTokens: number, outputTokens: number): void;
  printCompactionNotice(): void;
  startResponse(): void;
  endResponse(): void;
  startThinking(): void;
  endThinking(): void;
  getInput(): Promise<string | null>;
  setSkills(skills: Array<[string, string]>): void;
}
