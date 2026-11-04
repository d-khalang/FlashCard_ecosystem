import { useEffect, useMemo, useState } from 'react';
import { WifiOff } from 'lucide-react';
import { createClient } from './api/client';
import { ApiError } from './api/errors';
import { createApi } from './api/routes';
import { AppProvider, useApp } from './app/context';
import { BottomNav } from './components/BottomNav';
import { ErrorState } from './components/ErrorState';
import { useI18n } from './i18n';
import { NAV } from './navigation';
import { StudyScreen } from './screens/StudyScreen';
import { getInitData } from './telegram';

export const API_BASE_URL = './api/v1';

function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);
  return online;
}

function Shell() {
  const { me, meError, authLost } = useApp();
  const { t } = useI18n();
  const online = useOnline();
  const [tab, setTab] = useState(NAV[0]!.id);
  const [studying, setStudying] = useState(false);

  if (authLost || meError?.kind === 'auth') {
    return (
      <div className="app">
        <ErrorState error={new ApiError('auth', 'auth_required')} />
      </div>
    );
  }
  if (meError?.kind === 'forbidden') {
    return (
      <div className="app">
        <ErrorState error={meError} />
      </div>
    );
  }

  if (studying) {
    return (
      <div className="app">
        {!online ? <OfflineBanner text={t('offline.banner')} /> : null}
        <StudyScreen onExit={() => setStudying(false)} />
      </div>
    );
  }

  const entry = NAV.find((n) => n.id === tab) ?? NAV[0]!;
  const Screen = entry.Screen;
  return (
    <div className="app">
      {!online ? <OfflineBanner text={t('offline.banner')} /> : null}
      <main className="app-main" key={entry.id}>
        <Screen onStudy={() => setStudying(true)} />
      </main>
      <BottomNav entries={NAV} current={entry.id} onSelect={setTab} />
      {me === null && meError === null ? <span className="sr-only" role="status">{t('common.loading')}</span> : null}
    </div>
  );
}

function OfflineBanner({ text }: { text: string }) {
  return (
    <div className="offline-banner" role="status">
      <WifiOff size={16} strokeWidth={2.6} aria-hidden="true" />
      {text}
    </div>
  );
}

export function App({ fetchImpl }: { fetchImpl?: typeof fetch }) {
  const [authLost, setAuthLost] = useState(false);
  const api = useMemo(
    () =>
      createApi(
        createClient({
          baseUrl: API_BASE_URL,
          getInitData,
          fetch: fetchImpl,
          onUnauthorized: () => setAuthLost(true),
        }),
      ),
    [fetchImpl],
  );
  return (
    <AppProvider api={api} authLost={authLost}>
      <Shell />
    </AppProvider>
  );
}
