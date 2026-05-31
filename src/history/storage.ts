/** Conversation history persistence as JSONL files (one JSON object per line). */

import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { Message, type ContentBlock } from '../core/message.js';

interface SessionInfo {
  session_id: string;
  timestamp: string;
  message_count: number;
}

function timestamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_` +
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  );
}

/**
 * Saves and loads conversation histories as JSONL.
 *
 *   Line 1:  header   {"type":"header","session_id":...,"timestamp":...,"metadata":...}
 *   Line 2+: messages {"type":"message","role":...,"content":...,"token_count":N}
 */
export class HistoryStorage {
  private dir: string;

  constructor(historyDir: string, baseDir: string) {
    this.dir = path.join(baseDir, historyDir);
    fs.mkdirSync(this.dir, { recursive: true });
  }

  newSessionId(): string {
    return `${timestamp()}_${randomBytes(4).toString('hex')}`;
  }

  private jsonlPath(sessionId: string): string {
    return path.join(this.dir, `${sessionId}.jsonl`);
  }

  private jsonPath(sessionId: string): string {
    return path.join(this.dir, `${sessionId}.json`);
  }

  /** Append new messages to a JSONL session file. */
  save(
    sessionId: string,
    messages: Message[],
    metadata: Record<string, any> | null = null,
  ): string {
    const filePath = this.jsonlPath(sessionId);
    let existingCount = 0;

    if (fs.existsSync(filePath)) {
      const lines = fs.readFileSync(filePath, 'utf-8').split('\n');
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const obj = JSON.parse(trimmed);
          if (obj.type === 'message') existingCount += 1;
        } catch {
          /* ignore */
        }
      }
    } else {
      const header = {
        type: 'header',
        session_id: sessionId,
        timestamp: new Date().toISOString(),
        metadata: metadata ?? {},
      };
      fs.writeFileSync(filePath, JSON.stringify(header) + '\n');
    }

    const newMessages = messages.slice(existingCount);
    if (newMessages.length > 0) {
      const lines = newMessages.map((msg) =>
        JSON.stringify({
          type: 'message',
          role: msg.role,
          content: msg.content,
          token_count: msg.tokenCount,
        }),
      );
      fs.appendFileSync(filePath, lines.join('\n') + '\n');
    }

    return filePath;
  }

  /** Rewrite a session file from scratch (e.g. after compaction). */
  rewrite(
    sessionId: string,
    messages: Message[],
    metadata: Record<string, any> | null = null,
  ): string {
    const filePath = this.jsonlPath(sessionId);
    const header = {
      type: 'header',
      session_id: sessionId,
      timestamp: new Date().toISOString(),
      metadata: metadata ?? {},
    };
    const lines = [JSON.stringify(header)];
    for (const msg of messages) {
      lines.push(
        JSON.stringify({
          type: 'message',
          role: msg.role,
          content: msg.content,
          token_count: msg.tokenCount,
        }),
      );
    }
    fs.writeFileSync(filePath, lines.join('\n') + '\n');
    return filePath;
  }

  load(sessionId: string): Message[] | null {
    const filePath = this.jsonlPath(sessionId);
    if (!fs.existsSync(filePath)) {
      return this.loadLegacyJson(sessionId);
    }
    const messages: Message[] = [];
    const lines = fs.readFileSync(filePath, 'utf-8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj: any;
      try {
        obj = JSON.parse(trimmed);
      } catch {
        continue;
      }
      if (obj.type !== 'message') continue;
      messages.push(new Message(obj.role, obj.content as ContentBlock[], obj.token_count ?? 0));
    }
    return messages.length > 0 ? messages : null;
  }

  private loadLegacyJson(sessionId: string): Message[] | null {
    const filePath = this.jsonPath(sessionId);
    if (!fs.existsSync(filePath)) return null;
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    const messages: Message[] = [];
    for (const m of data.messages ?? []) {
      messages.push(new Message(m.role, m.content as ContentBlock[], m.token_count ?? 0));
    }
    return messages;
  }

  /** Reset a session file to header-only (no messages). */
  clearSession(sessionId: string): void {
    const filePath = this.jsonlPath(sessionId);
    if (!fs.existsSync(filePath)) return;
    let header: any = null;
    const lines = fs.readFileSync(filePath, 'utf-8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj = JSON.parse(trimmed);
        if (obj.type === 'header') {
          header = obj;
          break;
        }
      } catch {
        /* ignore */
      }
    }
    if (header) {
      fs.writeFileSync(filePath, JSON.stringify(header) + '\n');
    }
  }

  private listFiles(): Array<{ file: string; stem: string; mtime: number; ext: string }> {
    let entries: string[];
    try {
      entries = fs.readdirSync(this.dir);
    } catch {
      return [];
    }
    const files: Array<{ file: string; stem: string; mtime: number; ext: string }> = [];
    for (const name of entries) {
      const ext = path.extname(name);
      if (ext !== '.jsonl' && ext !== '.json') continue;
      const full = path.join(this.dir, name);
      let mtime = 0;
      try {
        mtime = fs.statSync(full).mtimeMs;
      } catch {
        continue;
      }
      files.push({ file: full, stem: path.basename(name, ext), mtime, ext });
    }
    files.sort((a, b) => b.mtime - a.mtime);
    return files;
  }

  /** Find a session ID by exact or prefix match. Returns full ID or null. */
  findSession(query: string): string | null {
    if (fs.existsSync(this.jsonlPath(query))) return query;
    if (fs.existsSync(this.jsonPath(query))) return query;
    const matches = this.listFiles().filter((f) => f.stem.startsWith(query));
    return matches.length > 0 ? matches[0]!.stem : null;
  }

  getLatestSessionId(): string | null {
    const files = this.listFiles();
    return files.length > 0 ? files[0]!.stem : null;
  }

  /** List recent sessions (newest first). */
  listSessions(limit = 20): SessionInfo[] {
    const files = this.listFiles().slice(0, limit);
    const sessions: SessionInfo[] = [];
    for (const f of files) {
      try {
        sessions.push(
          f.ext === '.jsonl' ? this.sessionInfoJsonl(f.file) : this.sessionInfoJson(f.file),
        );
      } catch {
        continue;
      }
    }
    return sessions;
  }

  private sessionInfoJsonl(filePath: string): SessionInfo {
    let sessionId = path.basename(filePath, '.jsonl');
    let ts = '';
    let messageCount = 0;
    const lines = fs.readFileSync(filePath, 'utf-8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj: any;
      try {
        obj = JSON.parse(trimmed);
      } catch {
        continue;
      }
      if (obj.type === 'header') {
        sessionId = obj.session_id ?? sessionId;
        ts = obj.timestamp ?? '';
      } else if (obj.type === 'message') {
        messageCount += 1;
      }
    }
    return { session_id: sessionId, timestamp: ts, message_count: messageCount };
  }

  private sessionInfoJson(filePath: string): SessionInfo {
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    return {
      session_id: data.session_id ?? path.basename(filePath, '.json'),
      timestamp: data.timestamp ?? '',
      message_count: (data.messages ?? []).length,
    };
  }
}
