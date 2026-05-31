/** Memory orchestrator: MEMORY.md I/O + delegates search/ingest to a provider. */

import type { MemoryConfig } from '../config/schema.js';
import type { Message } from '../core/message.js';
import { MemoryFiles } from './files.js';
import type { MemoryProvider, MemorySearchResult } from './provider.js';

/**
 * Orchestrates memory reads, writes, and search across two layers:
 *   - MEMORY.md: stable, long-term knowledge (auto-injected into the prompt)
 *   - provider:  continuously-ingested memories distilled from messages
 */
export class MemoryManager {
  private filesStore: MemoryFiles;
  private provider: MemoryProvider | null;

  constructor(config: MemoryConfig, baseDir: string, provider: MemoryProvider | null = null) {
    this.filesStore = new MemoryFiles(config.memory_file, baseDir);
    this.provider = provider;
  }

  /** Load MEMORY.md content for the system prompt. */
  async loadContext(): Promise<string> {
    return this.filesStore.read();
  }

  /** Save to MEMORY.md (stable, long-term knowledge only). */
  async saveMain(content: string): Promise<string> {
    this.filesStore.append(content);
    return 'Saved to MEMORY.md.';
  }

  async readMain(): Promise<string> {
    return this.filesStore.read();
  }

  /** Search provider memory (scope configured via MemoryConfig.scope). */
  async search(query: string, topK = 10): Promise<MemorySearchResult[]> {
    if (this.provider === null) return [];
    return this.provider.search(query, topK);
  }

  /** Submit a full user→assistant turn to the provider as a single batch. */
  ingestTurn(userMsg: Message, assistantMsgs: Message[]): void {
    if (this.provider === null) return;
    this.provider.enqueueTurn([userMsg, ...assistantMsgs]);
  }

  get files(): MemoryFiles {
    return this.filesStore;
  }

  get mem0(): MemoryProvider | null {
    return this.provider;
  }
}
