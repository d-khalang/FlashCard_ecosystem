import { useEffect, useRef, useState } from 'react';
import { Search, Upload } from 'lucide-react';
import { useApp } from '../app/context';
import { ErrorState } from '../components/ErrorState';
import { ImportSheet } from '../components/ImportSheet';
import { Mascot } from '../components/Mascot';
import { WordDetailSheet } from '../components/WordDetailSheet';
import { useCollection } from '../hooks/useCollection';
import { useI18n } from '../i18n';
import type { ScreenProps } from '../navigation';

export function CollectionScreen(_props: ScreenProps) {
  const { api, reloadMe } = useApp();
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const list = useCollection(api, query);
  const sentinel = useRef<HTMLDivElement>(null);

  // Infinite scroll: load the next page when the sentinel scrolls into view.
  const { hasMore, loadMore } = list;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasMore || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore();
    });
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, loadMore, list.items.length]);

  const shortQuery = query.trim().length > 0 && query.trim().length < 2;
  const empty = !list.loading && !list.error && list.items.length === 0;

  return (
    <div className="screen">
      <header className="top-bar">
        <h1 className="screen-title">{t('collection.title')}</h1>
        <button type="button" className="btn btn-small btn-with-icon" onClick={() => setImporting(true)}>
          <Upload size={18} strokeWidth={2.6} aria-hidden="true" />
          {t('collection.import')}
        </button>
      </header>

      <div className="search">
        <Search size={20} strokeWidth={2.6} aria-hidden="true" className="search-icon" />
        <input
          type="search"
          className="input search-input"
          dir="auto"
          aria-label={t('collection.search')}
          placeholder={t('collection.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
        />
      </div>
      {shortQuery ? <p className="field-hint">{t('collection.searchHint')}</p> : null}

      {list.error ? <ErrorState error={list.error} onRetry={list.reload} compact /> : null}

      <ul className="word-list">
        {list.items.map((item) => (
          <li key={item.id}>
            <button type="button" className="word-row" onClick={() => setOpenId(item.id)}>
              <span className="word-value" dir="auto">
                {item.value}
              </span>
              <span className="word-meta">{t('collection.stats', { reps: item.reps, lapses: item.lapses })}</span>
            </button>
          </li>
        ))}
      </ul>

      {list.loading ? (
        <p className="note-line center" role="status">
          {t('common.loading')}
        </p>
      ) : null}
      {empty ? (
        <div className="screen-center">
          <Mascot name="reading" size="medium" />
          <p className="note-line center" role="status">
            {list.searching ? t('collection.noResults') : t('collection.empty')}
          </p>
        </div>
      ) : null}
      {list.hasMore ? (
        <>
          <div ref={sentinel} className="sentinel" />
          <button type="button" className="btn btn-ghost" onClick={list.loadMore} disabled={list.loading}>
            {t('collection.loadMore')}
          </button>
        </>
      ) : null}

      {openId ? (
        <WordDetailSheet id={openId} onClose={() => setOpenId(null)} onRemoved={list.dropItem} />
      ) : null}
      {importing ? (
        <ImportSheet
          onClose={() => {
            setImporting(false);
            list.reload();
            void reloadMe();
          }}
        />
      ) : null}
    </div>
  );
}
