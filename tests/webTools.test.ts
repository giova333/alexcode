import { afterEach, describe, expect, it, vi } from 'vitest';

import { WebFetchTool } from '../src/tools/builtin/webFetch.js';
import { WebSearchTool } from '../src/tools/builtin/webSearch.js';

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockResponse(body: string, contentType: string, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k: string) => (k.toLowerCase() === 'content-type' ? contentType : null) },
    text: async () => body,
    json: async () => JSON.parse(body),
  } as unknown as Response;
}

describe('WebFetchTool', () => {
  it('rejects non-http URLs', async () => {
    const out = await new WebFetchTool().execute({ url: 'ftp://example.com' });
    expect(out).toContain('must start with http');
  });

  it('converts HTML to text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        mockResponse('<html><body><h1>Title</h1><p>Hello</p></body></html>', 'text/html'),
      ),
    );
    const out = await new WebFetchTool().execute({ url: 'https://example.com' });
    expect(out).toContain('Title');
    expect(out).toContain('Hello');
  });

  it('returns plain text as-is and applies prompt focus', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => mockResponse('raw text body', 'text/plain')),
    );
    const out = await new WebFetchTool().execute({ url: 'https://x.com', prompt: 'find foo' });
    expect(out).toContain('[Extraction focus: find foo]');
    expect(out).toContain('raw text body');
  });

  it('rejects non-text content', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => mockResponse('binary', 'image/png')),
    );
    const out = await new WebFetchTool().execute({ url: 'https://x.com/img' });
    expect(out).toContain('non-text content');
  });

  it('reports HTTP errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => mockResponse('nope', 'text/html', 404)),
    );
    const out = await new WebFetchTool().execute({ url: 'https://x.com' });
    expect(out).toContain('HTTP 404');
  });
});

describe('WebSearchTool', () => {
  it('parses DuckDuckGo lite HTML results', async () => {
    const html = `
      <table>
        <tr><td><a class="result-link" href="https://a.com">Result A</a></td></tr>
        <tr><td class="result-snippet">Snippet A</td></tr>
        <tr><td><a class="result-link" href="https://b.com">Result B</a></td></tr>
        <tr><td class="result-snippet">Snippet B</td></tr>
      </table>`;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => mockResponse(html, 'text/html')),
    );
    const out = await new WebSearchTool('duckduckgo', '').execute({ query: 'test' });
    expect(out).toContain('1. Result A');
    expect(out).toContain('https://a.com');
    expect(out).toContain('Snippet A');
    expect(out).toContain('2. Result B');
  });

  it('uses the Brave API when configured', async () => {
    const json = JSON.stringify({
      web: { results: [{ title: 'Brave Hit', url: 'https://brave.com', description: 'desc' }] },
    });
    const fetchMock = vi.fn(async () => mockResponse(json, 'application/json'));
    vi.stubGlobal('fetch', fetchMock);
    const out = await new WebSearchTool('brave', 'api-key').execute({ query: 'q' });
    expect(out).toContain('Brave Hit');
    expect(out).toContain('desc');
    const calledUrl = (fetchMock.mock.calls[0]![0] as string) ?? '';
    expect(calledUrl).toContain('api.search.brave.com');
  });
});
