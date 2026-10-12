/** USD/CAD is the only pair this desk holds. A missing rate returns null — never a
 *  silent 1:1, which once made a Canadian book read as a 24% loss on the web app. */
export function rateFor(usdCad: number | null | undefined, from: string, to: string): number | null {
  const f = (from || 'USD').toUpperCase();
  const t = (to || 'USD').toUpperCase();
  if (f === t) return 1;
  if (!usdCad || usdCad <= 0) return null;
  if (f === 'USD' && t === 'CAD') return usdCad;
  if (f === 'CAD' && t === 'USD') return 1 / usdCad;
  return null;
}
