import { describe, expect, it } from 'vitest';
import { verbFixtures } from '../dev/verbFixtures';
import { check, drillSchema, examplesSchema, homeSchema, lookupSchema, practiceSchema, suggestSchema, type Schema } from './schema';

// Fixture file name prefix -> the schema (and so the type) it must match. A new fixture without an entry fails.
const SCHEMA_BY_PREFIX: Array<[string, Schema]> = [
  ['drill-', drillSchema],
  ['examples-', examplesSchema],
  ['home', homeSchema],
  ['lookup-', lookupSchema],
  ['practice-request', practiceSchema],
  ['suggest-', suggestSchema],
];

const schemaFor = (name: string) => SCHEMA_BY_PREFIX.find(([prefix]) => name.startsWith(prefix))?.[1];

describe('contract fixtures', () => {
  const names = Object.keys(verbFixtures).sort();

  it('finds the fixture folder', () => {
    expect(names).toEqual(
      expect.arrayContaining(['drill-andare-futuro_semplice.json', 'home.json', 'lookup-vado.json', 'practice-request.json', 'suggest-and.json']),
    );
  });

  it.each(names)('%s matches its type exactly', (name) => {
    const schema = schemaFor(name);
    expect(schema, `no schema for ${name}`).toBeDefined();
    expect(check(schema!, verbFixtures[name])).toEqual([]);
  });

  it('covers every lookup and examples status', () => {
    const statuses = (prefix: string) =>
      names.filter((n) => n.startsWith(prefix)).map((n) => (verbFixtures[n] as { status: string }).status).sort();
    expect(statuses('lookup-')).toEqual(['found', 'invalid', 'not_found']);
    expect(statuses('examples-')).toEqual(['pending', 'ready', 'unavailable']);
  });
});

describe('check', () => {
  it('reports missing keys, extra keys and wrong literals', () => {
    const errors = check(suggestSchema, { item: [] });
    expect(errors).toEqual(['$.items: missing', '$.item: extra key']);
    expect(check(practiceSchema, { infinitive: 'a', tense_id: 'indicativo-futuro', score: 1, out_of: 2, missed: ['4s'] })).toEqual([
      expect.stringContaining('$.tense_id: expected one of'),
      expect.stringContaining('$.missed[0]: expected one of'),
    ]);
  });
});
