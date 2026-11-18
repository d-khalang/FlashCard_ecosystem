// Drill grading, exactly contract §4. The server sends every accepted answer; this only compares.
import type { AcceptedNote, Drill, DrillItem } from './types';

export type Verdict =
  | { result: 'right'; note: AcceptedNote | null }
  /** Right except for accents: the answer counts, with "accent: {primary}". */
  | { result: 'accent' }
  | { result: 'wrong' };

/** Step 1: NFC, lowercase, trim, collapse spaces, typographic apostrophes (’ and ‘) to plain. */
export function normalizeAnswer(input: string): string {
  return input.normalize('NFC').toLowerCase().trim().replace(/\s+/g, ' ').replace(/[\u2018\u2019]/g, "'");
}

/** Accents removed: NFD, then drop U+0300-U+036F. */
export function stripAccents(text: string): string {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

/** Step 2: drop the first listed prefix that is followed by a space. */
export function stripPrefix(n: string, prefixes: readonly string[]): string {
  for (const p of prefixes) {
    if (n.startsWith(`${p} `)) return n.slice(p.length + 1);
  }
  return n;
}

export function gradeAnswer(input: string, item: DrillItem, stripPrefixes: Drill['strip_prefixes']): Verdict {
  const n = stripPrefix(normalizeAnswer(input), stripPrefixes);
  const exact = item.accepted.find((a) => a.text === n);
  if (exact) return { result: 'right', note: exact.note };
  if (item.accepted_plain.includes(stripAccents(n))) return { result: 'accent' };
  return { result: 'wrong' };
}

/** Right and accent both count as correct. */
export const counts = (v: Verdict): boolean => v.result !== 'wrong';
