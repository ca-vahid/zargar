import { confirmAction, useStore, type ConfirmRequest } from '../store';

/** Confirm, run, and say what happened. Returns true when the action went through.
 *  A failure is shown with the server's own reason and nothing is retried. */
export async function runAction(
  ask: Omit<ConfirmRequest, 'resolve'>,
  action: () => Promise<unknown>,
  done: string,
): Promise<boolean> {
  if (!(await confirmAction(ask))) return false;
  try {
    await action();
    useStore.getState().toast('ok', done);
    return true;
  } catch (e: any) {
    useStore.getState().toast('error', e?.message ? String(e.message) : 'That did not go through');
    return false;
  }
}

/** Close an armed plan's open trade at the market; the plan itself stays armed. */
export function sellNow(symbol: string, exit: () => Promise<unknown>) {
  return runAction(
    { title: `Sell ${symbol} now?`, body: "Closes this plan's open trade at the market. The plan stays armed.",
      confirmLabel: 'Sell now', danger: true, secure: true },
    exit,
    `${symbol}: exit sent`,
  );
}
