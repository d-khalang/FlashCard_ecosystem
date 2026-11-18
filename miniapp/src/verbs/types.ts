// Verbs page types, transcribed from docs/verbs/contract.md (§1 ids, §2 verb object, §4 Mini App API).
// `schema.ts` mirrors every type here; a test checks the contract fixtures against it.

export const MOODS = ['indicativo', 'congiuntivo', 'condizionale', 'imperativo'] as const;
export type Mood = (typeof MOODS)[number];

export const TENSES = [
  'presente',
  'imperfetto',
  'passato_remoto',
  'futuro_semplice',
  'passato_prossimo',
  'trapassato_prossimo',
  'trapassato_remoto',
  'futuro_anteriore',
  'passato',
  'trapassato',
] as const;
export type TenseName = (typeof TENSES)[number];

/** The 15 tense ids in canonical order (the order of `verb.tenses`). */
export const TENSE_IDS = [
  'indicativo-presente',
  'indicativo-imperfetto',
  'indicativo-passato_remoto',
  'indicativo-futuro_semplice',
  'indicativo-passato_prossimo',
  'indicativo-trapassato_prossimo',
  'indicativo-trapassato_remoto',
  'indicativo-futuro_anteriore',
  'congiuntivo-presente',
  'congiuntivo-imperfetto',
  'congiuntivo-passato',
  'congiuntivo-trapassato',
  'condizionale-presente',
  'condizionale-passato',
  'imperativo-presente',
] as const;
export type TenseId = (typeof TENSE_IDS)[number];

export const PERSONS = ['1s', '2s', '3s', '1p', '2p', '3p'] as const;
export type Person = (typeof PERSONS)[number];

/** e.g. feminine, literary, regional, archaic, colloquial. The contract lists examples, so any string is accepted. */
export type FormTag = string;

export interface Auxiliary {
  verb: 'essere' | 'avere';
  primary: boolean;
  note: string | null;
}

/** Each may be null (essere has no present participle). */
export interface PrincipalForms {
  gerund: string | null;
  past_participle: string | null;
  present_participle: string | null;
}

export interface SimpleParts {
  kind: 'simple';
  clitic: string | null;
  stem: string;
  ending: string;
  /** Pronouns attached after the verb, mostly in imperatives: svegli|a|ti, v|a|ttene. */
  enclitic: string | null;
  irregular_stem: boolean;
  irregular_ending: boolean;
}

export interface CompoundParts {
  kind: 'compound';
  clitic: string | null;
  auxiliary_verb: 'essere' | 'avere';
  auxiliary: string;
  participle: string;
  irregular_participle: boolean;
}

export interface Form {
  text: string;
  primary: boolean;
  tags: FormTag[];
  tts: string;
  irregular: boolean;
  parts: SimpleParts | CompoundParts;
}

export interface Slot {
  person: Person;
  /** Empty: the form does not exist (defective verb). */
  forms: Form[];
}

export interface Tense {
  id: TenseId;
  mood: Mood;
  tense: TenseName;
  compound: boolean;
  slots: Slot[];
}

export interface Verb {
  infinitive: string;
  pronominal: string | null;
  auxiliaries: Auxiliary[];
  principal_forms: PrincipalForms;
  irregular: boolean;
  data_version: string;
  tenses: Tense[];
}

export interface MatchSlot {
  tense_id: TenseId;
  person: Person;
}

export interface Match {
  query: string;
  kind: 'infinitive' | 'form' | 'fuzzy';
  slots: MatchSlot[];
  candidates: string[];
}

// §4 Mini App API

export interface CollectionVerb {
  infinitive: string;
  expression_id: string;
  meaning: string;
}

export interface VerbHome {
  recent: string[];
  collection: CollectionVerb[];
}

export interface VerbSuggest {
  items: string[];
}

export interface LookupFound {
  status: 'found';
  match: Match;
  verb: Verb;
  level_tenses: TenseId[];
  meaning: string | null;
  in_collection: boolean;
}

export interface LookupNotFound {
  status: 'not_found';
  query: string;
  suggestions: string[];
}

export interface LookupInvalid {
  status: 'invalid';
  query: string;
}

export type LookupResult = LookupFound | LookupNotFound | LookupInvalid;

export type AcceptedNote = 'feminine' | 'variant';

export interface Accepted {
  text: string;
  note: AcceptedNote | null;
}

export type DrillHint = { kind: 'irregular_stem'; stem: string } | { kind: 'irregular_form' };

export interface DrillItem {
  person: Person;
  primary: string;
  accepted: Accepted[];
  accepted_plain: string[];
  hint: DrillHint | null;
}

export interface Drill {
  infinitive: string;
  tense_id: TenseId;
  /** Longest first; the first one that matches is dropped from the answer. */
  strip_prefixes: string[];
  items: DrillItem[];
}

export interface PracticeRequest {
  infinitive: string;
  tense_id: TenseId;
  score: number;
  out_of: number;
  missed: Person[];
}

export interface VerbExample {
  tense_id: TenseId;
  person: Person;
  text: string;
  translation: string;
}

export type ExamplesResult =
  | { status: 'ready'; examples: VerbExample[] }
  | { status: 'pending'; retry_after: number }
  | { status: 'unavailable' };

export const MAX_VERB_QUERY_CHARS = 60;

export function isTenseId(value: string): value is TenseId {
  return (TENSE_IDS as readonly string[]).includes(value);
}
