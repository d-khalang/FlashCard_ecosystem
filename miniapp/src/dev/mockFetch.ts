// Development-only fake API. Loaded by main.tsx behind `import.meta.env.DEV` and `?mock`,
// so it is not part of the production build.
//
// Query options: scenario=empty|caught|quota, long=1 (long word), reverse=1 (reverse cards),
// fail=grade|refresh|undo (make that route fail), slow=1 (add latency).

import type { Content, Me, StudyCard } from '../api/types';

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

const err = (status: number, code: string, message: string) => json(status, { error: { code, message } });

const CONTENT: Content = {
  definition: 'Grande distesa di acqua salata che copre gran parte della Terra.',
  translations: [
    { label: 'English', country: 'gb', text: 'sea' },
    { label: 'Persian', country: 'ir', text: 'دریا' },
  ],
  example: "D'estate andiamo sempre al mare con i bambini.",
  note: null,
};

const WORDS = ['il mare', 'la sedia', 'andare a gonfie vele', 'a seconda delle circostanze particolari del caso', 'la farfalla', 'il bicchiere', 'sebbene', 'fare una passeggiata', 'il gatto', 'la finestra', 'ottimo'];

export function createMockFetch(params: URLSearchParams): typeof fetch {
  const scenario = params.get('scenario') ?? 'normal';
  const slow = params.has('slow');
  const fail = params.get('fail');
  const reverse = params.has('reverse');
  const long = params.has('long');
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, slow ? ms * 6 : ms));

  const collection = WORDS.map((w, i) => ({ id: `w${i}`, value: w, reps: i, lapses: i % 3, created_at: '2026-10-01T10:00:00Z' }));
  let queue = scenario === 'normal' ? [...WORDS] : [];
  let n = 0;
  let current: StudyCard | null = null;
  let undo: StudyCard | null = null;

  const makeCard = (value: string): StudyCard => ({
    ...CONTENT,
    delivery_id: -(1000 + n++),
    expression_id: `w${n}`,
    value: long ? 'a seconda delle circostanze particolari del caso concreto' : value,
    direction: reverse ? 'reverse' : 'forward',
    from_storage: n % 3 === 0,
    older_settings: n % 4 === 0,
    example: value.length > 12 ? `${CONTENT.example} ${CONTENT.example} ${CONTENT.example}` : CONTENT.example,
  });

  const me = (): Me => ({
    language: { code: 'it', name: 'Italiano', country: 'it' },
    settings: settings,
    quota: scenario === 'quota' ? { used: 19, limit: 20 } : { used: 3, limit: 20 },
    words: { total: scenario === 'empty' ? 0 : 40, ready: queue.length },
    options: {
      levels: ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'],
      languages: [
        { code: 'en', name: 'English', country: 'gb' },
        { code: 'fa', name: 'Persian', country: 'ir' },
        { code: 'es', name: 'Spanish', country: 'es' },
        { code: 'fr', name: 'French', country: 'fr' },
        { code: 'de', name: 'German', country: 'de' },
        { code: 'ar', name: 'Arabic', country: 'sa' },
      ],
      min_interval: 30,
      max_interval: 1440,
    },
  });

  let settings: Me['settings'] = {
    target_level: 'B1',
    primary_language: 'en',
    secondary_language: 'fa',
    review_mode: 'standard',
    review_interval_minutes: 120,
    is_active: true,
  };

  return async (input, init) => {
    const url = new URL(String(input), 'http://mock.local/');
    const path = url.pathname.replace(/^.*\/api\/v1/, '');
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    await sleep(250);

    if (path === '/me') return json(200, me());
    if (path === '/study/current') return json(200, { card: current, undo_available: undo !== null });
    if (path === '/study/next') {
      if (scenario === 'quota') return json(200, { status: 'quota', tier: 'free', limit: 20 });
      if (!current) {
        const w = queue.shift();
        if (!w) return json(200, { status: 'none' });
        current = makeCard(w);
      }
      return json(200, { status: 'ready', card: current });
    }
    if (path === '/study/prepare') return json(202, {});
    if (path === '/study/grade') {
      if (fail === 'grade') return err(503, 'generation_failed', 'boom');
      undo = current;
      current = null;
      return json(200, { status: 'graded', undo_available: true });
    }
    if (path === '/study/undo') {
      if (fail === 'undo') return err(503, 'generation_failed', 'boom');
      if (!undo) return json(200, { status: 'nothing_to_undo' });
      current = undo;
      undo = null;
      return json(200, { status: 'undone', card: current });
    }
    if (path === '/study/refresh') {
      if (fail === 'refresh') return err(503, 'generation_failed', 'boom');
      await sleep(800);
      if (!current) return json(200, { status: 'not_pending' });
      const section = body.section as string;
      if (section === 'definition') current = { ...current, definition: 'Ampia distesa d’acqua salata (versione nuova).' };
      if (section === 'example') current = { ...current, example: 'Il mare è calmo stamattina.' };
      return json(200, { status: 'ready', card: current });
    }
    if (path === '/cards/preview') {
      const text = String(body.text ?? '');
      if (text === 'xx') return json(200, { status: 'invalid', suggestions: ['mare', 'marea'] });
      if (text === 'yy') return json(200, { status: 'unclear', note: 'Did you mean a different spelling?', suggestions: ['sedia', 'sedile'] });
      await sleep(600);
      return json(200, { status: 'ready', norm: text, content: CONTENT });
    }
    if (path === '/collection' && method === 'GET') {
      const q = url.searchParams.get('q');
      const items = q ? collection.filter((c) => c.value.includes(q)) : collection;
      return json(200, { items, next_cursor: null });
    }
    if (path === '/collection' && method === 'POST') return json(201, { status: 'saved' });
    if (path === '/collection/import') return json(200, { status: 'imported', items: String(body.text).split(/[\n,]/).filter(Boolean) });
    if (path === '/settings') {
      settings = { ...settings, ...(body as Partial<Me['settings']>) };
      if (body.target_level === 'C2') return err(422, 'invalid_request', 'nope');
      return json(200, settings);
    }
    const detail = /^\/collection\/(.+)$/.exec(path);
    if (detail) {
      if (method === 'DELETE') return json(204, null);
      const c = collection.find((x) => x.id === detail[1]);
      return c ? json(200, { ...c, content: CONTENT, generated_at: '2026-10-02T10:00:00Z' }) : err(404, 'not_found', 'gone');
    }
    return err(404, 'not_found', path);
  };
}
