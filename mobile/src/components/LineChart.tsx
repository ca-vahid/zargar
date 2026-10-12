import { useMemo, useRef, useState } from 'react';
import { PanResponder, View } from 'react-native';
import Svg, { Defs, Line, LinearGradient, Path, Stop, Circle, Text as SvgText } from 'react-native-svg';

import { areaPath, decimate, extent, type Frame, indexAt, linePath, type Point, tickLabel, ticks, xAt, yAt } from '../lib/chart';
import { useTheme } from '../theme';
import { Txt } from './ui';

export interface Overlay { values: (number | null)[]; color: string; label: string }

/** A line with a soft fill, a dashed reference level and a touch crosshair.
 *
 *  `points` is [time, value]; x is evenly spaced so closed hours take no room.
 *  Touch and drag to read any point: the header shows its value and time through
 *  `format` / `formatTime`, so the chart never needs a legend of its own. */
export function LineChart({ points, height = 180, color, baseline, baselineLabel, overlays, format, formatTime, emptyText = 'No data yet' }: {
  points: Point[];
  height?: number;
  color?: string;
  baseline?: number | null;
  baselineLabel?: string;
  overlays?: Overlay[];
  format: (v: number) => string;
  formatTime: (t: number) => string;
  emptyText?: string;
}) {
  const t = useTheme();
  const [width, setWidth] = useState(0);
  const [pick, setPick] = useState<number | null>(null);
  const series = useMemo(() => decimate(points, 320), [points]);
  const values = useMemo(() => series.map((p) => p[1]), [series]);
  const frame: Frame = { width, height, left: 4, right: 46, top: 10, bottom: 8 };
  const overlayValues = useMemo(() => (overlays ?? []).flatMap((o) => o.values.filter((v): v is number => v != null)), [overlays]);
  const range = useMemo(
    () => extent(values, [...(baseline != null ? [baseline] : []), ...overlayValues]),
    [values, baseline, overlayValues],
  );
  const up = values.length > 1 ? values[values.length - 1] >= (baseline ?? values[0]) : true;
  const ink = color ?? (up ? t.up : t.down);

  const frameRef = useRef(frame);
  frameRef.current = frame;
  const countRef = useRef(values.length);
  countRef.current = values.length;
  const responder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      // a mostly-vertical drag belongs to the page scroll, not the crosshair
      onMoveShouldSetPanResponder: (_e, g) => Math.abs(g.dx) > Math.abs(g.dy),
      onPanResponderGrant: (e) => setPick(indexAt(e.nativeEvent.locationX, countRef.current, frameRef.current)),
      onPanResponderMove: (e) => setPick(indexAt(e.nativeEvent.locationX, countRef.current, frameRef.current)),
      onPanResponderRelease: () => setPick(null),
      onPanResponderTerminate: () => setPick(null),
    }),
  ).current;

  if (values.length < 2) {
    return <View style={{ height, justifyContent: 'center' }}><Txt dim>{emptyText}</Txt></View>;
  }
  const shown = pick != null && pick < series.length ? pick : series.length - 1;
  const gradId = `fill-${ink.replace('#', '')}`;

  return (
    <View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', minHeight: 18 }}>
        <Txt v="small" num dim>{pick != null ? formatTime(series[shown][0]) : ' '}</Txt>
        <Txt v="small" num dim>{pick != null ? format(series[shown][1]) : ' '}</Txt>
      </View>
      <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} {...responder.panHandlers}
        accessibilityLabel={`Chart, latest ${format(values[values.length - 1])}`}>
        {width > 0 && (
          <Svg width={width} height={height}>
            <Defs>
              <LinearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={ink} stopOpacity={0.22} />
                <Stop offset="1" stopColor={ink} stopOpacity={0} />
              </LinearGradient>
            </Defs>
            {ticks(range, 3).map((v) => (
              <Line key={`g${v}`} x1={frame.left} x2={width - frame.right} y1={yAt(v, range, frame)} y2={yAt(v, range, frame)} stroke={t.line} strokeWidth={1} />
            ))}
            {ticks(range, 3).map((v) => (
              <SvgText key={`t${v}`} x={width - frame.right + 6} y={yAt(v, range, frame) + 4} fontSize={10} fill={t.text3}>{tickLabel(v)}</SvgText>
            ))}
            {baseline != null && (
              <Line x1={frame.left} x2={width - frame.right} y1={yAt(baseline, range, frame)} y2={yAt(baseline, range, frame)}
                stroke={t.text3} strokeWidth={1} strokeDasharray="4 4" />
            )}
            <Path d={areaPath(values, range, frame)} fill={`url(#${gradId})`} />
            {(overlays ?? []).map((o) => {
              // overlays are sampled on the SAME points as the main line
              const vals = decimateLike(o.values, points.length, series.length);
              let d = '';
              let pen = false;
              vals.forEach((v, i) => {
                if (v == null) { pen = false; return; }
                d += `${pen ? 'L' : 'M'}${xAt(i, vals.length, frame).toFixed(1)},${yAt(v, range, frame).toFixed(1)}`;
                pen = true;
              });
              return <Path key={o.label} d={d} stroke={o.color} strokeWidth={1.25} fill="none" />;
            })}
            <Path d={linePath(values, range, frame)} stroke={ink} strokeWidth={2} fill="none" strokeLinejoin="round" />
            {pick != null && (
              <>
                <Line x1={xAt(shown, values.length, frame)} x2={xAt(shown, values.length, frame)} y1={frame.top} y2={height - frame.bottom} stroke={t.text3} strokeWidth={1} />
                <Circle cx={xAt(shown, values.length, frame)} cy={yAt(values[shown], range, frame)} r={4.5} fill={ink} stroke={t.bg} strokeWidth={2} />
              </>
            )}
          </Svg>
        )}
      </View>
      {(baseline != null && baselineLabel) || overlays?.length ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 4 }}>
          {baseline != null && baselineLabel && <Txt v="small" faint>┄ {baselineLabel}</Txt>}
          {(overlays ?? []).map((o) => <Txt key={o.label} v="small" color={o.color}>— {o.label}</Txt>)}
        </View>
      ) : null}
    </View>
  );
}

/** Resample an overlay to the thinned main series' length (nearest sample). */
function decimateLike(values: (number | null)[], from: number, to: number): (number | null)[] {
  if (from === to || to <= 1) return values;
  const out: (number | null)[] = [];
  for (let i = 0; i < to; i++) out.push(values[Math.round((i / (to - 1)) * (from - 1))] ?? null);
  return out;
}
