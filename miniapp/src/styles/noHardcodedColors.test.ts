import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const FUNC = /\b(?:rgba?|hsla?)\(/;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe('theming', () => {
  const files = [...walk(join(SRC, 'components')), ...walk(join(SRC, 'screens')), ...walk(join(SRC, 'styles'))].filter(
    (f) => /\.(tsx?|css)$/.test(f) && !/\.test\./.test(f),
  );

  it('scans a sensible number of files', () => {
    expect(files.length).toBeGreaterThan(15);
  });

  it('keeps hex colors and color functions out of components, screens and shared styles', () => {
    const offenders = files.filter((f) => {
      const text = readFileSync(f, 'utf8');
      return HEX.test(text) || FUNC.test(text);
    });
    expect(offenders.map((f) => relative(SRC, f))).toEqual([]);
  });

  it('defines the role tokens in the theme file, with a dark scheme', () => {
    const css = readFileSync(join(SRC, 'theme', 'sticker.css'), 'utf8');
    for (const token of [
      '--color-ground',
      '--color-surface',
      '--color-ink',
      '--color-primary',
      '--color-on-primary',
      '--color-accent',
      '--color-example-bg',
      '--border-width',
      '--radius-card',
      '--shadow-card',
      '--font-display',
      '--font-body',
    ]) {
      expect(css).toContain(`${token}:`);
    }
    expect(css).toContain("[data-theme='sticker'][data-scheme='dark']");
  });
});
