import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { type ReactNode, useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';
import Svg, { Circle, Defs, Line, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

import { extent, linePath } from '../lib/chart';
import { radius, space, useTheme } from '../theme';
import { Txt } from './ui';

type IconName = keyof typeof Ionicons.glyphMap;

// eight hues that read on both themes; a ticker always gets the same one
const HUES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#7b6fe0', '#2aa7b8', '#b86b2a'];
function hueFor(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return HUES[h % HUES.length];
}

/** A round monogram for a ticker: the same colour every time it appears. */
export function SymbolBadge({ symbol, size = 38 }: { symbol: string; size?: number }) {
  const clean = (symbol || '?').replace(/[^A-Za-z]/g, '').toUpperCase() || '?';
  const ink = hueFor(clean);
  const letters = clean.length <= 4 ? clean : clean.slice(0, 3);
  return (
    <View
      style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: `${ink}26`, borderWidth: 1, borderColor: `${ink}66`, alignItems: 'center', justifyContent: 'center' }}>
      <Txt color={ink} style={{ fontWeight: '800', fontSize: letters.length > 3 ? size * 0.26 : letters.length > 2 ? size * 0.3 : size * 0.36, letterSpacing: -0.3 }}>{letters}</Txt>
    </View>
  );
}

/** A small trend line with no axes: direction at a glance, coloured by the day. */
export function Sparkline({ values, width = 76, height = 30, up }: { values: number[]; width?: number; height?: number; up?: boolean }) {
  const t = useTheme();
  if (values.length < 2) return <View style={{ width, height }} />;
  const rising = up ?? values[values.length - 1] >= values[0];
  const ink = rising ? t.up : t.down;
  const frame = { width, height, left: 2, right: 2, top: 3, bottom: 3 };
  return (
    <Svg width={width} height={height}>
      <Path d={linePath(values, extent(values, [], 0.05), frame)} stroke={ink} strokeWidth={1.75} fill="none" strokeLinejoin="round" strokeLinecap="round" />
    </Svg>
  );
}

/** Where the price sits between the stop and the target: red end, green end, a
 *  tick for the entry and a dot for now. Says "how close to either" without numbers. */
export function RangeBar({ stop, entry, now, target }: { stop: number | null; entry: number | null; now: number | null; target: number | null }) {
  const t = useTheme();
  const [width, setWidth] = useState(0);
  if (stop == null || now == null || (target == null && entry == null)) return null;
  const far = target ?? (entry as number) + ((entry as number) - stop);
  const lo = Math.min(stop, far, now);
  const hi = Math.max(stop, far, now);
  if (!(hi > lo)) return null;
  const x = (v: number) => 6 + ((v - lo) / (hi - lo)) * (width - 12);
  const gain = entry != null ? (far >= stop ? now >= entry : now <= entry) : true;
  return (
    <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} style={{ height: 14, justifyContent: 'center' }}
      accessibilityLabel={`Between stop ${stop} and target ${far}, now ${now}`}>
      {width > 0 && (
        <Svg width={width} height={14}>
          <Defs>
            <LinearGradient id="rng" x1="0" y1="0" x2="1" y2="0">
              <Stop offset="0" stopColor={far >= stop ? t.downFill : t.upFill} stopOpacity={0.9} />
              <Stop offset="0.5" stopColor={t.surface3} stopOpacity={1} />
              <Stop offset="1" stopColor={far >= stop ? t.upFill : t.downFill} stopOpacity={0.9} />
            </LinearGradient>
          </Defs>
          <Rect x={6} y={5} width={width - 12} height={4} rx={2} fill="url(#rng)" />
          {entry != null && <Line x1={x(entry)} x2={x(entry)} y1={2} y2={12} stroke={t.text3} strokeWidth={1.5} />}
          <Circle cx={x(now)} cy={7} r={5} fill={gain ? t.up : t.down} stroke={t.surface} strokeWidth={2} />
        </Svg>
      )}
    </View>
  );
}

/** A filled meter from 0 to 1 (confidence, loss limit used). */
export function Meter({ value, color, height = 5 }: { value: number; color?: string; height?: number }) {
  const t = useTheme();
  const v = Math.max(0, Math.min(1, value));
  return (
    <View style={{ height, borderRadius: height / 2, backgroundColor: t.surface3, overflow: 'hidden' }}>
      <View style={{ width: `${v * 100}%`, height, borderRadius: height / 2, backgroundColor: color ?? t.accent }} />
    </View>
  );
}

/** One number with its name and an icon; four of these make the home screen's strip. */
export function StatTile({ icon, label, value, tone, onPress }: {
  icon: IconName; label: string; value: string; tone?: 'ok' | 'bad' | 'warn' | 'accent'; onPress?: () => void;
}) {
  const t = useTheme();
  const ink = tone === 'ok' ? t.up : tone === 'bad' ? t.down : tone === 'warn' ? t.warn : tone === 'accent' ? t.accent : t.text2;
  return (
    <Pressable onPress={onPress} disabled={!onPress} accessibilityRole={onPress ? 'button' : undefined} accessibilityLabel={`${label}: ${value}`}
      android_ripple={{ color: t.surface3 }}
      style={{ flex: 1, minWidth: '45%', backgroundColor: t.surface, borderRadius: radius.md, borderWidth: 1, borderColor: t.line, padding: space.md, gap: 6 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <View style={{ width: 30, height: 30, borderRadius: 15, backgroundColor: `${ink}22`, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={icon} size={16} color={ink} />
        </View>
        <Txt v="title" num color={tone ? ink : t.text}>{value}</Txt>
      </View>
      <Txt v="small" dim>{label}</Txt>
    </Pressable>
  );
}

/** The headline card: a warm gold wash with the mark behind the numbers. */
export function Hero({ children }: { children: ReactNode }) {
  const t = useTheme();
  const [size, setSize] = useState({ w: 0, h: 0 });
  const stops = useMemo(() => (t.dark
    ? [['0', '#3a2a08', 1], ['0.55', '#1f1a12', 1], ['1', '#1a1a19', 1]]
    : [['0', '#fbe6ae', 1], ['0.6', '#fdf6e3', 1], ['1', '#fdfdfc', 1]]) as [string, string, number][], [t.dark]);
  return (
    <View onLayout={(e) => setSize({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })}
      style={{ borderRadius: radius.lg, overflow: 'hidden', borderWidth: 1, borderColor: t.dark ? '#4a3a12' : '#ecd9a0' }}>
      {size.w > 0 && (
        <Svg width={size.w} height={size.h} style={{ position: 'absolute' }}>
          <Defs>
            <LinearGradient id="hero" x1="0" y1="0" x2="1" y2="1">
              {stops.map(([o, c, a]) => <Stop key={o} offset={o} stopColor={c} stopOpacity={a} />)}
            </LinearGradient>
          </Defs>
          <Rect x={0} y={0} width={size.w} height={size.h} fill="url(#hero)" />
        </Svg>
      )}
      <Image source={require('../../assets/images/splash-icon.png')} contentFit="contain"
        style={{ position: 'absolute', right: -18, bottom: -22, width: 150, height: 150, opacity: t.dark ? 0.22 : 0.35 }} />
      <View style={{ padding: space.lg, gap: space.xs }}>{children}</View>
    </View>
  );
}

/** A friendly empty state: the desk's medallion and one line of what will appear. */
export function EmptyArt({ text }: { text: string }) {
  return (
    <View style={{ alignItems: 'center', gap: space.md, paddingVertical: space.xl }}>
      <Image source={require('../../assets/images/empty.png')} style={{ width: 132, height: 132, opacity: 0.9 }} contentFit="contain" />
      <Txt dim style={{ textAlign: 'center', maxWidth: 280 }}>{text}</Txt>
    </View>
  );
}

/** Section heading with a small icon. */
export function Heading({ icon, title, right }: { icon: IconName; title: string; right?: ReactNode }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Ionicons name={icon} size={15} color={t.accent} />
        <Txt v="label" dim>{title}</Txt>
      </View>
      {right}
    </View>
  );
}
