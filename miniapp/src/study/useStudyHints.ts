import { useCallback, useState, useSyncExternalStore } from 'react';
import { afterAction, currentHint, loadSeenHints, saveSeenHints, type Hint, type HintAction } from './hints';
import type { StudyPhase } from './reducer';

/** Below this height the answer needs all the room it can get, so hints step aside. */
export const SHORT_VIEWPORT_QUERY = '(max-height: 520px)';

function subscribeShort(onChange: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => undefined;
  const mq = window.matchMedia(SHORT_VIEWPORT_QUERY);
  mq.addEventListener('change', onChange);
  return () => mq.removeEventListener('change', onChange);
}

const isShort = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(SHORT_VIEWPORT_QUERY).matches;

/** True on a very short window, such as a phone held sideways. */
export function useShortViewport(): boolean {
  return useSyncExternalStore(subscribeShort, isShort, () => false);
}

/**
 * One-time study hints. The seen set lives in state (and in memory and storage, see hints.ts).
 * While `suppressed`, no hint shows and nothing is marked seen, so a hint is never used up unseen.
 * An answer-side hint that is closed or acted on leaves its card quiet: the next hint waits for the
 * next answer, so two hints never stack on one card.
 */
export function useStudyHints(
  phase: StudyPhase,
  suppressed = false,
  cardKey: number | null = null,
): {
  hint: Hint | null;
  dismiss: () => void;
  onAction: (action: HintAction) => void;
} {
  const [seen, setSeen] = useState<ReadonlySet<string>>(loadSeenHints);
  const [quietCard, setQuietCard] = useState<number | null>(null);
  const hint = suppressed || (cardKey !== null && cardKey === quietCard) ? null : currentHint(seen, phase);

  const mark = useCallback(
    (action: HintAction | 'close') => {
      if (!hint) return;
      const next = action === 'close' ? new Set(seen).add(hint.id) : afterAction(seen, hint, action);
      if (next === seen) return;
      setSeen(next);
      saveSeenHints(next);
      if (hint.phase === 'answer') setQuietCard(cardKey);
    },
    [hint, seen, cardKey],
  );

  const dismiss = useCallback(() => mark('close'), [mark]);
  return { hint, dismiss, onAction: mark };
}
