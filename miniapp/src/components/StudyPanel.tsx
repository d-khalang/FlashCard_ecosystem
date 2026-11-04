import type { ReactNode } from 'react';
import { Mascot, type MascotName } from './Mascot';

interface StudyPanelProps {
  mascot: MascotName;
  animated?: boolean;
  title?: string;
  body?: string;
  children?: ReactNode;
  live?: boolean;
}

/** Centered card-shaped panel used for loading, checkpoint, finished and quota states. */
export function StudyPanel({ mascot, animated, title, body, children, live }: StudyPanelProps) {
  return (
    <section className="panel" aria-live={live ? 'polite' : undefined}>
      <Mascot name={mascot} size="medium" animated={animated} />
      {title ? <h1 className="panel-title">{title}</h1> : null}
      {body ? <p className="panel-body">{body}</p> : null}
      {children}
    </section>
  );
}
