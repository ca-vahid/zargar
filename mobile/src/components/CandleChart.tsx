import { useMemo, useRef, useState } from 'react';
import { PanResponder, View } from 'react-native';
import Svg, { G, Line, Rect, Text as SvgText } from 'react-native-svg';

import type { ChartBar } from '../api/endpoints';
import { extent, type Frame, tickLabel, ticks, yAt } from '../lib/chart';
import { price } from '../lib/format';
import { useTheme } from '../theme';
import { Txt } from './ui';

export interface Level { price: number; label: string; kind: 'entry' | 'stop' | 'target' }

/** Candles with optional entry / stop / target lines and a touch read-out. */
export function CandleChart({ bars, height = 260, levels = [], formatTime }: {
  bars: ChartBar[]; height?: number; levels?: Level[]; formatTime: (t: number) => string;
}) {
  const t = useTheme();
  const [width, setWidth] = useState(0);
  const [pick, setPick] = useState<number | null>(null);
  const shown = useMemo(() => bars.slice(-90), [bars]);
  const frame: Frame = { width, height, left: 4, right: 50, top: 10, bottom: 8 };
  const range = useMemo(
    () => extent(shown.flatMap((b) => [b[2], b[3]]), levels.map((l) => l.price), 0.06),
    [shown, levels],
  );
  const slot = shown.length ? (width - frame.left - frame.right) / shown.length : 0;
  const slotRef = useRef({ slot, left: frame.left, n: shown.length });
  slotRef.current = { slot, left: frame.left, n: shown.length };
  const at = (x: number) => {
    const s = slotRef.current;
    if (!s.slot) return 0;
    return Math.max(0, Math.min(s.n - 1, Math.floor((x - s.left) / s.slot)));
  };
  const responder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: (_e, g) => Math.abs(g.dx) > Math.abs(g.dy),
      onPanResponderGrant: (e) => setPick(at(e.nativeEvent.locationX)),
      onPanResponderMove: (e) => setPick(at(e.nativeEvent.locationX)),
      onPanResponderRelease: () => setPick(null),
      onPanResponderTerminate: () => setPick(null),
    }),
  ).current;

  if (shown.length < 2) return <View style={{ height, justifyContent: 'center' }}><Txt dim>No price history for this range</Txt></View>;
  const bar = shown[pick != null && pick < shown.length ? pick : shown.length - 1];
  const levelInk = (k: Level['kind']) => (k === 'stop' ? t.down : k === 'target' ? t.up : t.accent);

  return (
    <View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', minHeight: 18 }}>
        <Txt v="small" num dim>{formatTime(bar[0])}</Txt>
        <Txt v="small" num dim>O {price(bar[1])}  H {price(bar[2])}  L {price(bar[3])}  C {price(bar[4])}</Txt>
      </View>
      <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} {...responder.panHandlers}
        accessibilityLabel={`Price chart, last close ${price(shown[shown.length - 1][4])}`}>
        {width > 0 && (
          <Svg width={width} height={height}>
            {ticks(range, 4).map((v) => (
              <Line key={`g${v}`} x1={frame.left} x2={width - frame.right} y1={yAt(v, range, frame)} y2={yAt(v, range, frame)} stroke={t.line} strokeWidth={1} />
            ))}
            {ticks(range, 4).map((v) => (
              <SvgText key={`t${v}`} x={width - frame.right + 6} y={yAt(v, range, frame) + 4} fontSize={10} fill={t.text3}>{tickLabel(v)}</SvgText>
            ))}
            {shown.map((b, i) => {
              const rising = b[4] >= b[1];
              const ink = rising ? t.upFill : t.downFill;
              const cx = frame.left + slot * (i + 0.5);
              const top = yAt(Math.max(b[1], b[4]), range, frame);
              const bottom = yAt(Math.min(b[1], b[4]), range, frame);
              const bodyWidth = Math.max(1, Math.min(10, slot - 2));
              return (
                <G key={`c${b[0]}`}>
                  <Line x1={cx} x2={cx} y1={yAt(b[2], range, frame)} y2={yAt(b[3], range, frame)} stroke={ink} strokeWidth={1} />
                  <Rect x={cx - bodyWidth / 2} y={top} width={bodyWidth} height={Math.max(1, bottom - top)} fill={ink} />
                </G>
              );
            })}
            {levels.map((l) => (
              <Line key={`l${l.kind}${l.price}`} x1={frame.left} x2={width - frame.right} y1={yAt(l.price, range, frame)} y2={yAt(l.price, range, frame)}
                stroke={levelInk(l.kind)} strokeWidth={1} strokeDasharray="5 4" />
            ))}
            {pick != null && (
              <Line x1={frame.left + slot * (pick + 0.5)} x2={frame.left + slot * (pick + 0.5)} y1={frame.top} y2={height - frame.bottom} stroke={t.text3} strokeWidth={1} />
            )}
          </Svg>
        )}
      </View>
      {levels.length > 0 && (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 4 }}>
          {levels.map((l) => (
            <Txt key={`k${l.kind}${l.price}`} v="small" color={levelInk(l.kind)}>┄ {l.label} {price(l.price)}</Txt>
          ))}
        </View>
      )}
    </View>
  );
}
