import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';

import { ApiError } from '@/api/client';
import { api, type AlertItem } from '@/api/endpoints';
import { Card, Chips, Empty, Problem, Screen, SkeletonRows, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { foldAlerts, type AlertGroup, alertLabel } from '@/lib/alerts';
import { dayTime } from '@/lib/format';
import { routeForWebPath } from '@/lib/links';
import { useStore } from '@/store';
import { space, useTheme } from '@/theme';

/** Older servers have no alerts feed: fall back to the plan-error journal so the
 *  screen still shows the most common alert until the backend update ships. */
async function loadAlerts(): Promise<AlertItem[]> {
  try {
    return await api.alerts(80);
  } catch (e) {
    if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 405)) throw e;
    const events = await api.events('TechniquePlanError', 60);
    return events.map((ev) => ({
      id: String(ev.id), ts: ev.ts, kind: ev.type,
      level: ev.payload?.level === 'warning' ? 'warning' : ev.payload?.level === 'info' ? 'info' : 'error',
      title: String(ev.payload?.symbol ?? 'Plan'), body: String(ev.payload?.error ?? ''),
      symbol: ev.payload?.symbol ?? null, url: ev.payload?.runId ? `/armed/${ev.payload.runId}` : null,
    }));
  }
}

type Filter = 'all' | 'problems';
type IconName = keyof typeof Ionicons.glyphMap;
const ICON: Record<AlertItem['level'], IconName> = { error: 'alert-circle', warning: 'warning', info: 'information-circle' };

function AlertRow({ g, last }: { g: AlertGroup; last: boolean }) {
  const t = useTheme();
  const a = g.item;
  const ink = a.level === 'error' ? t.down : a.level === 'warning' ? t.warn : t.text3;
  const target = a.url ? routeForWebPath(a.url) : null;
  return (
    <Pressable disabled={!target} onPress={() => target && router.navigate(target as any)} android_ripple={{ color: t.surface3 }}
      style={{ flexDirection: 'row', gap: space.md, paddingVertical: space.md, borderBottomWidth: last ? 0 : 0.5, borderBottomColor: t.line }}>
      <View style={{ width: 34, height: 34, borderRadius: 17, backgroundColor: `${ink}22`, alignItems: 'center', justifyContent: 'center' }}>
        <Ionicons name={ICON[a.level]} size={18} color={ink} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: space.sm }}>
          <Txt style={{ fontWeight: '700', flex: 1 }} numberOfLines={2}>{a.title}</Txt>
          <Txt v="small" dim num>{dayTime(a.ts)}</Txt>
        </View>
        <Txt v="small" color={ink} style={{ fontWeight: '600' }}>
          {alertLabel(a)}{g.count > 1 ? ` · ${g.count} times, first ${dayTime(g.firstTs)}` : ''}
        </Txt>
        {!!a.body && <Txt v="small" dim numberOfLines={4}>{a.body}</Txt>}
      </View>
    </Pressable>
  );
}

export default function AlertsScreen() {
  const feed = usePoll(loadAlerts, 30000, [], 'alerts');
  const live = useStore((s) => s.liveAlerts);
  const [filter, setFilter] = useState<Filter>('all');
  // alerts that arrived over the live link since the last fetch sit on top
  const groups = useMemo(() => {
    const newest = feed.data?.[0]?.ts ?? '';
    const items = [...live.filter((a) => a.ts > newest), ...(feed.data ?? [])];
    return foldAlerts(filter === 'problems' ? items.filter((a) => a.level === 'error') : items);
  }, [live, feed.data, filter]);
  const problems = useMemo(() => (feed.data ?? []).filter((a) => a.level === 'error').length, [feed.data]);

  return (
    <Screen onRefresh={feed.refresh} refreshing={feed.refreshing}>
      <Chips value={filter} onChange={setFilter}
        options={[{ key: 'all', label: 'Everything' }, { key: 'problems', label: `Problems${problems ? ` · ${problems}` : ''}` }]} />
      <Card>
        {feed.data == null && feed.error ? <Problem error={feed.error} onRetry={feed.refresh} />
          : feed.data == null ? <SkeletonRows rows={6} />
          : groups.length === 0 ? <Empty text={filter === 'problems' ? 'No problems on record.' : 'Nothing has been flagged. Alerts from plans, positions, brokers and the kill switch appear here.'} />
          : groups.map((g, i) => <AlertRow key={g.item.id} g={g} last={i === groups.length - 1} />)}
      </Card>
    </Screen>
  );
}
