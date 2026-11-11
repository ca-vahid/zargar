import { router } from 'expo-router';
import { useMemo } from 'react';
import { View } from 'react-native';

import { ApiError } from '@/api/client';
import { api, type AlertItem } from '@/api/endpoints';
import { Card, Empty, Loading, Pill, Problem, Row, Screen, styles, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { dayTime, titleCase } from '@/lib/format';
import { routeForWebPath } from '@/lib/links';
import { useStore } from '@/store';

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

export default function AlertsScreen() {
  const feed = usePoll(loadAlerts, 30000);
  const live = useStore((s) => s.liveAlerts);
  // alerts that arrived over the live link since the last fetch sit on top
  const items = useMemo(() => {
    const newest = feed.data?.[0]?.ts ?? '';
    return [...live.filter((a) => a.ts > newest), ...(feed.data ?? [])];
  }, [live, feed.data]);

  return (
    <Screen onRefresh={feed.refresh} refreshing={feed.refreshing}>
      <Card>
        {feed.data == null && feed.error ? <Problem error={feed.error} onRetry={feed.refresh} />
          : feed.data == null ? <Loading />
          : items.length === 0 ? <Empty text="Nothing has been flagged. Alerts from plans, positions, brokers and the kill switch appear here." />
          : items.map((a, i) => (
            <Row key={a.id} last={i === items.length - 1}
              onPress={a.url ? () => router.navigate(routeForWebPath(a.url) as any) : undefined}
              left={<View style={styles.wrap}>
                <Txt v="head">{a.title}</Txt>
                <Pill kind={a.level === 'error' ? 'bad' : a.level === 'warning' ? 'warn' : 'dim'}
                  text={a.kind === 'alert' ? titleCase(a.level) : titleCase(a.kind.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase())} />
              </View>}
              sub={<Txt v="small" dim numberOfLines={4}>{a.body}</Txt>}
              right={<Txt v="small" dim num>{dayTime(a.ts)}</Txt>} />
          ))}
      </Card>
    </Screen>
  );
}
