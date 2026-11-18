// Display labels from contract ids. The data never carries labels (contract §1).
import type { TranslationKey } from '../i18n/en';
import { MOODS, TENSE_IDS, type Mood, type Person, type TenseId } from './types';

export const moodKey = (mood: Mood) => `verbs.mood.${mood}` as const satisfies TranslationKey;
export const tenseKey = (id: TenseId) => `verbs.tense.${id}` as const satisfies TranslationKey;

/** io, tu…; che io… in the congiuntivo; (tu), (Lei)… in the imperativo. */
export function personKey(mood: Mood, person: Person): TranslationKey {
  if (mood === 'congiuntivo') return `verbs.personCong.${person}`;
  if (mood === 'imperativo') return `verbs.personImp.${person}`;
  return `verbs.person.${person}`;
}

export function moodOf(id: TenseId): Mood {
  return id.slice(0, id.indexOf('-')) as Mood;
}

/** Canonical position, for sorting. */
export const tenseIndex = (id: TenseId) => TENSE_IDS.indexOf(id);

export const MOOD_ORDER: readonly Mood[] = MOODS;
