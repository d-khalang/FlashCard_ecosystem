// The drill's flow as a pure reducer: answer -> feedback -> next ... -> summary, then retry the wrong ones.
import { counts, gradeAnswer, type Verdict } from './grade';
import type { Drill, DrillItem, Person, PracticeRequest } from './types';

export interface Answered {
  verdict: Verdict;
  /** Show answer was pressed: counts as wrong. */
  shown: boolean;
}

export interface DrillState {
  drill: Drill;
  /** The items of this round: all of them, or the wrong ones on a retry. */
  round: DrillItem[];
  index: number;
  answers: Answered[];
  phase: 'answer' | 'feedback' | 'summary';
  /** A retry round is practice only; it is not sent to the server. */
  retry: boolean;
}

export type DrillAction =
  | { type: 'check'; input: string }
  /** Enter: check while answering, next while showing feedback. Decided here, so fast double presses stay in order. */
  | { type: 'enter'; input: string }
  | { type: 'show' }
  | { type: 'next' }
  | { type: 'retryWrong' }
  | { type: 'restart' };

export function startDrill(drill: Drill, round: DrillItem[] = drill.items, retry = false): DrillState {
  return { drill, round, index: 0, answers: [], phase: 'answer', retry };
}

export function drillReducer(state: DrillState, action: DrillAction): DrillState {
  const item = state.round[state.index];
  switch (action.type) {
    case 'check':
      if (state.phase !== 'answer' || !item || !action.input.trim()) return state;
      return { ...state, phase: 'feedback', answers: [...state.answers, { verdict: gradeAnswer(action.input, item, state.drill.strip_prefixes), shown: false }] };
    case 'enter':
      return drillReducer(state, state.phase === 'answer' ? { type: 'check', input: action.input } : { type: 'next' });
    case 'show':
      if (state.phase !== 'answer' || !item) return state;
      return { ...state, phase: 'feedback', answers: [...state.answers, { verdict: { result: 'wrong' }, shown: true }] };
    case 'next':
      if (state.phase !== 'feedback') return state;
      return state.index + 1 >= state.round.length ? { ...state, phase: 'summary' } : { ...state, index: state.index + 1, phase: 'answer' };
    case 'retryWrong': {
      const wrong = state.round.filter((_, i) => !counts(state.answers[i]!.verdict));
      return wrong.length ? startDrill(state.drill, wrong, true) : state;
    }
    case 'restart':
      return startDrill(state.drill);
  }
}

export function score(state: DrillState): { score: number; outOf: number; missed: Person[] } {
  const missed = state.round.filter((_, i) => !state.answers[i] || !counts(state.answers[i].verdict)).map((it) => it.person);
  return { score: state.round.length - missed.length, outOf: state.round.length, missed };
}

/** The POST /practice body for a finished full round; null for retry rounds. */
export function practiceBody(state: DrillState): PracticeRequest | null {
  if (state.phase !== 'summary' || state.retry) return null;
  const s = score(state);
  return { infinitive: state.drill.infinitive, tense_id: state.drill.tense_id, score: s.score, out_of: s.outOf, missed: s.missed };
}
