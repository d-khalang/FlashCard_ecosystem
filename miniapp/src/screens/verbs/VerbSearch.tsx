import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ChevronRight, Loader2, Search, X } from 'lucide-react';
import { asApiError, type ApiError } from '../../api/errors';
import { useApp } from '../../app/context';
import { ErrorState } from '../../components/ErrorState';
import { useI18n } from '../../i18n';
import { MAX_VERB_QUERY_CHARS, type LookupFound, type LookupInvalid, type LookupNotFound, type VerbHome } from '../../verbs/types';

const SUGGEST_DELAY_MS = 250;
const MIN_SUGGEST_CHARS = 2;

type Status =
  | { kind: 'idle' }
  | { kind: 'loading'; query: string }
  | LookupNotFound
  | LookupInvalid
  | { kind: 'error'; error: ApiError; query: string };

interface VerbSearchProps {
  query: string;
  onQueryChange: (q: string) => void;
  onFound: (result: LookupFound) => void;
}

/** Entry: search box, suggestions while typing, recent verbs and verbs in the collection. */
export function VerbSearch({ query, onQueryChange, onFound }: VerbSearchProps) {
  const { api } = useApp();
  const { t } = useI18n();
  const [home, setHome] = useState<VerbHome | null>(null);
  const [homeError, setHomeError] = useState<ApiError | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const lookupSeq = useRef(0);

  const loadHome = () => {
    setHomeError(null);
    api.verbs.home().then(setHome, (e: unknown) => setHomeError(asApiError(e)));
  };
  useEffect(loadHome, [api]);

  // Debounced suggestions. Failures are quiet: suggestions only help.
  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_SUGGEST_CHARS) {
      setSuggestions([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      api.verbs.suggest(q).then(
        (r) => live && setSuggestions(r.items),
        () => live && setSuggestions([]),
      );
    }, SUGGEST_DELAY_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [api, query]);

  const lookup = async (raw: string) => {
    const q = raw.trim().replace(/\s+/g, ' ');
    if (!q) return;
    const seq = ++lookupSeq.current;
    setStatus({ kind: 'loading', query: q });
    try {
      const r = await api.verbs.lookup(q);
      if (seq !== lookupSeq.current) return;
      if (r.status === 'found') {
        setStatus({ kind: 'idle' });
        onFound(r);
      } else {
        setStatus(r);
      }
    } catch (e) {
      if (seq === lookupSeq.current) setStatus({ kind: 'error', error: asApiError(e), query: q });
    }
  };

  const pick = (infinitive: string) => {
    onQueryChange(infinitive);
    void lookup(infinitive);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void lookup(query);
  };

  const typing = query.trim().length > 0;
  const statusKind = 'kind' in status ? status.kind : status.status;
  const showSuggestions = typing && statusKind === 'idle' && suggestions.length > 0;

  return (
    <div className="screen verb-search">
      <header className="top-bar">
        <h1 className="screen-title">{t('verbs.title')}</h1>
        <span className="pill pill-free">{t('verbs.free')}</span>
      </header>

      <form className="field" role="search" onSubmit={submit}>
        <label className="field-label" htmlFor="verb-q">
          {t('verbs.search.label')}
        </label>
        <div className="verb-field">
          <Search size={20} strokeWidth={2.5} aria-hidden="true" />
          <input
            id="verb-q"
            className="verb-input"
            type="search"
            enterKeyHint="search"
            value={query}
            maxLength={MAX_VERB_QUERY_CHARS}
            placeholder={t('verbs.search.placeholder')}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            lang="it"
            onChange={(e) => {
              onQueryChange(e.target.value);
              if (statusKind !== 'loading') setStatus({ kind: 'idle' });
            }}
          />
          {typing ? (
            <>
              <button type="button" className="icon-btn icon-btn-small" aria-label={t('verbs.search.clear')} onClick={() => {
                onQueryChange('');
                setStatus({ kind: 'idle' });
              }}>
                <X size={18} strokeWidth={2.6} aria-hidden="true" />
              </button>
              <button type="submit" className="icon-btn icon-btn-go" aria-label={t('verbs.search.submit')} disabled={statusKind === 'loading'}>
                <ArrowRight size={20} strokeWidth={2.6} aria-hidden="true" />
              </button>
            </>
          ) : null}
        </div>
      </form>

      <StatusView status={status} onPick={pick} onRetry={() => 'query' in status && void lookup(status.query)} />

      {showSuggestions ? (
        <section className="verb-section" aria-labelledby="verb-sugg">
          <h2 id="verb-sugg" className="verb-section-title">
            {t('verbs.suggestions')}
          </h2>
          <ul className="verb-list">
            {suggestions.map((s) => (
              <li key={s}>
                <button type="button" className="verb-row" lang="it" onClick={() => pick(s)}>
                  <span className="verb-row-word">{s}</span>
                  <ChevronRight size={20} strokeWidth={2.5} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {!typing ? <HomeView home={home} error={homeError} onRetry={loadHome} onPick={pick} /> : null}
    </div>
  );
}

function StatusView({ status, onPick, onRetry }: { status: Status; onPick: (v: string) => void; onRetry: () => void }) {
  const { t } = useI18n();
  if ('status' in status) {
    if (status.status === 'invalid') {
      return (
        <div className="verb-message" role="status">
          <h2 className="verb-message-title">{t('verbs.invalid.title', { query: status.query })}</h2>
          <p>{t('verbs.invalid.body')}</p>
        </div>
      );
    }
    return (
      <div className="verb-message" role="status">
        <h2 className="verb-message-title">{t('verbs.notFound.title', { query: status.query })}</h2>
        <p>{t('verbs.notFound.body')}</p>
        {status.suggestions.length > 0 ? (
          <>
            <p className="verb-section-title">{t('verbs.didYouMean')}</p>
            <div className="chips" lang="it">
              {status.suggestions.map((s) => (
                <button key={s} type="button" className="verb-chip" onClick={() => onPick(s)}>
                  {s}
                </button>
              ))}
            </div>
          </>
        ) : null}
      </div>
    );
  }
  if (status.kind === 'loading') {
    return (
      <p className="verb-loading" role="status">
        <Loader2 size={20} strokeWidth={2.6} className="spin" aria-hidden="true" />
        {t('verbs.loading')}
      </p>
    );
  }
  if (status.kind === 'error') return <ErrorState error={status.error} onRetry={onRetry} compact />;
  return null;
}

interface HomeViewProps {
  home: VerbHome | null;
  error: ApiError | null;
  onRetry: () => void;
  onPick: (infinitive: string) => void;
}

function HomeView({ home, error, onRetry, onPick }: HomeViewProps) {
  const { t } = useI18n();
  if (error) return <ErrorState error={error} onRetry={onRetry} compact />;
  if (!home) return <span className="sr-only" role="status">{t('common.loading')}</span>;
  if (home.recent.length === 0 && home.collection.length === 0) return <p className="field-hint">{t('verbs.search.hint')}</p>;
  return (
    <>
      {home.recent.length > 0 ? (
        <section className="verb-section" aria-labelledby="verb-recent">
          <h2 id="verb-recent" className="verb-section-title">
            {t('verbs.recent')}
          </h2>
          <div className="chips" lang="it">
            {home.recent.map((v) => (
              <button key={v} type="button" className="verb-chip" onClick={() => onPick(v)}>
                {v}
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {home.collection.length > 0 ? (
        <section className="verb-section" aria-labelledby="verb-coll">
          <div className="verb-section-head">
            <h2 id="verb-coll" className="verb-section-title">
              {t('verbs.collection')}
            </h2>
            <span className="meta-line">{home.collection.length}</span>
          </div>
          <ul className="verb-panel-list">
            {home.collection.map((c) => (
              <li key={c.expression_id}>
                <button type="button" className="verb-panel-row" onClick={() => onPick(c.infinitive)}>
                  <span lang="it">{c.infinitive}</span>
                  {c.meaning ? (
                    <span className="verb-meaning" dir="auto">
                      {c.meaning}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
