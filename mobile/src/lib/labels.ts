import type { PillKind } from '../components/ui';

/** A research note's lean, as a pill colour. */
export const leanKind = (lean?: string | null): PillKind =>
  lean === 'constructive' ? 'ok' : lean === 'cautious' ? 'bad' : 'dim';
