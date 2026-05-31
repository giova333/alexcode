/** WebFetch tool — fetch a URL and return page content as readable text. */

import TurndownService from 'turndown';

import type { Tool } from '../base.js';

const TEXT_CONTENT_TYPES = new Set([
  'text/html',
  'text/plain',
  'application/json',
  'application/xml',
  'text/xml',
  'text/csv',
]);

function isTextResponse(contentType: string): boolean {
  const base = (contentType.split(';')[0] ?? '').trim().toLowerCase();
  return TEXT_CONTENT_TYPES.has(base) || base.startsWith('text/');
}

let turndown: TurndownService | null = null;
function htmlToText(html: string): string {
  if (turndown === null) {
    turndown = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced' });
    turndown.remove(['script', 'style', 'head', 'noscript']);
  }
  return turndown.turndown(html).trim();
}

export class WebFetchTool implements Tool {
  constructor(
    private timeout = 30,
    private maxContentLength = 50_000,
    private userAgent = 'Mozilla/5.0 (compatible; AgentCLI/0.1)',
  ) {}

  get name(): string {
    return 'web_fetch';
  }

  get description(): string {
    return (
      'Fetch a URL and return the page content as readable text. ' +
      'Supports HTML pages (converted to text), plain text, and JSON. ' +
      "Use the optional 'prompt' parameter to indicate what information you are looking for."
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        url: {
          type: 'string',
          description: 'The URL to fetch (must be http:// or https://).',
        },
        prompt: {
          type: 'string',
          description: 'Optional question or focus area to guide content extraction.',
        },
      },
      required: ['url'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const url: string = params.url;
    const prompt: string | undefined = params.prompt;

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      return 'Error: URL must start with http:// or https://';
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout * 1000);
    let response: Response;
    try {
      response = await fetch(url, {
        headers: { 'User-Agent': this.userAgent },
        redirect: 'follow',
        signal: controller.signal,
      });
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        return `Error: Request timed out after ${this.timeout}s for ${url}`;
      }
      return `Error: Could not connect to ${url}`;
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      return `Error: HTTP ${response.status} for ${url}`;
    }

    const contentType = response.headers.get('content-type') ?? 'text/plain';
    if (!isTextResponse(contentType)) {
      const base = (contentType.split(';')[0] ?? '').trim();
      return `Error: URL returned non-text content (${base}), cannot extract text.`;
    }

    const raw = await response.text();
    const baseType = (contentType.split(';')[0] ?? '').trim().toLowerCase();
    let text = baseType === 'text/html' ? htmlToText(raw) : raw;

    if (text.length > this.maxContentLength) {
      text =
        text.slice(0, this.maxContentLength) +
        `\n\n... (content truncated at ${this.maxContentLength} characters)`;
    }

    if (prompt) {
      text = `[Extraction focus: ${prompt}]\n\n${text}`;
    }

    return text || '(empty page)';
  }
}
