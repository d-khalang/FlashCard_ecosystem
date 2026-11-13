// Only the flags for the country codes in flashcard-project/src/flashcard/schemas/languages.py,
// imported one by one so the bundle does not carry the whole set.
import br from 'flag-icons/flags/4x3/br.svg';
import cn from 'flag-icons/flags/4x3/cn.svg';
import de from 'flag-icons/flags/4x3/de.svg';
import es from 'flag-icons/flags/4x3/es.svg';
import fr from 'flag-icons/flags/4x3/fr.svg';
import gb from 'flag-icons/flags/4x3/gb.svg';
import id from 'flag-icons/flags/4x3/id.svg';
import ind from 'flag-icons/flags/4x3/in.svg';
// Iran: our own Lion and Sun flag, which represents the people rather than the Islamic Republic.
import ir from '../assets/flags/ir.svg';
import it from 'flag-icons/flags/4x3/it.svg';
import jp from 'flag-icons/flags/4x3/jp.svg';
import kr from 'flag-icons/flags/4x3/kr.svg';
import nl from 'flag-icons/flags/4x3/nl.svg';
import pl from 'flag-icons/flags/4x3/pl.svg';
import ru from 'flag-icons/flags/4x3/ru.svg';
import sa from 'flag-icons/flags/4x3/sa.svg';
import se from 'flag-icons/flags/4x3/se.svg';
import tr from 'flag-icons/flags/4x3/tr.svg';
import vn from 'flag-icons/flags/4x3/vn.svg';

export const FLAG_URLS: Readonly<Record<string, string>> = {
  br, cn, de, es, fr, gb, id, in: ind, ir, it, jp, kr, nl, pl, ru, sa, se, tr, vn,
};

export function flagUrl(country: string | null | undefined): string | null {
  if (!country) return null;
  return FLAG_URLS[country.toLowerCase()] ?? null;
}

/** Strip regional-indicator (flag emoji) characters from a label such as "Persian". */
export function cleanLabel(label: string): string {
  return label.replace(/[\u{1F1E6}-\u{1F1FF}]/gu, '').trim();
}
