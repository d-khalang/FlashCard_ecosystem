// A runtime mirror of the types in types.ts. `check` reports missing keys, extra keys and wrong values,
// so the fixture test fails on any drift between the contract fixtures and our types. The `Same` lines at
// the bottom make the compiler fail when a schema and its type disagree.

import {
  MOODS,
  PERSONS,
  TENSES,
  TENSE_IDS,
  type Drill,
  type ExamplesResult,
  type LookupResult,
  type PracticeRequest,
  type Verb,
  type VerbHome,
  type VerbSuggest,
} from './types';

export type Schema =
  | { readonly kind: 'string' }
  | { readonly kind: 'number' }
  | { readonly kind: 'boolean' }
  | { readonly kind: 'null' }
  | { readonly kind: 'literal'; readonly values: readonly string[] }
  | { readonly kind: 'array'; readonly of: Schema }
  | { readonly kind: 'object'; readonly props: { readonly [key: string]: Schema } }
  | { readonly kind: 'union'; readonly of: readonly Schema[] };

const str = { kind: 'string' } as const;
const num = { kind: 'number' } as const;
const bool = { kind: 'boolean' } as const;
const nul = { kind: 'null' } as const;
const lit = <const T extends readonly string[]>(...values: T) => ({ kind: 'literal', values }) as const;
const arr = <const T extends Schema>(of: T) => ({ kind: 'array', of }) as const;
const obj = <const P extends { readonly [key: string]: Schema }>(props: P) => ({ kind: 'object', props }) as const;
const union = <const T extends readonly Schema[]>(...of: T) => ({ kind: 'union', of }) as const;
const nullable = <const T extends Schema>(s: T) => union(s, nul);

export type Infer<S> = S extends { kind: 'string' }
  ? string
  : S extends { kind: 'number' }
    ? number
    : S extends { kind: 'boolean' }
      ? boolean
      : S extends { kind: 'null' }
        ? null
        : S extends { kind: 'literal'; values: infer V extends readonly string[] }
          ? V[number]
          : S extends { kind: 'array'; of: infer T }
            ? Infer<T>[]
            : S extends { kind: 'object'; props: infer P }
              ? { -readonly [K in keyof P]: Infer<P[K]> }
              : S extends { kind: 'union'; of: infer U extends readonly Schema[] }
                ? Infer<U[number]>
                : never;

const tenseId = lit(...TENSE_IDS);
const person = lit(...PERSONS);
const auxVerb = lit('essere', 'avere');

const form = obj({
  text: str,
  primary: bool,
  tags: arr(str),
  tts: str,
  irregular: bool,
  parts: union(
    obj({ kind: lit('simple'), clitic: nullable(str), stem: str, ending: str, enclitic: nullable(str), irregular_stem: bool, irregular_ending: bool }),
    obj({
      kind: lit('compound'),
      clitic: nullable(str),
      auxiliary_verb: auxVerb,
      auxiliary: str,
      participle: str,
      irregular_participle: bool,
    }),
  ),
});

export const verbSchema = obj({
  infinitive: str,
  pronominal: nullable(str),
  auxiliaries: arr(obj({ verb: auxVerb, primary: bool, note: nullable(str) })),
  principal_forms: obj({ gerund: nullable(str), past_participle: nullable(str), present_participle: nullable(str) }),
  irregular: bool,
  data_version: str,
  tenses: arr(
    obj({
      id: tenseId,
      mood: lit(...MOODS),
      tense: lit(...TENSES),
      compound: bool,
      slots: arr(obj({ person, forms: arr(form) })),
    }),
  ),
});

export const homeSchema = obj({
  recent: arr(str),
  collection: arr(obj({ infinitive: str, expression_id: str, meaning: str })),
});

export const suggestSchema = obj({ items: arr(str) });

export const lookupSchema = union(
  obj({
    status: lit('found'),
    match: obj({
      query: str,
      kind: lit('infinitive', 'form', 'fuzzy'),
      slots: arr(obj({ tense_id: tenseId, person })),
      candidates: arr(str),
    }),
    verb: verbSchema,
    level_tenses: arr(tenseId),
    meaning: nullable(str),
    in_collection: bool,
  }),
  obj({ status: lit('not_found'), query: str, suggestions: arr(str) }),
  obj({ status: lit('invalid'), query: str }),
);

export const drillSchema = obj({
  infinitive: str,
  tense_id: tenseId,
  strip_prefixes: arr(str),
  items: arr(
    obj({
      person,
      primary: str,
      accepted: arr(obj({ text: str, note: nullable(lit('feminine', 'variant')) })),
      accepted_plain: arr(str),
      hint: union(obj({ kind: lit('irregular_stem'), stem: str }), obj({ kind: lit('irregular_form') }), nul),
    }),
  ),
});

export const practiceSchema = obj({ infinitive: str, tense_id: tenseId, score: num, out_of: num, missed: arr(person) });

export const examplesSchema = union(
  obj({ status: lit('ready'), examples: arr(obj({ tense_id: tenseId, person, text: str, translation: str })) }),
  obj({ status: lit('pending'), retry_after: num }),
  obj({ status: lit('unavailable') }),
);

/** Every problem found, as `path: message`. Empty when `value` matches `schema` exactly. */
export function check(schema: Schema, value: unknown, path = '$'): string[] {
  switch (schema.kind) {
    case 'string':
    case 'number':
    case 'boolean':
      return typeof value === schema.kind ? [] : [`${path}: expected ${schema.kind}, got ${JSON.stringify(value)}`];
    case 'null':
      return value === null ? [] : [`${path}: expected null, got ${JSON.stringify(value)}`];
    case 'literal':
      return typeof value === 'string' && schema.values.includes(value)
        ? []
        : [`${path}: expected one of ${schema.values.join('|')}, got ${JSON.stringify(value)}`];
    case 'array':
      return Array.isArray(value) ? value.flatMap((v, i) => check(schema.of, v, `${path}[${i}]`)) : [`${path}: expected array`];
    case 'object': {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return [`${path}: expected object`];
      const rec = value as Record<string, unknown>;
      const errors: string[] = [];
      for (const key of Object.keys(schema.props)) {
        if (!(key in rec)) errors.push(`${path}.${key}: missing`);
        else errors.push(...check(schema.props[key]!, rec[key], `${path}.${key}`));
      }
      for (const key of Object.keys(rec)) if (!(key in schema.props)) errors.push(`${path}.${key}: extra key`);
      return errors;
    }
    case 'union': {
      const results = schema.of.map((s) => check(s, value, path));
      if (results.some((r) => r.length === 0)) return [];
      // Report against the member with the fewest problems: usually the one the value meant to be.
      return results.reduce((best, r) => (r.length < best.length ? r : best));
    }
  }
}

// Compile-time: each schema infers exactly its contract type.
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
const assertSame = <T extends true>(): T | undefined => undefined;
assertSame<Same<Infer<typeof verbSchema>, Verb>>();
assertSame<Same<Infer<typeof homeSchema>, VerbHome>>();
assertSame<Same<Infer<typeof suggestSchema>, VerbSuggest>>();
assertSame<Same<Infer<typeof lookupSchema>, LookupResult>>();
assertSame<Same<Infer<typeof drillSchema>, Drill>>();
assertSame<Same<Infer<typeof practiceSchema>, PracticeRequest>>();
assertSame<Same<Infer<typeof examplesSchema>, ExamplesResult>>();
