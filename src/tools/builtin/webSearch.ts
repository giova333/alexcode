/** WebSearch tool — search the web and return results. */

import * as cheerio from 'cheerio';

import type { Tool } from '../base.js';

interface SearchResult {
  title?: string;
  url?: string;
  snippet?: string;
  description?: string;
}

export class WebSearchTool implements Tool {
  private apiKey: string;

  constructor(
    private provider = 'brave',
    apiKey = '',
    private defaultMaxResults = 5,
    private timeout = 15,
    private userAgent = 'Mozilla/5.0 (compatible; AgentCLI/0.1)',
  ) {
    this.apiKey = apiKey || process.env.BRAVE_SEARCH_API_KEY || '';
  }

  get name(): string {
    return 'web_search';
  }

  get description(): string {
    return (
      'Search the web and return results with titles, URLs, and snippets. ' +
      'Uses Brave Search API when configured, otherwise falls back to DuckDuckGo.'
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'The search query.' },
        max_results: {
          type: 'integer',
          description: 'Maximum number of results to return (default: 5, max: 20).',
        },
      },
      required: ['query'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const query: string = params.query;
    const requested: number | undefined =
      typeof params.max_results === 'number' ? params.max_results : undefined;
    const count = Math.min(requested ?? this.defaultMaxResults, 20);

    if (this.apiKey && this.provider === 'brave') {
      return this.searchBrave(query, count);
    }
    return this.searchDuckDuckGo(query, count);
  }

  private async fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout * 1000);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  private async searchBrave(query: string, count: number): Promise<string> {
    let response: Response;
    try {
      const url = new URL('https://api.search.brave.com/res/v1/web/search');
      url.searchParams.set('q', query);
      url.searchParams.set('count', String(count));
      response = await this.fetchWithTimeout(url.toString(), {
        headers: {
          'X-Subscription-Token': this.apiKey,
          Accept: 'application/json',
          'User-Agent': this.userAgent,
        },
      });
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        return `Error: Search request timed out for query: ${query}`;
      }
      return `Error: Search request failed: ${e?.message ?? e}`;
    }

    if (!response.ok) {
      if (response.status === 429) return 'Error: Search API rate limited. Try again later.';
      return `Error: Search API returned HTTP ${response.status}`;
    }

    const data = (await response.json()) as any;
    const results: SearchResult[] = data?.web?.results ?? [];
    if (results.length === 0) {
      return `No results found for: ${query}`;
    }
    return this.formatResults(results.slice(0, count));
  }

  private async searchDuckDuckGo(query: string, count: number): Promise<string> {
    let response: Response;
    try {
      response = await this.fetchWithTimeout('https://lite.duckduckgo.com/lite/', {
        method: 'POST',
        headers: {
          'User-Agent': this.userAgent,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({ q: query }).toString(),
        redirect: 'follow',
      });
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        return `Error: Search request timed out for query: ${query}`;
      }
      return `Error: Search request failed: ${e?.message ?? e}`;
    }

    const html = await response.text();
    return this.parseDuckDuckGoHtml(html, count);
  }

  private parseDuckDuckGoHtml(html: string, count: number): string {
    const $ = cheerio.load(html);
    const results: SearchResult[] = [];

    const links = $('.result-link');
    const snippets = $('.result-snippet');

    links.each((i, el) => {
      const title = $(el).text().trim();
      const url = $(el).attr('href') ?? '';
      const snippet = snippets.eq(i).text().trim();
      if (title && url) {
        results.push({ title, url, snippet });
      }
    });

    if (results.length === 0) {
      return 'No results found for the query.';
    }
    return this.formatResults(results.slice(0, count));
  }

  private formatResults(results: SearchResult[]): string {
    const lines: string[] = [];
    results.forEach((result, idx) => {
      const title = result.title ?? 'Untitled';
      const url = result.url ?? '';
      const snippet = result.description ?? result.snippet ?? '';
      lines.push(`${idx + 1}. ${title}`);
      lines.push(`   URL: ${url}`);
      if (snippet) lines.push(`   ${snippet}`);
      lines.push('');
    });
    return lines.join('\n').trim();
  }
}
