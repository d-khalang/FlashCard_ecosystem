import { useI18n } from '../../i18n';
import { moodKey, personKey, tenseKey } from '../../verbs/labels';
import type { Form, Mood, Person, Slot, Tense } from '../../verbs/types';

interface TenseCardProps {
  tense: Tense;
  position: number;
  total: number;
  secondary: boolean;
  /** Persons whose forms match the search. */
  matched: ReadonlySet<Person>;
}

const primaryOf = (slot: Slot): Form | undefined => slot.forms.find((f) => f.primary) ?? slot.forms[0];

/** "stem andr-" when every simple primary form shares one stem. */
function sharedStem(tense: Tense): string | null {
  if (tense.compound) return null;
  const stems = new Set<string>();
  for (const slot of tense.slots) {
    const f = primaryOf(slot);
    if (!f || f.parts.kind !== 'simple' || !f.parts.ending) return null;
    stems.add(`${f.parts.clitic ?? ''}|${f.parts.stem}`);
  }
  const [only] = stems;
  return stems.size === 1 && only ? only.slice(only.indexOf('|') + 1) : null;
}

function hasIrregularMark(tense: Tense): boolean {
  return tense.slots.some((s) =>
    s.forms.some((f) => (f.parts.kind === 'simple' ? f.parts.irregular_stem : f.parts.irregular_participle)),
  );
}

/** One tense: simple tenses as a 2-column grid of stem + ending, compound tenses as full-width rows. */
export function TenseCard({ tense, position, total, secondary, matched }: TenseCardProps) {
  const { t } = useI18n();
  const stem = sharedStem(tense);
  return (
    <section className={secondary ? 'tense-card is-secondary' : 'tense-card'} aria-roledescription="slide" aria-labelledby={`tc-${tense.id}`}>
      <div className="tense-card-top">
        <span className="tense-mood">{t(moodKey(tense.mood))}</span>
        <span className="tense-pos">
          {secondary ? <span className="tense-secondary">{t('verbs.secondary')}</span> : null}
          {t('verbs.position', { n: position, total })}
        </span>
      </div>
      <div className="tense-card-title">
        <h2 id={`tc-${tense.id}`} className="tense-name">
          <span className="sr-only">{t(moodKey(tense.mood))} </span>
          {t(tenseKey(tense.id))}
        </h2>
        {stem ? (
          <span className="tense-stem" lang="it">
            {t('verbs.stem', { stem })}
          </span>
        ) : null}
      </div>
      <div className={tense.compound ? 'tense-rows' : 'tense-grid'} lang="it">
        {tense.slots.map((slot) => (
          <SlotView key={slot.person} slot={slot} mood={tense.mood} matched={matched.has(slot.person)} compound={tense.compound} />
        ))}
      </div>
      {hasIrregularMark(tense) ? (
        <p className="tense-legend" aria-hidden="true">
          <span className="irr">abc</span> = {t('verbs.irregular')}
        </p>
      ) : null}
    </section>
  );
}

function SlotView({ slot, mood, matched, compound }: { slot: Slot; mood: Mood; matched: boolean; compound: boolean }) {
  const { t } = useI18n();
  const primary = primaryOf(slot);
  const others = slot.forms.filter((f) => f !== primary);
  return (
    <div className={matched ? 'slot is-matched' : 'slot'}>
      <span className="slot-person">{t(personKey(mood, slot.person))}</span>
      <span className="slot-forms">
        {primary ? (
          <span className={compound ? 'slot-form slot-form-compound' : 'slot-form'}>
            <FormText form={primary} />
          </span>
        ) : (
          <span className="slot-form slot-empty">
            <span aria-hidden="true">—</span>
            <span className="sr-only">{t('verbs.noForm')}</span>
          </span>
        )}
        {others.length > 0 ? <span className="slot-also">{t('verbs.also', { forms: others.map((f) => f.text).join(', ') })}</span> : null}
      </span>
      {matched ? <span className="sr-only">{t('verbs.matched')}</span> : null}
    </div>
  );
}

function Irregular({ on, children }: { on: boolean; children: string }) {
  const { t } = useI18n();
  if (!on || !children) return <>{children}</>;
  return (
    <span className="irr">
      {children}
      <span className="sr-only"> ({t('verbs.irregular')})</span>
    </span>
  );
}

/**
 * clitic + stem + ending + enclitic (simple), or clitic + auxiliary + participle (compound). Joins exactly like the contract.
 * Only the stem (and the participle) is marked irregular: `irregular_ending` compares with the regular paradigm's
 * full ending (andrò vs andERò), which would mark every futuro ending of andare.
 */
function FormText({ form }: { form: Form }) {
  const p = form.parts;
  const clitic = p.clitic ? (p.clitic.endsWith("'") ? p.clitic : `${p.clitic} `) : '';
  if (p.kind === 'compound') {
    return (
      <>
        {clitic}
        <span className="form-aux">{p.auxiliary}</span>{' '}
        <span className="form-participle">
          <Irregular on={p.irregular_participle}>{p.participle}</Irregular>
        </span>
      </>
    );
  }
  return (
    <>
      {clitic}
      <Irregular on={p.irregular_stem}>{p.stem}</Irregular>
      {p.ending ? (
        <span className="form-ending">
          {p.ending}
        </span>
      ) : null}
      {p.enclitic ?? ''}
    </>
  );
}
