import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PAGE_SIZE, SEARCH_LIMIT, useCollection } from './useCollection';

afterEach(cleanup);

const collection = () => vi.fn(async () => ({ items: [], next_cursor: null }));

describe('useCollection', () => {
  it('asks for a page when browsing', async () => {
    const api = { collection: collection() };
    renderHook(() => useCollection(api, ''));
    await waitFor(() => expect(api.collection).toHaveBeenCalled());
    expect(api.collection).toHaveBeenCalledWith({ limit: PAGE_SIZE, cursor: null, q: undefined });
  });

  it('asks for all it may get when searching, because a search has no next page', async () => {
    const api = { collection: collection() };
    renderHook(() => useCollection(api, 'mare'));
    await waitFor(() => expect(api.collection).toHaveBeenCalled());
    expect(api.collection).toHaveBeenCalledWith({ limit: SEARCH_LIMIT, cursor: null, q: 'mare' });
  });
});
