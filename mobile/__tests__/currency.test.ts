import { rateFor } from '@/lib/fx';

describe('currency conversion', () => {
  it('converts both ways with the live USD/CAD rate', () => {
    expect(rateFor(1.4278, 'USD', 'CAD')).toBeCloseTo(1.4278, 6);
    expect(rateFor(1.4278, 'CAD', 'USD')).toBeCloseTo(1 / 1.4278, 6);
    expect(rateFor(1.4278, 'cad', 'CAD')).toBe(1);
    expect(rateFor(null, 'USD', 'USD')).toBe(1);
  });
  it('never pretends 1:1 when the rate is unknown', () => {
    expect(rateFor(null, 'CAD', 'USD')).toBeNull();
    expect(rateFor(0, 'USD', 'CAD')).toBeNull();
    expect(rateFor(1.4278, 'EUR', 'USD')).toBeNull();
  });
});
