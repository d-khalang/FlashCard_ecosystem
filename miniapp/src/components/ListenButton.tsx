import { useState, type MouseEvent } from 'react';
import { Loader2, Volume2 } from 'lucide-react';
import { asApiError } from '../api/errors';
import type { AudioPart } from '../api/types';
import { useApp } from '../app/context';
import { useI18n } from '../i18n';

/** A part of a saved card, or of an unsaved preview by the key the preview gave it. */
export type ListenSource = { expressionId: string; part: AudioPart } | { speechKey: string };

interface Props {
  source: ListenSource;
  /** What is spoken: a refreshed section is a new clip. */
  text: string;
  small?: boolean;
  disabled?: boolean;
}

export function ListenButton({ source, text, small = false, disabled = false }: Props) {
  const { api, player, toast } = useApp();
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);

  const listen = async (event: MouseEvent) => {
    // On the front of a card, a tap anywhere else reveals the answer.
    event.stopPropagation();
    setLoading(true);
    try {
      if ('speechKey' in source) {
        await player.play(source.speechKey, () => api.speech(source.speechKey));
      } else {
        await player.play(`${source.expressionId}/${source.part}/${text}`, () => api.audio(source.expressionId, source.part));
      }
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
