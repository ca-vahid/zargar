import { router, useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { View } from 'react-native';
import Svg, { Rect } from 'react-native-svg';

import { api } from '@/api/endpoints';
import type { ScoutDossier, ScoutDossierPoint } from '@/api/types';
import { LineChart } from '@/components/LineChart';
import { Async, Button, Card, Loading, Pill, Row, Screen, Section, styles, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import type { Point } from '@/lib/chart';
import { money, price, shortDate, titleCase } from '@/lib/format';
import { leanKind } from '@/lib/labels';
import { space, useTheme } from '@/theme';

function Points({ title, items, facts }: { title: string; items: ScoutDossierPoint[]; facts: Map<string, string> }) {
  if (!items?.length) return null;
  return (
    <Section title={title}>
      <Card>
        {items.map((p, i) => (
          <View key={`${title}${i}`} style={{ gap: 4, paddingBottom: i === items.length - 1 ? 0 : space.sm }}>
            <Txt>{p.text}</Txt>
            {!!p.quote && <Txt v="small" dim style={{ fontStyle: 'italic' }}>“{p.quote}”</Txt>}
            {p.facts?.length > 0 && (
              <Txt v="small" faint num>{p.facts.map((id) => facts.get(id)).filter(Boolean).join(' · ')}</Txt>
            )}
          </View>
        ))}
      </Card>
    </Section>
  );
}

/** Revenue by quarter as plain bars: one measure, one colour, value on each bar's label. */
function Quarters({ rows, currency }: { rows: { end: string; revenue: number | null; netIncome: number | null }[]; currency: string }) {
  const t = useTheme();
  const shown = rows.filter((r) => r.revenue != null).slice(-8);
  if (shown.length < 2) return null;
  const max = Math.max(...shown.map((r) => r.revenue as number));
  const short = (v: number) => (Math.abs(v) >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : `${(v / 1e6).toFixed(0)}M`);
  return (
    <Section title={`Revenue by quarter (${currency})`}>
      <Card>
        {shown.map((r) => (
          <View key={r.end} style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
            <Txt v="small" dim num style={{ width: 54 }}>{r.end.slice(2, 7)}</Txt>
            <View style={{ flex: 1 }}>
              <Svg width="100%" height={12}>
                <Rect x={0} y={1} width={`${Math.max(2, ((r.revenue as number) / max) * 100)}%`} height={10} rx={3} fill={t.series} />
              </Svg>
            </View>
            <Txt v="small" num style={{ width: 52, textAlign: 'right' }}>{short(r.revenue as number)}</Txt>
            <Txt v="small" num dim style={{ width: 56, textAlign: 'right' }}>{r.netIncome != null ? short(r.netIncome) : '—'}</Txt>
          </View>
        ))}
        <Txt v="small" faint>Right-hand column: net income.</Txt>
      </Card>
    </Section>
  );
}

export default function DossierScreen() {
  const t = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const navigation = useNavigation();
  const state = usePoll(() => api.scoutDossier(String(id)), 0, [id]);
  const d = state.data;
  const running = d?.status === 'running';

  // a note takes about half a minute to write: keep asking until it is done
  const refresh = state.refresh;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [running, refresh]);
  useEffect(() => { if (d?.ticker) navigation.setOptions({ title: d.ticker }); }, [navigation, d?.ticker]);

  const factText = useMemo(() => new Map((d?.facts ?? []).map((f) => [f.id, `${f.label} ${f.value}`])), [d?.facts]);
  const groups = useMemo(() => {
    const out = new Map<string, NonNullable<ScoutDossier['facts']>>();
    for (const f of d?.facts ?? []) out.set(f.group, [...(out.get(f.group) ?? []), f]);
    return [...out.entries()];
  }, [d?.facts]);
  const rows = (d?.charts?.price ?? []) as { d: string; c: number; ma50?: number | null; ma200?: number | null; bench?: number | null }[];
  const priceSeries: Point[] = useMemo(() => rows.map((r) => [new Date(r.d).getTime(), r.c]), [rows]);

  return (
    <Screen onRefresh={state.refresh} refreshing={state.refreshing}>
      <Async state={state}>
        {(note: ScoutDossier) => (
          <>
            <View style={{ gap: space.sm }}>
              <Txt v="title">{note.name ?? note.ticker}</Txt>
              <View style={styles.wrap}>
                {note.status === 'running' ? <Pill kind="accent" text="Writing the note…" />
                  : note.status === 'error' ? <Pill kind="bad" text="Failed" />
                  : <Pill kind={leanKind(note.lean)} text={note.lean ? titleCase(note.lean) : 'Facts only'} />}
                {note.confidence != null && <Pill text={`Confidence ${note.confidence} of 5`} />}
                <Txt v="small" dim>{shortDate(note.createdAt)}</Txt>
              </View>
              {!!note.reason && note.status !== 'ok' && <Txt color={note.status === 'error' ? t.down : t.text2}>{note.reason}</Txt>}
              {running && <Loading />}
            </View>

            {!!note.note?.summary && <Card><Txt>{note.note.summary}</Txt>
              {!!note.note.leanWhy?.text && <Txt dim>{note.note.leanWhy.text}</Txt>}</Card>}

            {priceSeries.length > 1 && (
              <Section title="One year of price">
                <Card>
                  <LineChart points={priceSeries} color={t.series} format={(v) => price(v)} formatTime={(ts) => shortDate(ts)}
                    overlays={[
                      { label: '50-day average', color: t.series2, values: rows.map((r) => r.ma50 ?? null) },
                      { label: '200-day average', color: t.series3, values: rows.map((r) => r.ma200 ?? null) },
                    ]} />
                  <Button small kind="plain" label="Open live chart" onPress={() => router.navigate({ pathname: '/chart/[symbol]', params: { symbol: note.ticker } })} />
                </Card>
              </Section>
            )}

            <Points title="Strengths" items={note.note?.strengths ?? []} facts={factText} />
            <Points title="Concerns" items={note.note?.concerns ?? []} facts={factText} />
            <Points title="Valuation" items={note.note?.valuation ?? []} facts={factText} />
            <Points title="What to watch" items={note.note?.watch ?? []} facts={factText} />

            {(note.note?.questions?.length ?? 0) > 0 && (
              <Section title="Open questions">
                <Card>{note.note!.questions.map((q, i) => <Txt key={i}>• {q}</Txt>)}</Card>
              </Section>
            )}

            <Quarters rows={(note.charts?.quarters ?? []) as any} currency={note.charts?.currency ?? 'USD'} />

            {groups.map(([group, facts]) => (
              <Section key={group} title={titleCase(group)}>
                <Card>
                  {facts.map((f, i) => (
                    <Row key={f.id} last={i === facts.length - 1}
                      left={<Txt dim>{f.label}</Txt>}
                      right={<Txt num color={f.tone === 'good' ? t.up : f.tone === 'bad' ? t.down : t.text} style={{ maxWidth: 190, textAlign: 'right' }}>{f.value}</Txt>} />
                  ))}
                </Card>
              </Section>
            ))}

            {!!note.note?.background && (
              <Section title="Background (the model's own knowledge, not checked)">
                <Card><Txt dim>{note.note.background}</Txt></Card>
              </Section>
            )}
            {note.dropped?.length > 0 && (
              <Txt v="small" faint>{note.dropped.length} point{note.dropped.length > 1 ? 's were' : ' was'} removed for lacking a source.</Txt>
            )}
            <Txt v="small" faint>Research only. Numbers come from SEC filings and price data; cost {money(note.costUsd, 'USD')}.</Txt>
          </>
        )}
      </Async>
    </Screen>
  );
}
