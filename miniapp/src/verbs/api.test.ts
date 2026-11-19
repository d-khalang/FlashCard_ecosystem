import { describe, expect, it, vi } from 'vitest';
import { createClient } from '../api/client';
import { ApiError } from '../api/errors';
import { createApi } from '../api/routes';
import { fixture } from '../dev/verbFixtures';

function fakeFetch(status: number, body: unknown) {
  return vi.fn(async (_url: unknown, _init?: RequestInit) => new Response(status === 204 ? null : JSON.stringify(body), { status }));
}
const make = (f: ReturnType<typeof fakeFetch>) =>
  createApi(createClient({ baseUrl: './api/v1', getInitData: () => 'x', fetch: f as unknown as typeof fetch })).verbs;

describe('verbs api', () => {
  it('builds the contract routes', async () => {
    const f = fakeFetch(200, fixture('lookup-vado.json'));
    const api = make(f);
    await api.lookup('me ne vado');
    expect(f.mock.calls[0]![0]).toBe('./api/v1/verbs/lookup?q=me%20ne%20vado');

    const g = fakeFetch(200, fixture('drill-andare-futuro_semplice.json'));
    await make(g).drill('andare', 'indicativo-futuro_semplice');
    expect(g.mock.calls[0]![0]).toBe('./api/v1/verbs/andare/drill/indicativo-futuro_semplice');

    const h = fakeFetch(200, { items: [] });
    await make(h).suggest('and');
    expect(h.mock.calls[0]![0]).toBe('./api/v1/verbs/suggest?q=and');
  });

  it('posts practice and accepts 204', async () => {
    const f = fakeFetch(204, null);
    const body = fixture<Parameters<ReturnType<typeof make>['practice']>[0]>('practice-request.json');
    await expect(make(f).practice(body)).resolves.toBeUndefined();
    const [url, init] = f.mock.calls[0]!;
    expect(url).toBe('./api/v1/verbs/practice');
    expect(JSON.parse(String(init!.body))).toEqual(body);
  });

  it('rejects an unknown lookup status', async () => {
    await expect(make(fakeFetch(200, { status: 'maybe' })).lookup('x')).rejects.toBeInstanceOf(ApiError);
  });
});
