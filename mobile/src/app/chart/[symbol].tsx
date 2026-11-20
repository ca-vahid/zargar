import { useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';

import { api, type ChartBar } from '@/api/endpoints';
import { CandleChart, type Level } from '@/components/CandleChart';
import { Async, Button, Card, Chips, Delta, Screen, styles, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { runAction } from '@/lib/actions';
import { dayTime, pct, price, shortDate } from '@/lib/format';
import { onBar, watchSymbol } from '@/live/socket';
import { useStore } from '@/store';

type Tf = '5m' | '15m' | '1h' | '1d';
const TF_LABEL: Record<Tf, string> = { '5m': '5 min', '15m': '15 min', '1h': '1 hour', '1d': 'Daily' };
// how much history each view asks the server for (the chart shows the latest 90 bars)
const TF_RANGE: Record<Tf, string> = { '5m': '5d', '15m': '5d', '1h': '1mo', '1d': '6mo' };
const num = (v: string | string[] | undefined): number | null => {
  const n = Number(Array.isArray(v) ? v[0] : v);
  return v != null && v !== '' && Number.isFinite(n) ? n : null;
};

export default function ChartScreen() {
  const params = useLocalSearchParams<{ symbol: string; entry?: string; stop?: string; target?: string; positionId?: string; name?: string }>();
  const symbol = String(params.symbol ?? '').toUpperCase();
  const navigation = useNavigation();
  const [tf, setTf] = useState<Tf>('15m');
  const quote = useStore((s) => s.quotes[symbol]);
  const chart = usePoll(() => api.chart(symbol, tf, TF_RANGE[tf]), tf === '1d' ? 300000 : 60000, [symbol, tf]);
  // the newest bar follows the live feed between refreshes
  const [liveBar, setLiveBar] = useState<ChartBar | null>(null);

  useEffect(() => { navigation.setOptions({ title: params.name ? String(params.name) : symbol }); }, [navigation, symbol, params.name]);
  useEffect(() => {
    watchSymbol(symbol);
    setLiveBar(null);
    return onBar((m) => { if (m.symbol === symbol && m.tf === tf) setLiveBar(m.bar as ChartBar); });
  }, [symbol, tf]);

  const bars = useMemo(() => {
    const base = chart.data?.bars ?? [];
    if (!liveBar || !base.length) return base;
    const last = base[base.length - 1];
    if (liveBar[0] === last[0]) return [...base.slice(0, -1), liveBar];
    return liveBar[0] > last[0] ? [...base, liveBar] : base;
  }, [chart.data, liveBar]);

  const levels: Level[] = useMemo(() => {
    const out: Level[] = [];
    const entry = num(params.entry), stop = num(params.stop), target = num(params.target);
    if (entry != null) out.push({ price: entry, label: 'Entry', kind: 'entry' });
    if (stop != null) out.push({ price: stop, label: 'Stop', kind: 'stop' });
    if (target != null) out.push({ price: target, label: 'Target', kind: 'target' });
    return out;
  }, [params.entry, params.stop, params.target]);

  const last = quote?.last && quote.last > 0 ? quote.last : bars.length ? bars[bars.length - 1][4] : null;
  const prev = quote?.prevClose && quote.prevClose > 0 ? quote.prevClose : null;
  const move = last != null && prev != null ? last - prev : null;
  const positionId = params.positionId ? String(params.positionId) : '';

  return (
    <Screen onRefresh={chart.refresh} refreshing={chart.refreshing}>
      <View style={{ gap: 2 }}>
        <Txt v="hero" num>{price(last)}</Txt>
        {move != null && prev != null
          ? <Delta value={move} text={`${move >= 0 ? '+' : '−'}${Math.abs(move).toFixed(2)}  ${pct((move / prev) * 100)} today`} />
          : <Txt dim>{symbol}</Txt>}
        {quote && (quote.bid > 0 || quote.ask > 0) && (
          <Txt v="small" dim num>Bid {price(quote.bid)} · Ask {price(quote.ask)}{quote.session && quote.session !== 'regular' ? ` · ${quote.session}` : ''}</Txt>
        )}
      </View>

      <Card>
        <Async state={chart}>
          {() => <CandleChart bars={bars} levels={levels} formatTime={(ts) => (tf === '1d' ? shortDate(ts) : dayTime(ts))} />}
        </Async>
        <Chips value={tf} onChange={setTf} options={(Object.keys(TF_LABEL) as Tf[]).map((k) => ({ key: k, label: TF_LABEL[k] }))} />
      </Card>

      {positionId !== '' && (
        <Card>
          <View style={styles.rowBetween}>
            <Txt v="head">This position</Txt>
            {quote?.last && num(params.entry) != null
              ? <Delta value={quote.last - (num(params.entry) as number)} text={pct(((quote.last - (num(params.entry) as number)) / (num(params.entry) as number)) * 100)} />
              : null}
          </View>
          <Txt dim num>
            In at {price(num(params.entry))}{num(params.stop) != null ? ` · stop ${price(num(params.stop))}` : ' · no stop on record'}
            {num(params.target) != null ? ` · next target ${price(num(params.target))}` : ''}
          </Txt>
          <Button kind="danger" label="Close this position"
            onPress={() => void runAction(
              { title: `Close ${symbol}?`, body: 'Sells the whole position at the market and cancels its stop. This cannot be undone.',
                confirmLabel: 'Close position', danger: true, secure: true },
              () => api.closePosition(positionId), `${symbol}: close sent`)} />
        </Card>
      )}
    </Screen>
  );
}
