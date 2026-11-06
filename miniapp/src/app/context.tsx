import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Api } from '../api/routes';
import { asApiError, type ApiError } from '../api/errors';
import { createBrowserPlayer, type ClipPlayer } from '../audio/player';
import type { LanguageInfo, Me, Settings } from '../api/types';
import { cleanLabel } from '../components/flags';

interface Toast {
  id: number;
  text: string;
  tone: 'info' | 'error';
}

interface AppValue {
  api: Api;
  player: ClipPlayer;
  me: Me | null;
  meError: ApiError | null;
  reloadMe: () => Promise<void>;
  setSettings: (update: Settings | ((current: Settings) => Settings)) => void;
  languageName: (country: string | null | undefined, fallbackLabel: string) => string;
  toast: (text: string, tone?: Toast['tone']) => void;
  authLost: boolean;
}

const Ctx = createContext<AppValue | null>(null);

const NO_LANGUAGES: LanguageInfo[] = [];

interface ProviderProps {
  api: Api;
  authLost: boolean;
  children: ReactNode;
}

export function AppProvider({ api, authLost, children }: ProviderProps) {
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState<ApiError | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const [player] = useState(createBrowserPlayer);

  const reloadMe = useCallback(async () => {
    try {
      setMe(await api.me());
      setMeError(null);
    } catch (e) {
      setMeError(asApiError(e));
    }
  }, [api]);

  useEffect(() => {
    void reloadMe();
  }, [reloadMe]);

  const setSettings = useCallback((update: Settings | ((current: Settings) => Settings)) => {
    setMe((m) => (m ? { ...m, settings: typeof update === 'function' ? update(m.settings) : update } : m));
  }, []);

  const toast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = nextId.current++;
    setToasts((list) => [...list, { id, text, tone }]);
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 3500);
  }, []);

  const languages = me?.options.languages ?? NO_LANGUAGES;
  const languageName = useCallback(
    (country: string | null | undefined, fallbackLabel: string) => {
      const hit = country ? languages.find((l) => l.country?.toLowerCase() === country.toLowerCase()) : undefined;
      return hit?.name ?? (cleanLabel(fallbackLabel) || (country ?? '').toUpperCase());
    },
    [languages],
  );

  const value = useMemo<AppValue>(
    () => ({ api, player, me, meError, reloadMe, setSettings, languageName, toast, authLost }),
    [api, player, me, meError, reloadMe, setSettings, languageName, toast, authLost],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`} dir="auto">
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useApp(): AppValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}
