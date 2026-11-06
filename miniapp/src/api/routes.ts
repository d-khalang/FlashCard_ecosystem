import type { HttpClient } from './client';
import { ApiError } from './errors';
import type {
  AudioPart,
  CollectionDetail,
  CollectionPage,
  CurrentResponse,
  Grade,
  GradeResult,
  ImportResult,
  Me,
  NextResult,
  PreviewResult,
  RefreshResult,
  SaveResult,
  Section,
  Settings,
  StudyCard,
  UndoResult,
  Direction,
} from './types';

/** Check the discriminator of a union response. Unknown shapes become a bad_response error. */
export function expectStatus<T extends { status: string }>(raw: unknown, allowed: readonly T['status'][]): T {
  const status = (raw as { status?: unknown } | null)?.status;
  if (typeof status !== 'string' || !(allowed as readonly string[]).includes(status)) {
    throw new ApiError('bad_response', `Unexpected response status: ${String(status)}`);
  }
  return raw as T;
}

function expectCard(card: unknown): StudyCard {
  if (!card || typeof card !== 'object' || typeof (card as StudyCard).delivery_id !== 'number') {
    throw new ApiError('bad_response', 'Missing card in response');
  }
  return card as StudyCard;
}

function withCard<T extends { status: string }>(res: T): T {
  // 'ready' (next, refresh) and 'undone' (undo) must carry a card.
  if (res.status === 'ready' || res.status === 'undone') expectCard((res as { card?: unknown }).card);
  return res;
}

export function createApi(http: HttpClient) {
  const get = <T>(path: string, query?: Record<string, string | number | undefined>) =>
    http.request<T>('GET', path, { query });
  const post = <T>(path: string, body?: unknown) => http.request<T>('POST', path, { body });

  return {
    me: () => get<Me>('/me'),

    current: async (): Promise<CurrentResponse> => {
      const r = await get<CurrentResponse>('/study/current');
      if (r.card) expectCard(r.card);
      return { card: r.card ?? null, undo_available: Boolean(r.undo_available) };
    },
    next: async (): Promise<NextResult> =>
      withCard(expectStatus<NextResult>(await post('/study/next'), ['ready', 'none', 'quota'])),
    prepare: async (): Promise<void> => {
      await post('/study/prepare');
    },
    grade: async (a: { delivery_id: number; expression_id: string; direction: Direction; grade: Grade }): Promise<GradeResult> =>
      expectStatus<GradeResult>(await post('/study/grade', a), ['graded', 'not_pending']),
    undo: async (): Promise<UndoResult> =>
      withCard(expectStatus<UndoResult>(await post('/study/undo'), ['undone', 'nothing_to_undo'])),
    refresh: async (delivery_id: number, section: Section): Promise<RefreshResult> =>
      withCard(expectStatus<RefreshResult>(await post('/study/refresh', { delivery_id, section }), ['ready', 'not_pending', 'quota'])),

    preview: async (text: string): Promise<PreviewResult> =>
      expectStatus<PreviewResult>(await post('/cards/preview', { text }), ['ready', 'unclear', 'invalid', 'quota']),

    collection: (p: { limit?: number; cursor?: string | null; q?: string } = {}) =>
      get<CollectionPage>('/collection', { limit: p.limit, cursor: p.cursor ?? undefined, q: p.q }),
    save: async (value: string): Promise<SaveResult> =>
      expectStatus<SaveResult>(await post('/collection', { value }), ['saved', 'already_saved', 'invalid', 'too_many']),
    detail: (id: string) => get<CollectionDetail>(`/collection/${encodeURIComponent(id)}`),
    remove: async (id: string): Promise<void> => {
      await http.request<void>('DELETE', `/collection/${encodeURIComponent(id)}`);
    },
    importText: async (text: string): Promise<ImportResult> =>
      expectStatus<ImportResult>(await post('/collection/import', { text }), [
        'imported',
        'all_duplicates',
        'parse_failed',
        'nothing_found',
        'invalid_language',
        'too_long',
        'too_many',
        'quota',
      ]),

    audio: (expressionId: string, part: AudioPart) => http.blob(`/audio/${encodeURIComponent(expressionId)}/${part}`),

    updateSettings: (patch: Partial<Settings>) => http.request<Settings>('PATCH', '/settings', { body: patch }),
  };
}

export type Api = ReturnType<typeof createApi>;
