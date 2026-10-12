import { router } from 'expo-router';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { api } from '@/api/endpoints';
import type { ScoutCandidate, ScoutDossier, ScoutLane } from '@/api/types';
import { Async, Button, Card, Delta, Pill, type PillKind, Row, Screen, Section, styles, Tabs, Txt } from '@/components/ui';
import { SymbolBadge } from '@/components/graphics';
import { usePoll } from '@/hooks/usePoll';
import { runAction } from '@/lib/actions';
import { shortDate, signedMoney, titleCase } from '@/lib/format';
import { leanKind } from '@/lib/labels';
import { radius, space, useTheme } from '@/theme';

type Tab = 'notes' | 'scout';

const KIND_LABEL: Record<string, string> = {
  s1_insider: 'Insider buying', s1u_insider: 'Insider buying (unclassified)', s2_earnings: 'Earnings reaction',
};
const statusKind = (s: string): PillKind => (s === 'pass' || s === 'entered' ? 'ok' : s === 'fail' || s === 'error' ? 'bad' : 'dim');

function Notes() {
  const t = useTheme();
  const [ticker, setTicker] = useState('');
  const [busy, setBusy] = useState(false);
  const list = usePoll(() => api.scoutDossiers(30), 30000);
  const clean = ticker.trim().toUpperCase();

  const ask = async () => {
    setBusy(true);
    let made: ScoutDossier | null = null;
    const ok = await runAction(
      { title: `Research ${clean}?`, body: 'Builds a fact sheet from SEC filings and prices, then writes one note. Takes about half a minute and costs about 10 cents.', confirmLabel: 'Research' },
      async () => { made = await api.scoutDossierRequest(clean); },
      `${clean}: research started`);
    setBusy(false);
    if (ok) {
      setTicker('');
      list.refresh();
      if (made) router.navigate({ pathname: '/dossier/[id]', params: { id: (made as ScoutDossier).id } });
    }
  };

  return (
    <>
      <Card>
        <Txt v="label" faint>Research a company</Txt>
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          <TextInput value={ticker} onChangeText={setTicker} placeholder="Ticker, e.g. AAPL" placeholderTextColor={t.text3}
            autoCapitalize="characters" autoCorrect={false} maxLength={8} accessibilityLabel="Ticker"
            style={{ flex: 1, backgroundColor: t.surface2, color: t.text, borderRadius: radius.sm, paddingHorizontal: space.md, fontSize: 15, minHeight: 46 }} />
          <Button label="Research" busy={busy} disabled={!/^[A-Z.]{1,8}$/.test(clean)} onPress={ask} />
        </View>
        <Txt v="small" dim>Research only: a note never places an order.</Txt>
      </Card>
      <Section title="Notes">
        <Card>
          <Async state={list} empty="No research notes yet. Ask for one above.">
            {(items) => items.map((d, i) => (
              <Row key={d.id} last={i === items.length - 1} onPress={() => router.navigate({ pathname: '/dossier/[id]', params: { id: d.id } })}
                left={<View style={styles.wrap}>
                  <SymbolBadge symbol={d.ticker} size={32} />
                  <Txt v="head">{d.ticker}</Txt>
                  {d.status === 'running' ? <Pill kind="accent" text="writing…" />
                    : d.status === 'error' ? <Pill kind="bad" text="failed" />
                    : <Pill kind={leanKind(d.lean)} text={d.lean ? titleCase(d.lean) : 'Facts only'} />}
                </View>}
                sub={d.summary ?? d.reason ?? d.name ?? ''}
                right={<Txt v="small" dim>{shortDate(d.createdAt)}</Txt>} />
            ))}
          </Async>
        </Card>
      </Section>
    </>
  );
}

function Scout() {
  const candidates = usePoll(() => api.scoutCandidates(14), 120000);
  const lanes = usePoll(() => api.scoutLanes(), 120000);
  return (
    <>
      <Section title="Paper results by lane">
        <Card>
          <Async state={lanes} empty="No lanes yet.">
            {(items: ScoutLane[]) => {
              const active = items.filter((l) => l.entries > 0);
              if (!active.length) return <Txt dim>No lane has taken a paper trade yet.</Txt>;
              return active.map((l, i) => (
                <Row key={l.lane} last={i === active.length - 1}
                  left={l.label.replace(/^Scout /, '')}
                  sub={`${l.open} open · ${l.closed} closed${l.hitRate != null ? ` · ${(l.hitRate * 100).toFixed(0)}% winners` : ''}`}
                  right={<Delta value={l.totalNet} text={signedMoney(l.totalNet)} />} />
              ));
            }}
          </Async>
        </Card>
      </Section>
      <Section title="Candidates, last 14 days">
        <Card>
          <Async state={candidates} empty="The screen has found no candidates in the last two weeks.">
            {(items: ScoutCandidate[]) => items.slice(0, 40).map((c, i, all) => {
              const keeps = c.verdicts.filter((v) => v.verdict === 'keep').map((v) => v.lane);
              const drops = c.verdicts.filter((v) => v.verdict === 'drop').map((v) => v.lane);
              const failed = Object.entries(c.gates ?? {}).find(([, g]) => g.status === 'fail');
              return (
                <Row key={c.id} last={i === all.length - 1}
                  onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: c.ticker } })}
                  left={<View style={styles.wrap}><SymbolBadge symbol={c.ticker} size={32} /><Txt v="head">{c.ticker}</Txt><Pill kind={statusKind(c.status)} text={titleCase(c.status)} /></View>}
                  sub={[KIND_LABEL[c.kind] ?? titleCase(c.kind),
                    keeps.length ? `keep: ${keeps.join(', ')}` : '', drops.length ? `drop: ${drops.join(', ')}` : '',
                    failed ? failed[1].why : ''].filter(Boolean).join(' · ')}
                  right={<Txt v="small" dim>{shortDate(c.signalDate)}</Txt>} />
              );
            })}
          </Async>
        </Card>
      </Section>
    </>
  );
}

export default function ResearchScreen() {
  const [tab, setTab] = useState<Tab>('notes');
  return (
    <Screen>
      <Tabs value={tab} onChange={setTab} options={[{ key: 'notes', label: 'Notes' }, { key: 'scout', label: 'Scout' }]} />
      {tab === 'notes' ? <Notes /> : <Scout />}
    </Screen>
  );
}
