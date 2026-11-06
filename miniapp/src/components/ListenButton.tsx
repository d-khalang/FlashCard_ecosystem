import { useState, type MouseEvent } from 'react';
import { Loader2, Volume2 } from 'lucide-react';
import { asApiError } from '../api/errors';
import type { AudioPart } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';

interface Props {
  expressionId: string;
  part: AudioPart;
  /** What is spoken: a refreshed section is a new clip. */
  text: string;
  small?: boolean;
  disabled?: boolean;
}

export function ListenButton({ expressionId, part, text, small = false, disabled = false }: Props) {
  const { api, player, toast } = useApp();
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);

  const listen = async (event: MouseEvent) => {
    // On the front of a card, a tap anywhere else reveals the answer.
    event.stopPropagation();
    setLoading(true);
    try {
      await player.play(`${expressionId}/${part}/${text}`, () => api.audio(expressionId, part));
    } catch (e) {
      toast(t(asApiError(e).code === 'audio_limit' ? 'audio.limit' : 'audio.failed'), 'error');
    } finally {
      setLoading(false);
    }
  };

  const Icon = loading ? Loader2 : Volume2;
  return (
    <button
      type="button"
      className={small ? 'icon-btn icon-btn-small listen-btn' : 'icon-btn listen-btn'}
      onClick={(event) => void listen(event)}
      disabled={loading || disabled}
      aria-label={t('audio.listen')}
      title={t('audio.listen')}
    >
      <Icon size={19} strokeWidth={2.5} aria-hidden="true" className={loading ? 'spin' : undefined} />
    </button>
  );
}
