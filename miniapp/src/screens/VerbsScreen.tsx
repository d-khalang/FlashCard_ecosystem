import { useCallback, useRef, useState } from 'react';
import { asApiError } from '../api/errors';
import { useApp } from '../app/context';
import { errorCopy } from '../components/errorText';
import { useI18n } from '../i18n';
import type { LookupFound, TenseId } from '../verbs/types';
import { VerbDeck } from './verbs/VerbDeck';
import { VerbDrill } from './verbs/VerbDrill';
import { VerbSearch } from './verbs/VerbSearch';

/** Verbs tab: search -> deck of tense cards -> drill. Only shown when `me.features.verbs`. */
export function VerbsScreen() {
  const { api, toast } = useApp();
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<LookupFound | null>(null);
  const [tense, setTense] = useState<TenseId | undefined>(undefined);
  const [drilling, setDrilling] = useState<TenseId | null>(null);

  /** Bumped on every lookup, so a new result (even another form of the open verb) opens a fresh deck on its match. */
  const [opened, setOpened] = useState(0);

  const open = useCallback((r: LookupFound) => {
    setTense(undefined);
    setFound(r);
    setOpened((n) => n + 1);
  }, []);
  /** Bumped by every deck lookup and by Back: only the newest deck lookup may change the screen. */
  const deckLookup = useRef(0);
  const back = useCallback(() => {
    deckLookup.current += 1;
    setFound(null);
  }, []);
  const endDrill = useCallback(() => setDrilling(null), []);

  // A candidate from the deck ("Also: andarsene") opens straight away; problems fall back to the search.
  const lookupFromDeck = useCallback(
    async (infinitive: string) => {
      const seq = ++deckLookup.current;
      setQuery(infinitive);
      try {
        const r = await api.verbs.lookup(infinitive);
        if (seq !== deckLookup.current) return;
        if (r.status === 'found') open(r);
        else setFound(null);
      } catch (e) {
        if (seq !== deckLookup.current) return;
        toast(t(errorCopy(asApiError(e)).title), 'error');
      }
    },
    [api, open, t, toast],
  );

  if (!found) return <VerbSearch query={query} onQueryChange={setQuery} onFound={open} />;
  return (
    <>
      <VerbDeck
        key={opened}
        result={found}
        tenseId={tense}
        onTenseChange={setTense}
        onBack={back}
        onDrill={setDrilling}
        onLookup={(v) => void lookupFromDeck(v)}
      />
      {drilling ? <VerbDrill infinitive={found.verb.infinitive} tenseId={drilling} onExit={endDrill} /> : null}
    </>
  );
}
