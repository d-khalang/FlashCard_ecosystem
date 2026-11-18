import type { ComponentType } from 'react';
import { BookMarked, ListEnd, SlidersHorizontal, Sparkles, type LucideIcon } from 'lucide-react';
import type { TranslationKey } from './i18n/en';
import { CollectionScreen } from './screens/CollectionScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { TodayScreen } from './screens/TodayScreen';
import { VerbsScreen } from './screens/VerbsScreen';
import type { Me } from './api/types';

export interface ScreenProps {
  onStudy: () => void;
}

export interface NavEntry {
  id: string;
  label: TranslationKey;
  Icon: LucideIcon;
  Screen: ComponentType<ScreenProps>;
  /** Shown only when this `me.features` flag is true. */
  feature?: keyof NonNullable<Me['features']>;
}

/** Bottom navigation. A later feature (stories, progress, ...) adds one entry here. */
export const NAV: readonly NavEntry[] = [
  { id: 'today', label: 'nav.today', Icon: Sparkles, Screen: TodayScreen },
  { id: 'collection', label: 'nav.collection', Icon: BookMarked, Screen: CollectionScreen },
  { id: 'verbs', label: 'nav.verbs', Icon: ListEnd, Screen: VerbsScreen, feature: 'verbs' },
  { id: 'settings', label: 'nav.settings', Icon: SlidersHorizontal, Screen: SettingsScreen },
];

/** The entries this user sees: feature entries only when the server turns them on. */
export function visibleNav(me: Me | null): readonly NavEntry[] {
  return NAV.filter((n) => !n.feature || me?.features?.[n.feature] === true);
}
