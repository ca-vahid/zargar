/** A notification carries the WEB app's path for what it is about. Map it to the
 *  screen that shows the same thing here; anything unknown opens the home screen. */
export function routeForWebPath(path: string | null | undefined): string {
  const p = (path ?? '').split('?')[0].replace(/\/+$/, '');
  if (!p || p === '/') return '/';
  if (p.startsWith('/inbox') || p.startsWith('/tips')) return '/tips';
  if (p.startsWith('/armed')) return '/armed';
  if (p.startsWith('/dashboard') || p.startsWith('/portfolio') || p.startsWith('/blotter')) return '/portfolio';
  if (p.includes('/scout')) return '/research';
  if (p.startsWith('/settings')) return '/settings';
  return '/';
}
