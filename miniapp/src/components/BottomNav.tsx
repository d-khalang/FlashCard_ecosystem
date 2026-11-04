import { useI18n } from '../i18n';
import type { NavEntry } from '../navigation';

interface BottomNavProps {
  entries: readonly NavEntry[];
  current: string;
  onSelect: (id: string) => void;
}

export function BottomNav({ entries, current, onSelect }: BottomNavProps) {
  const { t } = useI18n();
  return (
    <nav className="bottom-nav" aria-label={t('nav.main')}>
      {entries.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          className={id === current ? 'nav-item is-current' : 'nav-item'}
          aria-current={id === current ? 'page' : undefined}
          onClick={() => onSelect(id)}
        >
          <Icon size={22} strokeWidth={2.4} aria-hidden="true" />
          <span>{t(label)}</span>
        </button>
      ))}
    </nav>
  );
}
