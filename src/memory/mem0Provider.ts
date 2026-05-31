/**
 * mem0-backed memory: a single project- or globally-scoped index with async
 * ingestion. Implemented against the optional `mem0ai` OSS SDK and degrades
 * gracefully to a no-op when the SDK or its backends are unavailable.
 */

import path from 'node:path';

import type { Mem0Config } from '../config/schema.js';
import type { Message } from '../core/message.js';
import { expandUser } from '../util/fsutil.js';
import type { MemoryProvider, MemorySearchResult } from './provider.js';

type Payload = { role: string; content: string };

export class Mem0Provider implements MemoryProvider {
  readonly scope: string;
  private config: Mem0Config;
  private userId: string;
  private storeDir: string;
  private collection: string;

  private memory: any = null;
  private initAttempted = false;
  private initPromise: Promise<boolean> | null = null;

  private queue: Payload[][] = [];
  private worker: Promise<void> | null = null;
  private stopped = false;

  constructor(config: Mem0Config, scope: string, projectDir: string) {
    if (scope !== 'project' && scope !== 'global') {
      throw new Error(`Invalid mem0 scope: ${scope}; expected 'project' or 'global'`);
    }
    this.config = config;
    this.scope = scope;
    if (scope === 'project') {
      this.userId = path.resolve(projectDir);
      this.storeDir = config.project_store_dir;
      this.collection = 'project_memories';
    } else {
      this.userId = 'global';
      this.storeDir = config.global_store_dir;
      this.collection = 'global_memories';
    }
  }

  private async ensureInit(): Promise<boolean> {
    if (this.initAttempted) return this.memory !== null;
    if (this.initPromise) return this.initPromise;
    this.initPromise = (async () => {
      try {
        this.memory = await this.buildMemory();
      } catch (e) {
        console.error(
          `mem0 init failed (scope=${this.scope}): ${String(e)} — search and ingest disabled. ` +
            'Check API keys (ANTHROPIC_API_KEY for llm, OPENAI_API_KEY for embedder) ' +
            "and that the 'mem0ai' package is installed.",
        );
        this.memory = null;
      }
      this.initAttempted = true;
      return this.memory !== null;
    })();
    return this.initPromise;
  }

  private async buildMemory(): Promise<any> {
    // Optional dependency — imported dynamically so its absence is non-fatal.
    const mod: any = await import('mem0ai/oss');
    const Memory = mod.Memory ?? mod.default?.Memory ?? mod.default;
    const absPath = path.resolve(expandUser(this.storeDir));

    const configDict = {
      version: 'v1.1',
      llm: {
        provider: this.config.llm.provider,
        config: { model: this.config.llm.model, apiKey: this.config.llm.api_key },
      },
      embedder: {
        provider: this.config.embedder.provider,
        config: { model: this.config.embedder.model, apiKey: this.config.embedder.api_key },
      },
      vectorStore: {
        provider: 'memory',
        config: { collectionName: this.collection, path: absPath },
      },
    };
    return new Memory(configDict);
  }

  enqueueTurn(messages: Message[]): void {
    const payloads: Payload[] = [];
    for (const message of messages) {
      if (message.role !== 'user' && message.role !== 'assistant') continue;
      const text = message.text.trim();
      if (!text) continue;
      payloads.push({ role: message.role, content: text });
    }
    if (payloads.length === 0) return;
    this.queue.push(payloads);
    this.kickWorker();
  }

  private kickWorker(): void {
    if (this.worker || this.stopped) return;
    this.worker = (async () => {
      while (this.queue.length > 0) {
        const item = this.queue.shift()!;
        try {
          await this.dispatchAdd(item);
        } catch (e) {
          console.error(`mem0 ingest failed (scope=${this.scope}): ${String(e)}`);
        }
      }
      this.worker = null;
    })();
  }

  private async dispatchAdd(payloads: Payload[]): Promise<void> {
    if (!(await this.ensureInit())) return;
    await this.memory.add(payloads, { userId: this.userId });
  }

  async search(query: string, topK = 10): Promise<MemorySearchResult[]> {
    if (!(await this.ensureInit())) return [];
    let hits: any;
    try {
      hits = await this.memory.search(query, { userId: this.userId, limit: topK });
    } catch (e) {
      console.error(`mem0 search failed (scope=${this.scope}): ${String(e)}`);
      return [];
    }
    const results = normalizeHits(hits, this.scope);
    results.sort((a, b) => b.score - a.score);
    return results.slice(0, topK);
  }

  async close(): Promise<void> {
    this.stopped = true;
    if (this.worker) {
      try {
        await this.worker;
      } catch {
        /* ignore */
      }
    }
  }
}

function normalizeHits(hits: any, source: string): MemorySearchResult[] {
  let raw: any[];
  if (hits && typeof hits === 'object' && Array.isArray(hits.results)) {
    raw = hits.results;
  } else if (Array.isArray(hits)) {
    raw = hits;
  } else {
    return [];
  }

  const out: MemorySearchResult[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const text = item.memory ?? item.text ?? '';
    let score = 0;
    const rawScore = item.score;
    if (typeof rawScore === 'number') {
      score = Math.round(rawScore * 1000) / 1000;
    }
    out.push({ text, source, score });
  }
  return out;
}
