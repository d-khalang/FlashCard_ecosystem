import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { Api } from '../api/routes';
import { asApiError } from '../api/errors';
import { assertNever, type Grade, type Section } from '../api/types';
import { initialStudyState, isCheckpoint, studyReducer } from './reducer';

type StudyApi = Pick<Api, 'current' | 'next' | 'prepare' | 'grade' | 'undo' | 'refresh'>;

export function useStudy(api: StudyApi) {
  const [state, dispatch] = useReducer(studyReducer, initialStudyState);
  const stateRef = useRef(state);
  stateRef.current = state;

  const alive = useRef(true);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const inFlight = useRef(0);
  const [busy, setBusy] = useState(false);

  /** Server calls that depend on each other (grade, next, undo) run strictly in order. */
  const run = useCallback((job: () => Promise<void>) => {
    inFlight.current += 1;
    setBusy(true);
    const p = queue.current.then(job);
    queue.current = p
      .catch(() => undefined)
      .finally(() => {
        inFlight.current -= 1;
        if (alive.current) setBusy(inFlight.current > 0);
      });
    return p;
  }, []);

  const loadNext = useCallback(async () => {
    dispatch({ type: 'loading' });
    try {
      const r = await api.next();
      if (!alive.current) return;
      switch (r.status) {
        case 'ready':
          dispatch({ type: 'card', card: r.card });
          return;
        case 'none':
          dispatch({ type: 'none' });
          return;
        case 'quota':
          dispatch({ type: 'quota', quota: r });
          return;
        default:
          assertNever(r);
      }
    } catch (e) {
      if (alive.current) dispatch({ type: 'failed', error: asApiError(e) });
    }
  }, [api]);

  const start = useCallback(
    () =>
      run(async () => {
        dispatch({ type: 'loading' });
        try {
          const cur = await api.current();
          if (!alive.current) return;
          if (cur.card) {
            dispatch({ type: 'card', card: cur.card, undoAvailable: cur.undo_available });
            return;
          }
          dispatch({ type: 'grade_confirmed', undoAvailable: cur.undo_available });
        } catch (e) {
          if (alive.current) dispatch({ type: 'failed', error: asApiError(e) });
          return;
        }
        await loadNext();
      }),
    [api, run, loadNext],
  );

  useEffect(() => {
    alive.current = true;
    void start();
    return () => {
      alive.current = false;
    };
  }, [start]);

  const reveal = useCallback(() => {
    const s = stateRef.current;
    if (s.phase !== 'question' || !s.card) return;
    dispatch({ type: 'reveal' });
    // Fire and forget, once per reveal: a repeated prepare is free on the server and a miss only costs speed.
    api.prepare().catch(() => undefined);
  }, [api]);

  const grade = useCallback(
    (g: Grade) => {
      const s = stateRef.current;
      const card = s.card;
      if (s.phase !== 'answer' || !card) return;
      const checkpoint = isCheckpoint(s.reviewed + 1);
      dispatch({ type: 'grade_optimistic' });
      void run(async () => {
        try {
          const r = await api.grade({
            delivery_id: card.delivery_id,
            expression_id: card.expression_id,
            direction: card.direction,
            grade: g,
          });
          if (!alive.current) return;
          switch (r.status) {
            case 'graded':
              dispatch({ type: 'grade_confirmed', undoAvailable: r.undo_available });
              if (!checkpoint) await loadNext();
              return;
            case 'not_pending':
              dispatch({ type: 'grade_skipped' });
              await loadNext();
              return;
            default:
              assertNever(r);
          }
        } catch (e) {
          if (!alive.current) return;
          const err = asApiError(e);
          if (err.kind === 'not_found') {
            // The card is gone on the server: nothing to retry, move on.
            dispatch({ type: 'grade_skipped' });
            await loadNext();
            return;
          }
          dispatch({ type: 'grade_rolled_back', card });
        }
      });
    },
    [api, run, loadNext],
  );

  const continueSession = useCallback(() => {
    void run(loadNext);
  }, [run, loadNext]);

  const undo = useCallback(() => {
    // Not while a grade or next card is in flight: a queued undo would spend a card on `next`
    // and a double tap would answer "nothing to undo".
    if (!stateRef.current.undoAvailable || inFlight.current > 0) return;
    void run(async () => {
      try {
        const r = await api.undo();
        if (!alive.current) return;
        switch (r.status) {
          case 'undone':
            dispatch({ type: 'undone', card: r.card });
            return;
          case 'nothing_to_undo':
            dispatch({ type: 'undo_unavailable' });
            return;
          default:
            assertNever(r);
        }
      } catch {
        if (alive.current) dispatch({ type: 'undo_failed' });
      }
    });
  }, [api, run]);

  const refresh = useCallback(
    async (section: Section) => {
      const s = stateRef.current;
      const card = s.card;
      if (s.phase !== 'answer' || !card || s.refresh[section] === 'loading') return;
      dispatch({ type: 'refresh_status', section, status: 'loading' });
      try {
        const r = await api.refresh(card.delivery_id, section);
        if (!alive.current || stateRef.current.card?.delivery_id !== card.delivery_id) return;
        switch (r.status) {
          case 'ready':
            dispatch({ type: 'card_replaced', card: r.card });
            dispatch({ type: 'refresh_status', section, status: 'idle' });
            return;
          case 'not_pending':
            dispatch({ type: 'refresh_status', section, status: 'notPending' });
            return;
          case 'quota':
            dispatch({ type: 'refresh_status', section, status: 'quota' });
            return;
          default:
            assertNever(r);
        }
      } catch {
        if (alive.current && stateRef.current.card?.delivery_id === card.delivery_id) {
          dispatch({ type: 'refresh_status', section, status: 'failed' });
        }
      }
    },
    [api],
  );

  const retry = useCallback(() => {
    void run(async () => {
      // A failed first load or failed next: ask the server for the pending card again.
      await loadNext();
    });
  }, [run, loadNext]);

  const dismissNotice = useCallback(() => dispatch({ type: 'dismiss_notice' }), []);

  return { state, busy, reveal, grade, undo, refresh, continueSession, retry, dismissNotice };
}
