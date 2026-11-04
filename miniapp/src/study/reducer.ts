import type { ApiError } from '../api/errors';
import type { QuotaResult, Section, StudyCard } from '../api/types';

export const CHECKPOINT_EVERY = 5;

export type StudyPhase = 'loading' | 'question' | 'answer' | 'checkpoint' | 'finished' | 'quota' | 'error';
export type RefreshStatus = 'idle' | 'loading' | 'failed' | 'quota' | 'notPending';
export type Notice = 'gradeFailed' | 'undoNothing' | 'undoFailed' | null;

export interface StudyState {
  phase: StudyPhase;
  card: StudyCard | null;
  reviewed: number;
  undoAvailable: boolean;
  quota: QuotaResult | null;
  error: ApiError | null;
  notice: Notice;
  refresh: Record<Section, RefreshStatus>;
}

const IDLE_REFRESH: Record<Section, RefreshStatus> = { definition: 'idle', translations: 'idle', example: 'idle' };

export const initialStudyState: StudyState = {
  phase: 'loading',
  card: null,
  reviewed: 0,
  undoAvailable: false,
  quota: null,
  error: null,
  notice: null,
  refresh: IDLE_REFRESH,
};

export type StudyAction =
  | { type: 'loading' }
  | { type: 'card'; card: StudyCard; undoAvailable?: boolean }
  | { type: 'none' }
  | { type: 'quota'; quota: QuotaResult }
  | { type: 'failed'; error: ApiError }
  | { type: 'reveal' }
  | { type: 'grade_optimistic' }
  | { type: 'grade_confirmed'; undoAvailable: boolean }
  | { type: 'grade_skipped' }
  | { type: 'grade_rolled_back'; card: StudyCard }
  | { type: 'undone'; card: StudyCard }
  | { type: 'undo_unavailable' }
  | { type: 'undo_failed' }
  | { type: 'refresh_status'; section: Section; status: RefreshStatus }
  | { type: 'card_replaced'; card: StudyCard }
  | { type: 'dismiss_notice' };

/** True when the review count just reached a checkpoint. */
export function isCheckpoint(reviewed: number): boolean {
  return reviewed > 0 && reviewed % CHECKPOINT_EVERY === 0;
}

export function studyReducer(state: StudyState, action: StudyAction): StudyState {
  switch (action.type) {
    case 'loading':
      return { ...state, phase: 'loading', error: null };
    case 'card':
      return {
        ...state,
        phase: 'question',
        card: action.card,
        undoAvailable: action.undoAvailable ?? state.undoAvailable,
        error: null,
        notice: null,
        refresh: IDLE_REFRESH,
      };
    case 'none':
      return { ...state, phase: 'finished', card: null, error: null };
    case 'quota':
      return { ...state, phase: 'quota', card: null, quota: action.quota };
    case 'failed':
      return { ...state, phase: 'error', error: action.error };
    case 'reveal':
      return state.phase === 'question' ? { ...state, phase: 'answer' } : state;
    case 'grade_optimistic': {
      const reviewed = state.reviewed + 1;
      return {
        ...state,
        reviewed,
        phase: isCheckpoint(reviewed) ? 'checkpoint' : 'loading',
        undoAvailable: false,
        notice: null,
      };
    }
    case 'grade_confirmed':
      return { ...state, undoAvailable: action.undoAvailable };
    case 'grade_skipped':
      // The card was answered elsewhere: do not count it, just move on.
      return { ...state, reviewed: Math.max(0, state.reviewed - 1), phase: 'loading', undoAvailable: false };
    case 'grade_rolled_back':
      return {
        ...state,
        phase: 'answer',
        card: action.card,
        reviewed: Math.max(0, state.reviewed - 1),
        notice: 'gradeFailed',
        error: null,
      };
    case 'undone':
      return {
        ...state,
        phase: 'answer',
        card: action.card,
        reviewed: Math.max(0, state.reviewed - 1),
        undoAvailable: false,
        notice: null,
        error: null,
        refresh: IDLE_REFRESH,
      };
    case 'undo_unavailable':
      return { ...state, undoAvailable: false, notice: 'undoNothing' };
    case 'undo_failed':
      return { ...state, notice: 'undoFailed' };
    case 'refresh_status':
      return { ...state, refresh: { ...state.refresh, [action.section]: action.status } };
    case 'card_replaced':
      return state.card ? { ...state, card: action.card } : state;
    case 'dismiss_notice':
      return { ...state, notice: null };
  }
}
