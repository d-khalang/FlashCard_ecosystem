import { ApiError, kindFor } from './errors';

export interface ClientOptions {
  /** Relative base, for example './api/v1'. */
  baseUrl: string;
  getInitData: () => string;
  fetch?: typeof fetch;
  /** Called on any 401 so the app can show the "reopen from Telegram" screen. */
  onUnauthorized?: () => void;
}

export interface RequestOptions {
  query?: Record<string, string | number | undefined>;
  body?: unknown;
}

export interface HttpClient {
  request<T>(method: 'GET' | 'POST' | 'PATCH' | 'DELETE', path: string, opts?: RequestOptions): Promise<T>;
}

function buildQuery(query: RequestOptions['query']): string {
  if (!query) return '';
  const parts: string[] = [];
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== '') parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

async function readError(res: Response): Promise<ApiError> {
  let code: string | null = null;
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const data: unknown = await res.json();
    const err = (data as { error?: { code?: unknown; message?: unknown } } | null)?.error;
    if (err && typeof err.code === 'string') code = err.code;
    if (err && typeof err.message === 'string') message = err.message;
  } catch {
    /* body was not JSON */
  }
  const ra = Number.parseInt(res.headers.get('Retry-After') ?? '', 10);
  return new ApiError(kindFor(res.status, code), message, {
    status: res.status,
    code,
    retryAfter: Number.isFinite(ra) ? ra : null,
  });
}

export function createClient(options: ClientOptions): HttpClient {
  return {
    async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
      const doFetch = options.fetch ?? fetch;
      const headers: Record<string, string> = {
        Authorization: `tma ${options.getInitData()}`,
        Accept: 'application/json',
      };
      let body: string | undefined;
      if (opts.body !== undefined) {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(opts.body);
      }
      let res: Response;
      try {
        res = await doFetch(`${options.baseUrl}${path}${buildQuery(opts.query)}`, { method, headers, body });
      } catch (e) {
        throw new ApiError('network', e instanceof Error ? e.message : 'Network error');
      }
      if (!res.ok) {
        const err = await readError(res);
        if (err.kind === 'auth') options.onUnauthorized?.();
        throw err;
      }
      if (res.status === 204) return undefined as T;
      try {
        return (await res.json()) as T;
      } catch {
        throw new ApiError('bad_response', 'Response was not JSON', { status: res.status });
      }
    },
  };
}
