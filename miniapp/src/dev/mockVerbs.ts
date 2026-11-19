// Development-only fake of the /verbs routes, built on the contract fixtures. See mockFetch.ts.
import { stripAccents } from '../verbs/grade';
import type { Drill, LookupFound, LookupResult, MatchSlot, TenseId, VerbHome } from '../verbs/types';
import { fixture } from './verbFixtures';

const INFINITIVES = [
  'andare', 'andarsene', 'andicappare', 'essere', 'avere', 'fare', 'dire', 'potere', 'volere', 'sapere', 'stare',
  'dovere', 'vedere', 'venire', 'uscire', 'prendere', 'parlare', 'mangiare', 'dormire', 'finire', 'svegliarsi',
];

type Json = (status: number, body: unknown) => Response;
type Err = (status: number, code: string, message: string) => Response;

const recent: string[] = fixture<VerbHome>('home.json').recent;

function found(q: string): LookupResult {
  const base = fixture<LookupFound>('lookup-vado.json');
  const verb = base.verb;
  const n = q.trim().toLowerCase();
  if (n === verb.infinitive) return { ...base, match: { query: q, kind: 'infinitive', slots: [], candidates: ['andarsene'] } };
  if (n === 'andre' || n === 'andar') return { ...base, match: { query: q, kind: 'fuzzy', slots: [], candidates: [] } };
  const slots: MatchSlot[] = [];
  for (const t of verb.tenses)
    for (const s of t.slots) if (s.forms.some((f) => f.text === n)) slots.push({ tense_id: t.id, person: s.person });
  if (slots.length) return { ...base, match: { query: q, kind: 'form', slots, candidates: n === 'vado' ? ['andarsene'] : [] } };
  if (!/^[\p{L}' ]+$/u.test(n)) return { status: 'invalid', query: q };
  const suggestions = INFINITIVES.filter((v) => v !== n && v.startsWith(n.slice(0, 2))).slice(0, 4);
  return { status: 'not_found', query: q, suggestions };
}

/** A drill made from the verb fixture for tenses that have no drill fixture. */
function drill(tenseId: TenseId): Drill | null {
  if (tenseId === 'indicativo-futuro_semplice') return fixture('drill-andare-futuro_semplice.json');
  if (tenseId === 'indicativo-passato_prossimo') return fixture('drill-andare-passato_prossimo.json');
  const tense = fixture<LookupFound>('lookup-vado.json').verb.tenses.find((t) => t.id === tenseId);
  if (!tense) return null;
  const { strip_prefixes } = fixture<Drill>('drill-andare-futuro_semplice.json');
  return {
    infinitive: 'andare',
    tense_id: tenseId,
    strip_prefixes,
    items: tense.slots
      .filter((s) => s.forms.length > 0)
      .map((s) => {
        const primary = s.forms.find((f) => f.primary) ?? s.forms[0]!;
        return {
          person: s.person,
          primary: primary.text,
          accepted: s.forms.map((f) => ({ text: f.text, note: f.primary ? null : f.tags.includes('feminine') ? 'feminine' : 'variant' })),
          accepted_plain: [...new Set(s.forms.map((f) => stripAccents(f.text)))],
          hint: primary.irregular ? { kind: 'irregular_form' } : null,
        };
      }),
  };
}

export async function mockVerbs(
  path: string,
  query: URLSearchParams,
  method: string,
  body: Record<string, unknown>,
  json: Json,
  err: Err,
  sleep: (ms: number) => Promise<unknown>,
): Promise<Response> {
  const q = query.get('q') ?? '';
  if (path === '/verbs/home') return json(200, { ...fixture<VerbHome>('home.json'), recent });
  if (path === '/verbs/suggest') {
    const n = q.trim().toLowerCase();
    return json(200, { items: n.length < 2 ? [] : INFINITIVES.filter((v) => v.startsWith(n)).slice(0, 8) });
  }
  if (path === '/verbs/lookup') {
    await sleep(300);
    const r = found(q);
    if (r.status === 'found') {
      const i = recent.indexOf(r.verb.infinitive);
      if (i >= 0) recent.splice(i, 1);
      recent.unshift(r.verb.infinitive);
      recent.splice(10);
    }
    return json(200, r);
  }
  if (path === '/verbs/practice' && method === 'POST') {
    console.info('[mock] practice', body);
    return json(204, null);
  }
  const d = /^\/verbs\/([^/]+)\/drill\/([^/]+)$/.exec(path);
  if (d) {
    const data = d[1] === 'andare' ? drill(decodeURIComponent(d[2]!) as TenseId) : null;
    return data ? json(200, data) : err(404, 'not_found', 'no such verb or tense');
  }
  const ex = /^\/verbs\/([^/]+)\/examples$/.exec(path);
  if (ex) return json(200, fixture('examples-ready.json'));
  return err(404, 'not_found', path);
}
