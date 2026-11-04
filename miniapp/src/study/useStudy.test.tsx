import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import type { NextResult, StudyCard } from '../api/types';
import { initialStudyState, studyReducer } from './reducer';
import { useStudy } from './useStudy';

afterEach(cleanup);

const card = (n: number): StudyCard => ({
  delivery_id: -n,
  expression_id: `e${n}`,
  value: `word ${n}`,
  direction: 'forward',
  from_storage: false,
  older_settings: false,
  definition: 'def',
  translations: [],
  example: 'ex',
  note: null,
});

function fakeApi(over: Partial<Record<string, unknown>> = {}) {
  let n = 0;
  const api = {
    current: vi.fn(async () => ({ card: null, undo_available: false })),
    next: vi.fn(async (): Promise<NextResult> => ({ status: 'ready', card: card(++n) })),
    prepare: vi.fn(async () => undefined),
    grade: vi.fn(async () => ({ status: 'graded' as const, undo_available: true })),
    undo: vi.fn(async () => ({ status: 'undone' as const, card: card(1) })),
    refresh: vi.fn(async () => ({ status: 'ready' as const, card: { ...card(1), definition: 'new def' } })),
    ...over,
  };
  return api as typeof api & Parameters<typeof useStudy>[0];
}

async function setup(api = fakeApi()) {
  const hook = renderHook(() => useStudy(api));
  await waitFor(() => expect(hook.result.current.state.phase).toBe('question'));
  return { api, hook };
}

const gradeAndSettle = async (hook: Awaited<ReturnType<typeof setup>>['hook'], g: 0 | 1 | 2 | 3 | 4 | 5 = 4) => {
  act(() => hook.result.current.reveal());
  act(() => hook.result.current.grade(g));
};

describe('study entry', () => {
  it('resumes the current card without asking for a new one', async () => {
    const api = fakeApi({ current: vi.fn(async () => ({ card: card(7), undo_available: true })) });
    const { hook } = await setup(api);
    expect(hook.result.current.state.card?.delivery_id).toBe(-7);
    expect(hook.result.current.state.undoAvailable).toBe(true);
    expect(api.next).not.toHaveBeenCalled();
  });

  it('asks for the next card when there is no current one', async () => {
    const { api, hook } = await setup();
    expect(api.current).toHaveBeenCalledTimes(1);
    expect(api.next).toHaveBeenCalledTimes(1);
    expect(hook.result.current.state.card?.value).toBe('word 1');
  });

  it('shows the finished state for status none, and quota for quota', async () => {
    let hook = renderHook(() => useStudy(fakeApi({ next: vi.fn(async () => ({ status: 'none' })) })));
    await waitFor(() => expect(hook.result.current.state.phase).toBe('finished'));
    hook = renderHook(() => useStudy(fakeApi({ next: vi.fn(async () => ({ status: 'quota', tier: 'free', limit: 20 })) })));
    await waitFor(() => expect(hook.result.current.state.phase).toBe('quota'));
  });

  it('reports a load failure with the error', async () => {
    const hook = renderHook(() => useStudy(fakeApi({ next: vi.fn(async () => { throw new ApiError('network', 'x'); }) })));
    await waitFor(() => expect(hook.result.current.state.phase).toBe('error'));
    expect(hook.result.current.state.error?.kind).toBe('network');
  });
});

describe('reveal and prepare', () => {
  it('reveals once and calls prepare once per card', async () => {
    const { api, hook } = await setup();
    act(() => hook.result.current.reveal());
    act(() => hook.result.current.reveal());
    expect(hook.result.current.state.phase).toBe('answer');
    expect(api.prepare).toHaveBeenCalledTimes(1);
  });

  it('ignores a failing prepare', async () => {
    const { hook } = await setup(fakeApi({ prepare: vi.fn(async () => { throw new ApiError('rate_limited', 'x'); }) }));
    act(() => hook.result.current.reveal());
    expect(hook.result.current.state.phase).toBe('answer');
  });

  it('does not grade before the answer is revealed', async () => {
    const { api, hook } = await setup();
    act(() => hook.result.current.grade(3));
    expect(api.grade).not.toHaveBeenCalled();
  });
});

describe('grading', () => {
  it('moves on at once, then loads the next card after the grade is saved', async () => {
    let release: (v: { status: 'graded'; undo_available: boolean }) => void = () => undefined;
    const api = fakeApi({ grade: vi.fn(() => new Promise((r) => { release = r as typeof release; })) });
    const { hook } = await setup(api);
    await gradeAndSettle(hook, 4);
    // Optimistic: already counted and loading, before the server answered.
    expect(hook.result.current.state.phase).toBe('loading');
    expect(hook.result.current.state.reviewed).toBe(1);
    expect(api.next).toHaveBeenCalledTimes(1); // next is not requested before the grade lands
    await act(async () => release({ status: 'graded', undo_available: true }));
    await waitFor(() => expect(hook.result.current.state.phase).toBe('question'));
    expect(api.next).toHaveBeenCalledTimes(2);
    expect(hook.result.current.state.card?.value).toBe('word 2');
    expect(hook.result.current.state.undoAvailable).toBe(true);
    expect(api.grade).toHaveBeenCalledWith({ delivery_id: -1, expression_id: 'e1', direction: 'forward', grade: 4 });
  });

  it('rolls back to the same card with an error when grading fails', async () => {
    const api = fakeApi({ grade: vi.fn(async () => { throw new ApiError('server', 'x'); }) });
    const { hook } = await setup(api);
    await gradeAndSettle(hook, 2);
    await waitFor(() => expect(hook.result.current.state.notice).toBe('gradeFailed'));
    const s = hook.result.current.state;
    expect(s.phase).toBe('answer');
    expect(s.card?.delivery_id).toBe(-1);
    expect(s.reviewed).toBe(0);
    expect(api.next).toHaveBeenCalledTimes(1);
  });

  it('moves on without counting when the card is no longer pending', async () => {
    const api = fakeApi({ grade: vi.fn(async () => ({ status: 'not_pending' })) });
    const { hook } = await setup(api);
    await gradeAndSettle(hook);
    await waitFor(() => expect(hook.result.current.state.card?.value).toBe('word 2'));
    expect(hook.result.current.state.reviewed).toBe(0);
  });

  it('treats a 404 on grade as gone and moves on', async () => {
    const api = fakeApi({ grade: vi.fn(async () => { throw new ApiError('not_found', 'x'); }) });
    const { hook } = await setup(api);
    await gradeAndSettle(hook);
    await waitFor(() => expect(hook.result.current.state.card?.value).toBe('word 2'));
    expect(hook.result.current.state.reviewed).toBe(0);
  });
});

describe('checkpoint', () => {
  it('stops every 5 reviews and continues on request', async () => {
    const { api, hook } = await setup();
    for (let i = 1; i <= 5; i++) {
      await gradeAndSettle(hook);
      if (i < 5) await waitFor(() => expect(hook.result.current.state.card?.value).toBe(`word ${i + 1}`));
    }
    await waitFor(() => expect(hook.result.current.state.phase).toBe('checkpoint'));
    expect(hook.result.current.state.reviewed).toBe(5);
    await waitFor(() => expect(hook.result.current.state.undoAvailable).toBe(true)); // undo stays possible
    expect(api.next).toHaveBeenCalledTimes(5);
    act(() => hook.result.current.continueSession());
    await waitFor(() => expect(hook.result.current.state.phase).toBe('question'));
    expect(api.next).toHaveBeenCalledTimes(6);
  });
});

describe('undo', () => {
  it('restores the previous card in the answer state and uncounts it', async () => {
    const { api, hook } = await setup();
    await gradeAndSettle(hook);
    await waitFor(() => expect(hook.result.current.state.undoAvailable).toBe(true));
    await waitFor(() => expect(hook.result.current.state.phase).toBe('question'));
    act(() => hook.result.current.undo());
    await waitFor(() => expect(hook.result.current.state.phase).toBe('answer'));
    expect(api.undo).toHaveBeenCalledTimes(1);
    expect(hook.result.current.state.card?.delivery_id).toBe(-1);
    expect(hook.result.current.state.reviewed).toBe(0);
    expect(hook.result.current.state.undoAvailable).toBe(false);
  });

  it('reports nothing to undo', async () => {
    const api = fakeApi({ undo: vi.fn(async () => ({ status: 'nothing_to_undo' })) });
    const { hook } = await setup(api);
    await gradeAndSettle(hook);
    await waitFor(() => expect(hook.result.current.state.undoAvailable).toBe(true));
    act(() => hook.result.current.undo());
    await waitFor(() => expect(hook.result.current.state.notice).toBe('undoNothing'));
    expect(hook.result.current.state.undoAvailable).toBe(false);
  });

  it('does nothing when undo is not available', async () => {
    const { api, hook } = await setup();
    act(() => hook.result.current.undo());
    expect(api.undo).not.toHaveBeenCalled();
  });
});

describe('refresh', () => {
  it('replaces the card content on success', async () => {
    const { api, hook } = await setup();
    act(() => hook.result.current.reveal());
    await act(async () => hook.result.current.refresh('definition'));
    expect(api.refresh).toHaveBeenCalledWith(-1, 'definition');
    expect(hook.result.current.state.card?.definition).toBe('new def');
    expect(hook.result.current.state.refresh.definition).toBe('idle');
  });

  it('keeps the old text and flags the section when refresh fails', async () => {
    const api = fakeApi({ refresh: vi.fn(async () => { throw new ApiError('unavailable', 'x'); }) });
    const { hook } = await setup(api);
    act(() => hook.result.current.reveal());
    await act(async () => hook.result.current.refresh('example'));
    expect(hook.result.current.state.card?.example).toBe('ex');
    expect(hook.result.current.state.refresh.example).toBe('failed');
  });

  it('shows the quota message from a quota result', async () => {
    const api = fakeApi({ refresh: vi.fn(async () => ({ status: 'quota', tier: 'free', limit: 20 })) });
    const { hook } = await setup(api);
    act(() => hook.result.current.reveal());
    await act(async () => hook.result.current.refresh('translations'));
    expect(hook.result.current.state.refresh.translations).toBe('quota');
  });
});

describe('reducer', () => {
  it('only reveals from the question phase', () => {
    expect(studyReducer(initialStudyState, { type: 'reveal' }).phase).toBe('loading');
    const q = studyReducer(initialStudyState, { type: 'card', card: card(1) });
    expect(studyReducer(q, { type: 'reveal' }).phase).toBe('answer');
  });
});
