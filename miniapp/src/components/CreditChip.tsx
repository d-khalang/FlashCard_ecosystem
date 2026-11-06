import { useState } from 'react';
import { Zap } from 'lucide-react';
import type { Me } from '../api/types';
import { credits, refillIn, type Credits } from '../credits';
import { useI18n } from '../i18n';
import { haptic } from '../telegram';
import { Sheet } from './Sheet';

function Meter({ c, large = false }: { c: Credits; large?: boolean }) {
  return (
    <span className={`credit-meter credit-meter-${c.level}${large ? ' credit-meter-large' : ''}`} aria-hidden="true">
      <span style={{ width: `${Math.round(c.share * 100)}%` }} />
    </span>
  );
}

function CreditSheet({ c, onClose }: { c: Credits; onClose: () => void }) {
  const { t } = useI18n();
  const refill = refillIn();
  return (
    <Sheet title={t('credits.title')} onClose={onClose}>
      <p className="credit-total">
        <strong>{c.left}</strong> {t('credits.left', { limit: c.limit })}
      </p>
      <Meter c={c} large />
      <dl className="credit-costs">
        <div>
          <dt>{t('credits.newCard')}</dt>
          <dd>
            {c.cardCost} <Zap size={14} strokeWidth={2.8} aria-hidden="true" />
          </dd>
        </div>
        <div>
          <dt>{t('credits.refreshPart')}</dt>
          <dd>
            {c.sectionCost} <Zap size={14} strokeWidth={2.8} aria-hidden="true" />
          </dd>
        </div>
        <div className="credit-muted">
          <dt>{t('credits.refillIn')}</dt>
          <dd>{t('credits.time', refill)}</dd>
        </div>
      </dl>
      <p className="credit-muted credit-note">{t('credits.free')}</p>
    </Sheet>
  );
}

/** Today's credits in the top bar; tapping it opens the details. Hidden when nothing limits the user. */
export function CreditChip({ quota }: { quota: Me['quota'] }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const c = credits(quota);
  if (!c) return null;
  return (
    <>
      <button
        type="button"
        className={`credit-chip credit-chip-${c.level}`}
        onClick={() => {
          haptic('select');
          setOpen(true);
        }}
        aria-label={t('credits.chip', { n: c.left })}
      >
        <Zap size={14} strokeWidth={2.8} aria-hidden="true" />
        <span>{c.left}</span>
        <Meter c={c} />
      </button>
      {open ? <CreditSheet c={c} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
