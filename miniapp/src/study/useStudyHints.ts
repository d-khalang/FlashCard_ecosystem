import { useCallback, useState } from 'react';
import { afterAction, currentHint, loadSeenHints, saveSeenHints, type Hint, type HintAction } from './hints';
import type { StudyPhase } from './reducer';

/**
 * One-time study hints. The seen set lives in state, so hints still behave for this page view when
 * storage is unavailable; storage only carries the set across visits.
 */
export function useStudyHints(phase: StudyPhase): {
  hint: Hint | null;
  dismiss: () => void;
  onAction: (action: HintAction) => void;
} {
  const [seen, setSeen] = useState<ReadonlySet<string>>(loadSeenHints);
  const hint = currentHint(seen, phase);

  const mark = useCallback(
    (action: HintAction | 'close') => {
      if (!hint) return;
      const next = action === 'close' ? new Set(seen).add(hint.id) : afterAction(seen, hint, action);
      if (next === seen) return;
      setSeen(next);
      saveSeenHints(next);
    },
    [hint, seen],
  );

  const dismiss = useCallback(() => mark('close'), [mark]);
  return { hint, dismiss, onAction: mark };
}
