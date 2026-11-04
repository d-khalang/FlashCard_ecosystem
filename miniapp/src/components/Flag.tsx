import { cleanLabel, flagUrl } from './flags';

interface FlagProps {
  country: string | null | undefined;
  /** Language name, used as the accessible label. */
  name: string;
  className?: string;
}

/** Small SVG flag. Returns null when the country has no flag; the caller then shows the label. */
export function Flag({ country, name, className }: FlagProps) {
  const url = flagUrl(country);
  if (!url) return null;
  return <img className={`flag ${className ?? ''}`} src={url} alt={cleanLabel(name)} width={24} height={18} />;
}
