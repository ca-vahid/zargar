import { useState } from 'react';
import { View } from 'react-native';

import { api } from '@/api/endpoints';
import type { Portfolio, Proposal, Signal } from '@/api/types';
import { Async, Button, Card, Empty, Pill, type PillKind, Row, Screen, styles, Tabs, Txt } from '@/components/ui';
import { EmptyArt, Meter, SymbolBadge } from '@/components/graphics';
import { usePoll } from '@/hooks/usePoll';
import { useWorkspace } from '@/hooks/useWorkspace';
import { runAction } from '@/lib/actions';
import { GROUP_LABEL, groupOf, workspaceOf } from '@/lib/books';
import { dayTime, money, price, qty, sourceLabel, titleCase, until } from '@/lib/format';
import { confirmAction, useStore } from '@/store';
import { space, useTheme } from '@/theme';

type Tab = 'cards' | 'tips' | 'history';

const verdictKind = (v?: string | null): PillKind => (v === 'take' ? 'ok' : v === 'skip' ? 'bad' : v === 'watch' ? 'warn' : 'dim');

function readinessOf(p: Proposal): { label: string; kind: PillKind; blockers: string[] } {
  const rd = p.context?.readiness;
  if (!rd) return { label: 'not checked yet', kind: 'dim', blockers: [] };
  const stale = rd.validUntil ? Date.now() > new Date(rd.validUntil).getTime() : false;
  const blockers = (rd.blockers ?? []).map((b: any) => String(b.message ?? b.detail ?? b.code ?? b));
  if (rd.state === 'expired') return { label: 'expired', kind: 'bad', blockers };
  if (rd.state === 'blocked') return { label: 'blocked', kind: 'bad', blockers };
  if (stale) return { label: 'needs refresh', kind: 'warn', blockers };
  if (rd.state === 'ready') return { label: 'ready', kind: 'ok', blockers };
  return { label: 'advisory checks', kind: 'dim', blockers };
}

function CardView({ p, book }: { p: Proposal; book?: Portfolio }) {
  const t = useTheme();
  const [busy, setBusy] = useState<'approve' | 'refresh' | 'decline' | null>(null);
  const [open, setOpen] = useState(false);
  const ctx = p.context ?? {};
  const analyst = ctx.analyst as { verdict?: string; rationale?: string; confidence?: number; invalidation?: string } | undefined;
  const exit = ctx.exitPlan as { targets?: number[]; fractions?: number[]; underlyingStop?: number | null; maxHoldSessions?: number | null } | undefined;
  const vehicle = ctx.vehicle as { display?: string; underlying?: string } | undefined;
  const isOption = p.secType === 'OPT' || p.secType === 'SPREAD';
  const cost = p.limitPrice != null ? p.limitPrice * p.qty * (isOption ? 100 : 1) : null;
  const rd = readinessOf(p);
  const real = book?.kind === 'live';
  const cur = book?.baseCurrency ?? 'USD';
  const what = isOption ? vehicle?.display ?? p.symbol : `${p.symbol} shares`;
  const stop = p.bracket?.stop_loss ?? exit?.underlyingStop ?? null;

  // Approve always re-runs the server's checks first, shows the refreshed numbers,
  // and binds the approval to exactly that plan (its fingerprint). A card the checks
  // block cannot be approved from the phone — overrides stay on the desk.
  const approve = async () => {
    setBusy('approve');
    try {
      const fresh = await api.revalidateProposal(p.id);
      useStore.getState().applyMessage('proposal', fresh);
      const check = readinessOf(fresh);
      if (check.kind === 'bad') {
        useStore.getState().toast('error', `${fresh.symbol}: ${check.label}${check.blockers[0] ? ` — ${check.blockers[0]}` : ''}`);
        return;
      }
      const freshOption = fresh.secType === 'OPT' || fresh.secType === 'SPREAD';
      const freshCost = fresh.limitPrice != null ? fresh.limitPrice * fresh.qty * (freshOption ? 100 : 1) : null;
      const ok = await confirmAction({
        title: `${real ? 'REAL MONEY — buy' : 'Buy'} ${fresh.symbol}?`,
        body: real ? `This order goes to your real account (${book?.name}).` : undefined,
        lines: [
          ['Book', book?.name ?? fresh.portfolioId],
          ['Order', `${titleCase(fresh.side.toLowerCase())} ${qty(fresh.qty)} at ${price(fresh.limitPrice)}`],
          ['Cost', money(freshCost, cur)],
          ['Stop', price(fresh.bracket?.stop_loss ?? stop)],
        ],
        confirmLabel: 'Approve', danger: real, secure: true,
      });
      if (!ok) return;
      await api.approveProposal(fresh.id, fresh.context?.readiness?.fingerprint ?? null);
      useStore.getState().toast('ok', `${fresh.symbol}: approved`);
    } catch (e: any) {
      useStore.getState().toast('error', e?.message ? String(e.message) : 'Approval did not go through');
    } finally {
      setBusy(null);
    }
  };

  const refresh = async () => {
    setBusy('refresh');
    try {
      useStore.getState().applyMessage('proposal', await api.revalidateProposal(p.id));
    } catch (e: any) {
      useStore.getState().toast('error', e?.message ? String(e.message) : 'Refresh failed');
    } finally {
      setBusy(null);
    }
  };

  const decline = async () => {
    setBusy('decline');
    await runAction({ title: `Decline ${p.symbol}?`, body: 'The card is closed and no order is placed.', confirmLabel: 'Decline', danger: true },
      () => api.rejectProposal(p.id), `${p.symbol}: declined`);
    setBusy(null);
  };

  return (
    <Card style={{ borderLeftWidth: 4, borderLeftColor: analyst?.verdict === 'take' ? t.up : analyst?.verdict === 'skip' ? t.down : analyst?.verdict === 'watch' ? t.warn : t.line }}>
      <View style={styles.rowBetween}>
        <View style={styles.wrap}>
          <SymbolBadge symbol={vehicle?.underlying ?? p.symbol} />
          <Txt v="title">{vehicle?.underlying ?? p.symbol}</Txt>
          <Pill kind={real ? 'bad' : 'dim'} text={real ? 'REAL MONEY' : book ? GROUP_LABEL[groupOf(book)] : 'Book'} />
        </View>
        <Txt v="small" dim>{until(p.expiresAt)}</Txt>
      </View>
      <Txt>{titleCase(p.side.toLowerCase())} {qty(p.qty)} × {what} at {price(p.limitPrice)}{cost != null ? ` · ${money(cost, cur)}` : ''}</Txt>
      <Txt v="small" dim>
        {book?.name ?? ''}{ctx.sourceName ? ` · from ${sourceLabel(ctx.sourceName)}` : ''} · {dayTime(p.createdAt)}
      </Txt>
      <View style={styles.wrap}>
        {analyst?.verdict && <Pill kind={verdictKind(analyst.verdict)} text={`Analyst: ${analyst.verdict}${analyst.confidence != null ? ` ${(analyst.confidence * 100).toFixed(0)}%` : ''}`} />}
        <Pill kind={rd.kind} text={`Checks: ${rd.label}`} />
      </View>
      {analyst?.confidence != null && (
        <View style={{ gap: 4 }}>
          <Txt v="small" dim>Analyst confidence</Txt>
          <Meter value={analyst.confidence} color={analyst.verdict === 'take' ? t.up : analyst.verdict === 'skip' ? t.down : t.warn} />
        </View>
      )}
      {(stop != null || exit?.targets?.length) && (
        <Txt v="small" dim num>
          {stop != null ? `Stop ${price(stop)}` : 'No stop on the card'}
          {exit?.targets?.length ? ` · targets ${exit.targets.map((x) => price(x)).join(', ')}` : ''}
          {exit?.maxHoldSessions ? ` · hold up to ${exit.maxHoldSessions} sessions` : ''}
        </Txt>
      )}
      {rd.blockers.map((b) => <Txt key={b} v="small" color={t.down}>• {b}</Txt>)}
      {!!analyst?.rationale && (
        <View style={{ gap: 4 }}>
          <Txt dim numberOfLines={open ? undefined : 4}>{analyst.rationale}</Txt>
          {open && !!analyst.invalidation && <Txt v="small" dim>Wrong if: {analyst.invalidation}</Txt>}
          <Txt v="small" color={t.accent} onPress={() => setOpen((v) => !v)}>{open ? 'Show less' : 'Read the full reasoning'}</Txt>
        </View>
      )}
      <View style={{ flexDirection: 'row', gap: space.sm, marginTop: space.xs }}>
        <Button small kind="plain" label="Decline" busy={busy === 'decline'} disabled={!!busy} onPress={decline} style={{ flex: 1 }} />
        <Button small kind="plain" label="Refresh" busy={busy === 'refresh'} disabled={!!busy} onPress={refresh} style={{ flex: 1 }} />
        <Button small kind="good" label="Approve" busy={busy === 'approve'} disabled={!!busy || rd.label === 'expired'} onPress={approve} style={{ flex: 1.3 }} />
      </View>
    </Card>
  );
}

function SignalRow({ s, last }: { s: Signal; last: boolean }) {
  const verdict = s.extraction?.analyst?.verdict as string | undefined;
  const contract = s.instrument && s.instrument !== 'shares' && s.instrument !== 'unspecified'
    ? ` ${s.strike ?? ''}${s.instrument === 'put' ? 'P' : s.instrument === 'call' ? 'C' : ''}${s.expiry ? ` ${s.expiry.slice(5)}` : ''}` : '';
  return (
    <Row last={last}
      left={<View style={styles.wrap}>
        <SymbolBadge symbol={s.ticker} size={30} />
        <Txt v="head">{s.ticker}{contract}</Txt>
        <Pill kind={s.direction === 'short' ? 'bad' : 'ok'} text={s.action === 'open' ? s.direction : s.action} />
        {verdict && <Pill kind={verdictKind(verdict)} text={verdict} />}
      </View>}
      sub={<View style={{ gap: 2 }}>
        <Txt v="small" dim>{sourceLabel(s.sourceName)} · {titleCase(s.status)}</Txt>
        {!!s.thesisSummary && <Txt v="small" dim numberOfLines={3}>{s.thesisSummary}</Txt>}
      </View>}
      right={<Txt v="small" dim num>{dayTime(s.createdAt)}</Txt>} />
  );
}

export default function TipsScreen() {
  const [tab, setTab] = useState<Tab>('cards');
  const ws = useWorkspace();
  const allProposals = useStore((s) => s.proposals);
  const portfolios = useStore((s) => s.portfolios);
  // a card belongs to the workspace of the book it would trade in
  const proposals = allProposals.filter((p) => workspaceOf(portfolios.find((b) => b.id === p.portfolioId)?.kind) === ws);
  const elsewhere = allProposals.length - proposals.length;
  const signals = usePoll(() => (tab === 'tips' ? api.signals(40) : Promise.resolve(null)), tab === 'tips' ? 45000 : 0, [tab]);
  const history = usePoll(() => (tab === 'history' ? api.proposals(true, 40) : Promise.resolve(null)), tab === 'history' ? 60000 : 0, [tab]);
  const bookOf = (pid: string) => portfolios.find((b) => b.id === pid);

  return (
    <Screen onRefresh={tab === 'tips' ? signals.refresh : tab === 'history' ? history.refresh : undefined}
      refreshing={signals.refreshing || history.refreshing}>
      <Tabs value={tab} onChange={setTab} options={[
        { key: 'cards', label: 'Cards', badge: proposals.length },
        { key: 'tips', label: 'Tips' },
        { key: 'history', label: 'History' },
      ]} />

      {tab === 'cards' && (
        proposals.length === 0
          ? <EmptyArt text={elsewhere > 0
              ? `${elsewhere} card${elsewhere > 1 ? 's are' : ' is'} waiting in the ${ws === 'live' ? 'Practice' : 'Live'} workspace. Switch at the top to see ${elsewhere > 1 ? 'them' : 'it'}.`
              : 'No approval cards are waiting. A new one appears here the moment a tip needs your decision.'} />
          : proposals.map((p) => <CardView key={p.id} p={p} book={bookOf(p.portfolioId)} />)
      )}

      {tab === 'tips' && (
        <Card>
          <Async state={signals as any} empty="No tips yet.">
            {(list: Signal[]) => list.map((s, i) => <SignalRow key={s.id} s={s} last={i === list.length - 1} />)}
          </Async>
        </Card>
      )}

      {tab === 'history' && (
        <Card>
          <Async state={history as any} empty="No cards have been decided yet.">
            {(list: Proposal[]) => list.filter((p) => p.status !== 'pending' && workspaceOf(bookOf(p.portfolioId)?.kind) === ws).map((p, i, all) => {
              const book = bookOf(p.portfolioId);
              const filled = p.outcome?.filledQty ? ` · filled ${qty(p.outcome.filledQty)} at ${price(p.outcome.avgFillPrice)}` : '';
              const kind: PillKind = p.status === 'approved' || p.status === 'executed' ? 'ok' : p.status === 'rejected' ? 'bad' : 'dim';
              return (
                <Row key={p.id} last={i === all.length - 1}
                  left={<View style={styles.wrap}><SymbolBadge symbol={p.symbol} size={30} /><Txt v="head">{p.symbol}</Txt><Pill kind={kind} text={titleCase(p.status)} /></View>}
                  sub={`${titleCase(p.side.toLowerCase())} ${qty(p.qty)} at ${price(p.limitPrice)} · ${book?.name ?? ''}${p.decidedVia ? ` · by ${p.decidedVia}` : ''}${filled}`}
                  right={<Txt v="small" dim num>{dayTime(p.createdAt)}</Txt>} />
              );
            })}
          </Async>
        </Card>
      )}
    </Screen>
  );
}
