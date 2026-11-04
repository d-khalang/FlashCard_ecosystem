export type ApiErrorKind =
  | 'auth' // 401 auth_required
  | 'forbidden' // 403 not_allowed
  | 'not_found' // 404
  | 'invalid' // 422
  | 'rate_limited' // 429
  | 'unavailable' // 503 generation_failed
  | 'server' // other HTTP errors
  | 'network' // fetch failed: offline, DNS, TLS
  | 'bad_response'; // 2xx with a shape this client does not know

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly code: string | null;
  readonly retryAfter: number | null;

  constructor(kind: ApiErrorKind, message: string, opts: { status?: number; code?: string | null; retryAfter?: number | null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = opts.status ?? 0;
    this.code = opts.code ?? null;
    this.retryAfter = opts.retryAfter ?? null;
  }
}

const KIND_BY_CODE: Record<string, ApiErrorKind> = {
  auth_required: 'auth',
  not_allowed: 'forbidden',
  not_found: 'not_found',
  invalid_request: 'invalid',
  rate_limited: 'rate_limited',
  generation_failed: 'unavailable',
};

const KIND_BY_STATUS: Record<number, ApiErrorKind> = {
  401: 'auth',
  403: 'forbidden',
  404: 'not_found',
  422: 'invalid',
  429: 'rate_limited',
  503: 'unavailable',
};

export function kindFor(status: number, code: string | null): ApiErrorKind {
  return (code && KIND_BY_CODE[code]) || KIND_BY_STATUS[status] || 'server';
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

export function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError('server', e instanceof Error ? e.message : 'Unknown error');
}
