import { configureClient, request, socketUrl } from '@/api/client';
import { nextBackoff } from '@/live/socket';
import { posKey, useStore } from '@/store';

const snapshot: any = {
  settings: { 'mobile.exit_only': true },
  portfolios: [{ id: 'p1', name: 'Paper', kind: 'paper', cash: 100, equity: 150, dayStart: 140, startingCash: 0 }],
  positions: [{ portfolioId: 'p1', symbol: 'SNAP', secType: 'STK', qty: 103, avgCost: 6.37, realizedPnl: 0 }],
  openOrders: [{ id: 'o1', portfolioId: 'p1', symbol: 'SNAP', side: 'SELL', orderType: 'STP', status: 'ACCEPTED', qty: 103 }],
  quotes: { SNAP: { symbol: 'SNAP', last: 6.4, bid: 6.39, ask: 6.41 } },
  halt: { engaged: false, reason: '', ts: 0, books: {}, pauses: { p9: { reason: 'drawdown', ts: 1 } } },
  proposals: [{ id: 'c1', symbol: 'AXP', status: 'pending' }, { id: 'c0', symbol: 'OLD', status: 'rejected' }],
  broker: { feedConnected: true, ibkrConnected: true, mode: 'live', feed: 'x' },
};

beforeEach(() => {
  useStore.getState().reset();
  useStore.getState().applySnapshot(snapshot);
});

describe('live state', () => {
  it('takes a snapshot and keeps only cards that still need a decision', () => {
    const s = useStore.getState();
    expect(s.synced).toBe(true);
    expect(s.proposals.map((p) => p.id)).toEqual(['c1']);
    expect(s.positions[posKey({ portfolioId: 'p1', symbol: 'SNAP' })].qty).toBe(103);
    expect(s.halt.pauses?.p9.reason).toBe('drawdown');
  });

  it('moves a filled order out of the working list', () => {
    const apply = useStore.getState().applyMessage;
    apply('order', { id: 'o2', portfolioId: 'p1', symbol: 'MO', side: 'BUY', status: 'SUBMITTED' });
    expect(Object.keys(useStore.getState().openOrders).sort()).toEqual(['o1', 'o2']);
    apply('order', { id: 'o2', portfolioId: 'p1', symbol: 'MO', side: 'BUY', status: 'FILLED' });
    apply('order', { id: 'o1', portfolioId: 'p1', symbol: 'SNAP', side: 'SELL', status: 'CANCELLED' });
    expect(Object.keys(useStore.getState().openOrders)).toEqual([]);
  });

  it('applies an equity push to its own book only, leaving missing fields alone', () => {
    useStore.getState().applyMessage('portfolio', { portfolioId: 'p1', equity: 155.5, ts: 1 });
    const b = useStore.getState().portfolios[0];
    expect(b.equity).toBe(155.5);
    expect(b.cash).toBe(100);
    expect(b.dayStart).toBe(140);
    useStore.getState().applyMessage('portfolio', { portfolioId: 'other', equity: 1 });
    expect(useStore.getState().portfolios[0].equity).toBe(155.5);
  });

  it('adds a new card on top and drops it once decided', () => {
    const apply = useStore.getState().applyMessage;
    apply('proposal', { id: 'c2', symbol: 'SNAP', status: 'pending' });
    expect(useStore.getState().proposals.map((p) => p.id)).toEqual(['c2', 'c1']);
    apply('proposal', { id: 'c2', symbol: 'SNAP', status: 'pending', qty: 5 });
    expect(useStore.getState().proposals).toHaveLength(2);
    apply('proposal', { id: 'c2', symbol: 'SNAP', status: 'approved' });
    expect(useStore.getState().proposals.map((p) => p.id)).toEqual(['c1']);
  });

  it('follows the kill switch and keeps per-book pauses the message did not carry', () => {
    useStore.getState().applyMessage('system', { kind: 'halt', engaged: true, reason: 'phone', ts: 5, books: {} });
    const h = useStore.getState().halt;
    expect(h.engaged).toBe(true);
    expect(h.reason).toBe('phone');
    expect(h.pauses?.p9.reason).toBe('drawdown');
    expect(useStore.getState().armedBump).toBe(1);
  });

  it('turns a live alert into a feed item with its level and link', () => {
    useStore.getState().applyMessage('technique', { kind: 'alert', level: 'critical', text: 'MGM: exit failed', runId: 'r1', symbol: 'MGM' });
    const a = useStore.getState().liveAlerts[0];
    expect(a.level).toBe('error');
    expect(a.body).toBe('MGM: exit failed');
    expect(a.url).toBe('/armed/r1');
    useStore.getState().applyMessage('technique', { kind: 'alert', level: 'info', text: 'feed recovered' });
    expect(useStore.getState().liveAlerts[0].level).toBe('info');
    expect(useStore.getState().liveAlerts).toHaveLength(2);
  });

  it('ignores topics it has no use for', () => {
    const before = useStore.getState();
    before.applyMessage('chat', { anything: 1 });
    before.applyMessage('tipAnalyst', { runId: 'x' });
    expect(useStore.getState().portfolios).toBe(before.portfolios);
  });

  it('forgets everything live on sign-out', () => {
    useStore.getState().reset();
    const s = useStore.getState();
    expect(s.synced).toBe(false);
    expect(s.portfolios).toEqual([]);
    expect(s.proposals).toEqual([]);
  });
});

describe('http client', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; });

  it('builds the socket address from the server address and token', () => {
    configureClient({ baseUrl: 'https://desk.example.net/', token: 'a b' });
    expect(socketUrl()).toBe('wss://desk.example.net/ws?token=a%20b&client=phone');
    configureClient({ baseUrl: 'http://127.0.0.1:8420', token: null });
    expect(socketUrl()).toBe('ws://127.0.0.1:8420/ws?client=phone');
  });

  it('sends the bearer token and declares itself a phone', async () => {
    configureClient({ baseUrl: 'https://desk.example.net', token: 'tok' });
    const calls: any[] = [];
    globalThis.fetch = (async (url: string, init: any) => {
      calls.push({ url, init });
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    }) as any;
    await request('POST', '/api/halt', { reason: 'phone' });
    expect(calls[0].url).toBe('https://desk.example.net/api/halt');
    expect(calls[0].init.headers.Authorization).toBe('Bearer tok');
    expect(calls[0].init.headers['X-Zargar-Client']).toBe('phone');
    expect(calls[0].init.body).toBe('{"reason":"phone"}');
  });

  it("reports the server's own reason and signs out on 401", async () => {
    let signedOut = 0;
    configureClient({ baseUrl: 'https://desk.example.net', token: 'tok', onUnauthorized: () => { signedOut++; } });
    globalThis.fetch = (async () => ({ ok: false, status: 400, statusText: 'Bad Request', json: async () => ({ detail: 'the plan changed since it was displayed' }) })) as any;
    await expect(request('POST', '/api/proposals/x/approve', {})).rejects.toThrow('the plan changed since it was displayed');
    expect(signedOut).toBe(0);
    globalThis.fetch = (async () => ({ ok: false, status: 401, statusText: 'Unauthorized', json: async () => ({ detail: 'sign in' }) })) as any;
    await expect(request('GET', '/api/portfolios')).rejects.toThrow('sign in');
    expect(signedOut).toBe(1);
    // a failed sign-in attempt is not a lost session
    await expect(request('POST', '/api/auth/google', {})).rejects.toThrow();
    expect(signedOut).toBe(1);
  });

  it('says so plainly when the server cannot be reached', async () => {
    configureClient({ baseUrl: 'https://desk.example.net', token: 'tok' });
    globalThis.fetch = (async () => { throw new TypeError('Network request failed'); }) as any;
    await expect(request('GET', '/api/health')).rejects.toThrow('Cannot reach the server');
  });
});

describe('reconnect', () => {
  it('backs off from one second to a fifteen second ceiling', () => {
    let ms = 1000;
    const seen = [ms];
    for (let i = 0; i < 6; i++) { ms = nextBackoff(ms); seen.push(ms); }
    expect(seen).toEqual([1000, 2000, 4000, 8000, 15000, 15000, 15000]);
  });
});
