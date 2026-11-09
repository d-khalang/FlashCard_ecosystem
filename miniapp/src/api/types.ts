// Types transcribed from docs/mini-app.md (API section).

export type Direction = 'forward' | 'reverse';
export type ReviewMode = 'standard' | 'dual';
export type Section = 'definition' | 'translations' | 'example';
export type AudioPart = 'word' | 'definition' | 'example' | 'translation_0' | 'translation_1';
export type Grade = 0 | 1 | 2 | 3 | 4 | 5;

export interface Translation {
  label: string;
  /** Lowercase country code for the flag, from the label's flag emoji. */
  country: string | null;
  text: string;
}

export interface Content {
  definition: string | null;
  translations: Translation[];
  example: string | null;
  note: string | null;
}

export interface StudyCard extends Content {
  delivery_id: number;
  expression_id: string;
  value: string;
  direction: Direction;
  from_storage: boolean;
  older_settings: boolean;
}

export interface Settings {
  target_level: string;
  primary_language: string;
  secondary_language: string | null;
  review_mode: ReviewMode;
  review_interval_minutes: number;
  is_active: boolean;
}

export interface QuotaResult {
  status: 'quota';
  tier: string;
  /** Today's credit limit. */
  limit: number;
}

export interface LanguageInfo {
  code: string;
  name: string;
  country: string | null;
}

export interface Me {
  language: LanguageInfo;
  settings: Settings;
  /** Today's card credits; `limit` is null when nothing limits the user. Refills at 00:00 UTC. */
  quota: { used: number; limit: number | null; card_cost: number; section_cost: number };
  /** False until the user has started the bot chat, so reminders cannot be delivered. */
  reminders_available: boolean;
  words: { total: number; ready: number; /** A card is waiting for an answer. */ pending: boolean };
  options: {
    levels: string[];
    languages: LanguageInfo[];
    min_interval: number;
    max_interval: number;
  };
}

export interface CurrentResponse {
  card: StudyCard | null;
  undo_available: boolean;
}

export type NextResult = { status: 'ready'; card: StudyCard } | { status: 'none' } | QuotaResult;

export type GradeResult = { status: 'graded'; undo_available: boolean } | { status: 'not_pending' };

export type UndoResult = { status: 'undone'; card: StudyCard } | { status: 'nothing_to_undo' };

export type RefreshResult = { status: 'ready'; card: StudyCard } | { status: 'not_pending' } | QuotaResult;

export type PreviewResult =
  | { status: 'ready'; norm: string; content: Content }
  | { status: 'unclear'; note: string | null; suggestions: string[] }
  | { status: 'invalid'; suggestions: string[] }
  | QuotaResult;

export interface CollectionItem {
  id: string;
  value: string;
  reps: number;
  lapses: number;
  created_at: string | null;
}

export interface CollectionPage {
  items: CollectionItem[];
  next_cursor: string | null;
}

export type SaveResult =
  | { status: 'saved' | 'already_saved' }
  | { status: 'invalid'; suggestions: string[] }
  | { status: 'too_many'; limit: number };

export interface CollectionDetail {
  id: string;
  value: string;
  reps: number;
  lapses: number;
  created_at: string | null;
  content: Content | null;
  generated_at: string | null;
}

export type ImportResult =
  | { status: 'imported'; items: string[] }
  | { status: 'all_duplicates' | 'parse_failed' | 'nothing_found' | 'invalid_language' }
  | { status: 'too_long'; limit: number }
  | { status: 'too_many'; limit: number }
  | QuotaResult;

export const MAX_IMPORT_CHARS = 1000;
export const MAX_WORD_CHARS = 200;
export const MIN_SEARCH_CHARS = 2;

/** Compile-time exhaustiveness check for union switches. */
export function assertNever(value: never): never {
  throw new Error(`Unhandled case: ${JSON.stringify(value)}`);
}
