import { describe, expect, it, vi } from 'vitest';
import { createClient } from './client';
import { ApiError } from './errors';
import { createApi } from './routes';

function fakeFetch(res: { status?: number; body?: unknown; headers?: Record<string, string>; throws?: boolean }) {
  return vi.fn(async (_url: unknown, _init?: RequestInit) => {
    if (res.throws) throw new TypeError('Failed to fetch');
    const status = res.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(res.body ?? {}), { status, headers: res.headers });
  });
}

const make = (f: ReturnType<typeof fakeFetch>, onUnauthorized?: () => void) =>
  createApi(createClient({ baseUrl: './api/v1', getInitData: () => 'user=1&hash=abc', fetch: f as unknown as typeof fetch, onUnauthorized }));

describe('client', () => {
  it('sends the tma Authorization header and a relative URL', async () => {
    const f = fakeFetch({ body: { words: { total: 1, ready: 1 } } });
    await make(f).me();
    const [url, init] = f.mock.calls[0]!;
    expect(url).toBe('./api/v1/me');
    expect((init!.headers as Record<string, string>).Authorization).toBe('tma user=1&hash=abc');
  });

  it('encodes query params and skips empty ones', async () => {
    const f = fakeFetch({ body: { items: [], next_cursor: null } });
    await make(f).collection({ limit: 30, q: 'a b', cursor: null });
    expect(f.mock.calls[0]![0]).toBe('./api/v1/collection?limit=30&q=a%20b');
  });

  it('sends JSON bodies', async () => {
    const f = fakeFetch({ body: { status: 'graded', undo_available: true } });
    await make(f).grade({ delivery_id: -5, expression_id: 'e', direction: 'forward', grade: 3 });
    const init = f.mock.calls[0]![1]!;
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ delivery_id: -5, expression_id: 'e', direction: 'forward', grade: 3 });
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it.each([
    [401, 'auth_required', 'auth'],
    [403, 'not_allowed', 'forbidden'],
    [404, 'not_found', 'not_found'],
    [422, 'invalid_request', 'invalid'],
    [429, 'rate_limited', 'rate_limited'],
    [503, 'generation_failed', 'unavailable'],
    [500, 'boom', 'server'],
  ])('maps %s %s to %s', async (status, code, kind) => {
    const f = fakeFetch({ status, body: { error: { code, message: 'msg' } }, headers: status === 429 ? { 'Retry-After': '7' } : undefined });
    const e = await make(f)
      .me()
      .catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).kind).toBe(kind);
    expect((e as ApiError).message).toBe('msg');
    if (status === 429) expect((e as ApiError).retryAfter).toBe(7);
  });

  it('maps by status when the body is not JSON', async () => {
    const f = vi.fn(async () => new Response('<html>', { status: 503 }));
    const e = await make(f as never)
      .me()
      .catch((x: unknown) => x);
    expect((e as ApiError).kind).toBe('unavailable');
  });

  it('calls onUnauthorized on 401 only', async () => {
    const spy = vi.fn();
    await make(fakeFetch({ status: 401, body: { error: { code: 'auth_required', message: 'x' } } }), spy)
      .me()
      .catch(() => undefined);
    expect(spy).toHaveBeenCalledTimes(1);
    await make(fakeFetch({ status: 429, body: { error: { code: 'rate_limited', message: 'x' } } }), spy)
      .me()
      .catch(() => undefined);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('reports a failed fetch as a network error', async () => {
    const e = await make(fakeFetch({ throws: true }))
      .me()
      .catch((x: unknown) => x);
    expect((e as ApiError).kind).toBe('network');
  });

  it('handles 204 for DELETE and 202 for prepare', async () => {
    const f = fakeFetch({ status: 204 });
    await expect(make(f).remove('a/b')).resolves.toBeUndefined();
    expect(f.mock.calls[0]![0]).toBe('./api/v1/collection/a%2Fb');
    expect((f.mock.calls[0]![1] as RequestInit).method).toBe('DELETE');
    await expect(make(fakeFetch({ status: 202, body: {} })).prepare()).resolves.toBeUndefined();
  });
});

describe('union parsing', () => {
  const card = {
    delivery_id: -1,
    expression_id: 'e',
    value: 'v',
    direction: 'forward',
    from_storage: false,
    older_settings: false,
    definition: null,
    translations: [],
    example: null,
    note: null,
  };

  it('accepts every documented status', async () => {
    expect(await make(fakeFetch({ body: { status: 'ready', card } })).next()).toMatchObject({ status: 'ready' });
    expect(await make(fakeFetch({ body: { status: 'none' } })).next()).toEqual({ status: 'none' });
    expect(await make(fakeFetch({ body: { status: 'quota', tier: 'free', limit: 20 } })).next()).toMatchObject({ status: 'quota', limit: 20 });
    expect(await make(fakeFetch({ body: { status: 'unclear', note: 'n', suggestions: ['a'] } })).preview('x')).toMatchObject({ status: 'unclear' });
    expect(await make(fakeFetch({ body: { status: 'too_long', limit: 1000 } })).importText('x')).toMatchObject({ status: 'too_long' });
    expect(await make(fakeFetch({ body: { status: 'nothing_to_undo' } })).undo()).toEqual({ status: 'nothing_to_undo' });
  });

  it('rejects an unknown status', async () => {
    const e = await make(fakeFetch({ body: { status: 'surprise' } }))
      .grade({ delivery_id: 1, expression_id: 'e', direction: 'forward', grade: 1 })
      .catch((x: unknown) => x);
    expect((e as ApiError).kind).toBe('bad_response');
  });

  it('rejects a ready response without a card', async () => {
    const e = await make(fakeFetch({ body: { status: 'ready' } }))
      .next()
      .catch((x: unknown) => x);
    expect((e as ApiError).kind).toBe('bad_response');
  });
});
