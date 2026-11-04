import type { ComponentType } from 'react';
import { BookMarked, SlidersHorizontal, Sparkles, type LucideIcon } from 'lucide-react';
import type { TranslationKey } from './i18n/en';
import { CollectionScreen } from './screens/CollectionScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { TodayScreen } from './screens/TodayScreen';

export interface ScreenProps {
  onStudy: () => void;
}

export interface NavEntry {
  id: string;
  label: TranslationKey;
  Icon: LucideIcon;
  Screen: ComponentType<ScreenProps>;
}

/** Bottom navigation. A later feature (stories, progress, ...) adds one entry here. */
export const NAV: readonly NavEntry[] = [
  { id: 'today', label: 'nav.today', Icon: Sparkles, Screen: TodayScreen },
  { id: 'collection', label: 'nav.collection', Icon: BookMarked, Screen: CollectionScreen },
  { id: 'settings', label: 'nav.settings', Icon: SlidersHorizontal, Screen: SettingsScreen },
];
