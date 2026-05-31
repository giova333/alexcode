/** OAuth browser flow support for MCP HTTP servers (file-backed token storage). */

import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { URL } from 'node:url';

export const CALLBACK_PORT = 18247;

/**
 * An OAuthClientProvider (duck-typed against @modelcontextprotocol/sdk) that
 * persists tokens/client info to disk and drives a browser-based auth flow.
 */
export class FileOAuthProvider {
  private dir: string;

  constructor(
    private serverName: string,
    baseDir = '.agent/oauth',
  ) {
    this.dir = path.join(baseDir, serverName);
    fs.mkdirSync(this.dir, { recursive: true });
  }

  get redirectUrl(): string {
    return `http://127.0.0.1:${CALLBACK_PORT}/callback`;
  }

  get clientMetadata(): Record<string, any> {
    return {
      client_name: `agent-${this.serverName}`,
      redirect_uris: [this.redirectUrl],
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'client_secret_basic',
    };
  }

  private readJson(file: string): any {
    const p = path.join(this.dir, file);
    if (!fs.existsSync(p)) return undefined;
    try {
      return JSON.parse(fs.readFileSync(p, 'utf-8'));
    } catch {
      return undefined;
    }
  }

  private writeJson(file: string, data: unknown): void {
    fs.writeFileSync(path.join(this.dir, file), JSON.stringify(data, null, 2));
  }

  clientInformation(): any {
    return this.readJson('client.json');
  }

  saveClientInformation(info: any): void {
    this.writeJson('client.json', info);
  }

  tokens(): any {
    return this.readJson('tokens.json');
  }

  saveTokens(tokens: any): void {
    this.writeJson('tokens.json', tokens);
  }

  saveCodeVerifier(verifier: string): void {
    fs.writeFileSync(path.join(this.dir, 'verifier.txt'), verifier);
  }

  codeVerifier(): string {
    return fs.readFileSync(path.join(this.dir, 'verifier.txt'), 'utf-8');
  }

  async redirectToAuthorization(authorizationUrl: URL): Promise<void> {
    console.error('Opening browser for authentication...');
    const { default: open } = await import('open');
    await open(authorizationUrl.toString());
  }
}

/**
 * Run a temporary local HTTP server to receive the OAuth callback.
 * Resolves with [authCode, state].
 */
export function waitForCallback(): Promise<[string, string | null]> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url ?? '/', `http://127.0.0.1:${CALLBACK_PORT}`);
      const code = url.searchParams.get('code');
      const state = url.searchParams.get('state');

      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(
        '<html><body><h2>Authentication successful!</h2>' +
          '<p>You can close this tab and return to the agent.</p>' +
          '<script>window.close()</script></body></html>',
      );
      server.close();
      if (!code) {
        reject(new Error('No authorization code received from OAuth callback'));
      } else {
        resolve([code, state]);
      }
    });
    server.on('error', reject);
    server.listen(CALLBACK_PORT, '127.0.0.1');
  });
}
