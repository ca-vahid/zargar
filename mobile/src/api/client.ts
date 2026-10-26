// The one place that talks HTTP. No React, no storage: the session module hands it
// the server address, the token and what to do when the server says "signed out".

let baseUrl = '';
let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function configureClient(opts: { baseUrl?: string; token?: string | null; onUnauthorized?: () => void }) {
  if (opts.baseUrl !== undefined) baseUrl = opts.baseUrl.replace(/\/+$/, '');
  if (opts.token !== undefined) token = opts.token;
  if (opts.onUnauthorized !== undefined) onUnauthorized = opts.onUnauthorized;
}

export const getBaseUrl = () => baseUrl;
export const getToken = () => token;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** ws(s)://host/ws?token=…&client=phone — the socket reads the token from the URL. */
export function socketUrl(): string {
  const u = baseUrl.replace(/^http/i, 'ws');
  const q = [`client=phone`];
  if (token) q.unshift(`token=${encodeURIComponent(token)}`);
  return `${u}/ws?${q.join('&')}`;
}

export async function request<T>(method: string, path: string, body?: unknown, timeoutMs = 20000): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    // the server's exit-only rule for phones keys on this (and, once the backend
    // change ships, on the client class signed into the session itself)
    'X-Zargar-Client': 'phone',
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let resp: Response;
  try {
    resp = await fetch(baseUrl + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
    });
  } catch (e: any) {
    throw new ApiError(0, e?.name === 'AbortError' ? 'The server did not answer in time' : 'Cannot reach the server');
  } finally {
    clearTimeout(timer);
  }
  if (resp.status === 401 && !path.startsWith('/api/auth/')) onUnauthorized?.();
  if (!resp.ok) {
    let detail = resp.statusText || `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep the status text */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}
