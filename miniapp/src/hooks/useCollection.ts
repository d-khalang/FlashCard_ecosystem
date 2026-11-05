import { useCallback, useEffect, useRef, useState } from 'react';
import type { Api } from '../api/routes';
import { asApiError, type ApiError } from '../api/errors';
import { MIN_SEARCH_CHARS, type CollectionItem } from '../api/types';

export const PAGE_SIZE = 30;
/** Searching is not paged, so it asks for the most the server allows. */
export const SEARCH_LIMIT = 50;
export const SEARCH_DEBOUNCE_MS = 300;

/** Search term to send, or undefined when the box is empty or too short. */
export function effectiveQuery(raw: string): string | undefined {
  const q = raw.trim();
  return q.length >= MIN_SEARCH_CHARS ? q : undefined;
}

export function useCollection(api: Pick<Api, 'collection'>, rawQuery: string) {
  const [q, setQ] = useState<string | undefined>(effectiveQuery(rawQuery));
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const request = useRef(0);

  // Debounce the search term.
  useEffect(() => {
    const next = effectiveQuery(rawQuery);
    const id = window.setTimeout(() => setQ(next), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [rawQuery]);

  const load = useCallback(
    async (after: string | null) => {
      const id = ++request.current;
      setLoading(true);
      setError(null);
      try {
        const page = await api.collection({ limit: q ? SEARCH_LIMIT : PAGE_SIZE, cursor: after, q });
        if (request.current !== id) return;
        setItems((prev) => (after ? [...prev, ...page.items] : page.items));
        // Searching is not paged.
        setCursor(q ? null : page.next_cursor);
      } catch (e) {
        if (request.current === id) setError(asApiError(e));
      } finally {
        if (request.current === id) setLoading(false);
      }
    },
    [api, q],
  );

  useEffect(() => {
    setItems([]);
    setCursor(null);
    void load(null);
  }, [load]);

  const loadMore = useCallback(() => {
    if (cursor && !loading) void load(cursor);
  }, [cursor, loading, load]);

  const reload = useCallback(() => {
    void load(null);
  }, [load]);

  const dropItem = useCallback((id: string) => setItems((prev) => prev.filter((i) => i.id !== id)), []);

  return { items, loading, error, hasMore: cursor !== null, loadMore, reload, dropItem, searching: q !== undefined };
}
