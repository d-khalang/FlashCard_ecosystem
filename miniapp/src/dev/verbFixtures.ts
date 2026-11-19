// The contract's Mini App fixtures (docs/verbs/fixtures/miniapp), loaded by file name.
// Used by the fixture test and the dev mock. Never imported by app code, so a production build
// (whose context is only miniapp/) does not need the docs folder.

const files = import.meta.glob('../../../docs/verbs/fixtures/miniapp/*.json', { eager: true, import: 'default' });

/** File name (without folder) -> parsed JSON. */
export const verbFixtures: Record<string, unknown> = Object.fromEntries(
  Object.entries(files).map(([path, data]) => [path.slice(path.lastIndexOf('/') + 1), data]),
);

export function fixture<T>(name: string): T {
  if (!(name in verbFixtures)) throw new Error(`No verbs fixture ${name}`);
  // A deep copy, so a caller can change it freely.
  return structuredClone(verbFixtures[name]) as T;
}
