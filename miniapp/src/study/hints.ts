import type { TranslationKey } from '../i18n/en';
import type { StudyPhase } from './reducer';

/** What the user does that can dismiss a hint. */
export type HintAction = 'reveal' | 'grade' | 'refresh';

export interface Hint {
  /** Stable id stored in localStorage. Never reuse or rename one. */
  id: string;
  /** The hint only shows while the study screen is in this phase. */
  phase: Extract<StudyPhase, 'question' | 'answer'>;
  text: TranslationKey;
  /** Doing any of these counts as having understood it. */
  dismissOn: readonly HintAction[];
}

/**
 * The hints in the order they are introduced. Adding one later is one entry here and one text key
 * in each dictionary. Only the first unseen hint can show, and only in its own phase, so a hint
 * whose phase is not current holds the ones behind it back.
 */
export const HINTS: readonly Hint[] = [
  { id: 'reveal', phase: 'question', text: 'study.hint.reveal', dismissOn: ['reveal'] },
  { id: 'grades', phase: 'answer', text: 'study.hint.grades', dismissOn: ['grade'] },
  { id: 'refresh', phase: 'answer', text: 'study.hint.refresh', dismissOn: ['refresh'] },
];

export const HINTS_STORAGE_KEY = 'kartino.study-hints.v1';

/**
 * Ids seen during this page view. Storage can be blocked, so this copy keeps a dismissed hint
 * dismissed when the study screen unmounts and mounts again. It only ever grows.
 */
let seenThisPageView = new Set<string>();

/** For tests: forget what this page view has seen. */
export function resetSeenHintsMemory(): void {
  seenThisPageView = new Set();
}

/** The ids already seen: this page view plus storage. Never throws: unavailable or damaged storage adds nothing. */
export function loadSeenHints(hints: readonly Hint[] = HINTS): Set<string> {
  const seen = new Set(seenThisPageView);
  try {
    const raw = localStorage.getItem(HINTS_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      const known = new Set(hints.map((h) => h.id));
      for (const id of parsed) if (typeof id === 'string' && known.has(id)) seen.add(id);
    }
  } catch {
    // Blocked or damaged storage: the in-memory copy still applies.
  }
  return seen;
}

/** Remembers in memory first, then best effort in storage (it can be full, blocked or missing). */
export function saveSeenHints(seen: ReadonlySet<string>): void {
  for (const id of seen) seenThisPageView.add(id);
  try {
    localStorage.setItem(HINTS_STORAGE_KEY, JSON.stringify([...seenThisPageView]));
  } catch {
    // Ignored on purpose: the in-memory copy above already holds it.
  }
}

/** The hint to show now, if any: the first unseen one, and only when its phase is current. */
export function currentHint(seen: ReadonlySet<string>, phase: StudyPhase, hints: readonly Hint[] = HINTS): Hint | null {
  const first = hints.find((h) => !seen.has(h.id));
  return first && first.phase === phase ? first : null;
}

/** The set after the user did `action` while `shown` was visible. */
export function afterAction(seen: ReadonlySet<string>, shown: Hint | null, action: HintAction): ReadonlySet<string> {
  if (!shown || !shown.dismissOn.includes(action)) return seen;
  return new Set(seen).add(shown.id);
}
