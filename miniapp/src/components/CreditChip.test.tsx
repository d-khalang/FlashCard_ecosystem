import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { I18nProvider } from '../i18n';
import { CreditChip } from './CreditChip';

afterEach(cleanup);

const quota = (used: number, limit: number | null) => ({ used, limit, card_cost: 2, section_cost: 1 });

function show(used: number, limit: number | null) {
  render(
    <I18nProvider initial="en">
      <CreditChip quota={quota(used, limit)} />
    </I18nProvider>,
  );
}

describe('CreditChip', () => {
  it('shows the credits left and opens the details on tap', () => {
    show(6, 40);
    const chip = screen.getByRole('button', { name: 'Credits left: 34. Show details' });
    expect(chip.textContent).toContain('34');

    fireEvent.click(chip);

    const sheet = screen.getByRole('dialog', { name: "Today's credits" });
    expect(sheet.textContent).toContain('of 40 left');
    expect(sheet.textContent).toContain('New card2');
    expect(sheet.textContent).toContain('Refresh one part1');
    expect(sheet.textContent).toContain('Failed generations are free.');
  });

  it('turns to its low look when few credits are left', () => {
    show(37, 40);
    expect(screen.getByRole('button').className).toContain('credit-chip-low');
  });

  it('is hidden when nothing limits the user', () => {
    show(5, null);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
