/** Pluggable vector-memory provider interface. */

import type { Message } from '../core/message.js';

export interface MemorySearchResult {
  text: string;
  source: string;
  score: number;
}

/**
 * A swappable backend for continuously-ingested, searchable memory.
 *
 * Implementations should degrade gracefully: when the backend is unavailable
 * (missing keys, no vector store), search returns [] and ingestion is a no-op.
 */
export interface MemoryProvider {
  readonly scope: string;
  search(query: string, topK?: number): Promise<MemorySearchResult[]>;
  enqueueTurn(messages: Message[]): void;
  close(): Promise<void>;
}
