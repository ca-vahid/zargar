import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { api, type ScoutAgent } from '@/api/endpoints';
import type { ScoutCandidate, ScoutDossier, ScoutLane } from '@/api/types';
import { Async, Button, Card, Delta, Pill, type PillKind, Row, Screen, Section, styles, Tabs, Txt } from '@/components/ui';
import { SymbolBadge } from '@/components/graphics';
import { usePoll } from '@/hooks/usePoll';
import { runAction } from '@/lib/actions';
import { shortDate, signedMoney, titleCase } from '@/lib/format';
import { leanKind } from '@/lib/labels';
import { radius, space, useTheme } from '@/theme';

type Tab = 'notes' | 'scout' | 'agent';

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

/** The Scout agent: the model that proposes its own trades on practice books each morning.
 *  Research only — nothing here trades a real or paper account. */
function Agent() {
  const t = useTheme();
  const state = usePoll(() => api.scoutAgent(), 120000, [], 'scout:agent');
  return (
    <Async state={state}>
      {(a: ScoutAgent) => {
        const gate = a.scorecard?.gate;
        // the agent's own trades; the screen and random books are only the yardsticks
        const open = a.lanes.filter((l) => /claude|gpt/i.test(l.lane)).flatMap((l) => l.openTrades.map((x) => ({ ...x, book: l.label.replace(/^Scout Agent /, '') })));
        const lessons = a.lessons.filter((l) => l.status === 'active');
        return (
          <>
            <Card style={{ borderLeftWidth: 4, borderLeftColor: gate?.passed ? t.up : t.warn }}>
              <View style={styles.rowBetween}>
                <Txt v="head">Has it proven an edge?</Txt>
                <Pill kind={gate?.passed ? 'ok' : 'warn'} text={gate?.passed ? 'Yes' : 'Not yet'} />
              </View>
              <Txt v="small" dim>
                {a.enabled ? 'Running each weekday morning on practice books' : 'Switched off'}
                {a.scorecard?.sampleStart ? ` · measured since ${shortDate(`${a.scorecard.sampleStart}T12:00:00`)}` : ''}
              </Txt>
              {(gate?.checks ?? []).map((c) => (
                <View key={c.name} style={{ flexDirection: 'row', gap: space.sm, alignItems: 'flex-start' }}>
                  <Ionicons name={c.ok ? 'checkmark-circle' : 'ellipse-outline'} size={16} color={c.ok ? t.up : t.text3} style={{ marginTop: 2 }} />
                  <Txt v="small" style={{ flex: 1 }}>{titleCase(c.name)}</Txt>
                  <Txt v="small" dim num>{typeof c.have === 'number' ? Number(c.have.toFixed(2)) : c.have ?? '—'} (needs {c.need.replace('>=', '≥')})</Txt>
                </View>
              ))}
            </Card>

            <Section title="Its books against the comparisons">
              <Card>
                {a.lanes.map((l, i) => (
                  <Row key={l.lane} last={i === a.lanes.length - 1}
                    left={l.label.replace(/^Scout Agent /, '').replace(/^\w/, (c) => c.toUpperCase())}
                    sub={`${l.open} open · ${l.closed} closed${l.hitRate != null && l.closed ? ` · ${(l.hitRate * 100).toFixed(0)}% winners` : ''}${l.pending ? ` · ${l.pending} waiting` : ''}`}
                    right={<Delta value={l.totalNet} text={signedMoney(l.totalNet)} />}
                    rightSub={`banked ${signedMoney(l.realizedNet)}`} />
                ))}
              </Card>
            </Section>

            <Section title={`The agent's open trades · ${open.length}`}>
              <Card>
                {open.length === 0 && <Txt dim>No agent trade is open.</Txt>}
                {open.slice(0, 20).map((x, i, all) => (
                  <Row key={x.id} last={i === all.length - 1}
                    onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: x.ticker } })}
                    left={<View style={styles.wrap}><SymbolBadge symbol={x.ticker} size={30} /><Txt v="head">{x.ticker}</Txt><Pill kind="dim" text={x.book} /></View>}
                    sub={x.reason ?? ''}
                    right={<Txt v="small" dim>{shortDate(`${x.entryDate}T12:00:00`)}</Txt>} />
                ))}
              </Card>
            </Section>

            {lessons.length > 0 && (
              <Section title="What it has learned">
                {lessons.map((l) => (
                  <Card key={l.id}>
                    <Txt v="small" dim>{l.text}</Txt>
                    {!!l.effectiveFrom && <Txt v="small" faint>In use from {shortDate(`${l.effectiveFrom}T12:00:00`)}</Txt>}
                  </Card>
                ))}
              </Section>
            )}

            <Section title="Recent runs">
              <Card>
                {a.runs.length === 0 && <Txt dim>No runs yet.</Txt>}
                {a.runs.slice(0, 10).map((r, i, all) => (
                  <Row key={r.id} last={i === all.length - 1}
                    left={<View style={styles.wrap}>
                      <Txt v="head">{titleCase(r.lane)}</Txt>
                      <Pill kind={r.status === 'ok' ? 'dim' : 'bad'} text={r.lane === 'review' ? 'weekly review' : `${r.proposals.length} idea${r.proposals.length === 1 ? '' : 's'}`} />
                    </View>}
                    sub={<Txt v="small" dim numberOfLines={3}>{r.reason ?? ''}</Txt>}
                    right={<Txt v="small" dim>{shortDate(`${r.day}T12:00:00`)}</Txt>} />
                ))}
              </Card>
            </Section>
          </>
        );
      }}
    </Async>
  );
}

export default function ResearchScreen() {
  const [tab, setTab] = useState<Tab>('notes');
  return (
    <Screen>
      <Tabs value={tab} onChange={setTab} options={[{ key: 'notes', label: 'Notes' }, { key: 'scout', label: 'Scout' }, { key: 'agent', label: 'Agent' }]} />
      {tab === 'notes' ? <Notes /> : tab === 'scout' ? <Scout /> : <Agent />}
    </Screen>
  );
}
