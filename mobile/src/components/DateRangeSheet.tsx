import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { monthGrid, monthName, type Span, spanLabel, spanOfDays, startOfDay } from '../lib/range';
import { radius, space, useTheme } from '../theme';
import { Button, Txt } from './ui';

const DAY = 24 * 3600e3;
const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

/** Pick any stretch of days for the chart: a few ready-made windows, or tap a first
 *  and a last day on the calendar. Days after today cannot be chosen. */
export function DateRangeSheet({ visible, value, onApply, onClose }: {
  visible: boolean; value: Span | null; onApply: (span: Span) => void; onClose: () => void;
}) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const now = Date.now();
  const today = startOfDay(now);
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const [view, setView] = useState(() => { const d = new Date(now); return { y: d.getFullYear(), m: d.getMonth() }; });

  // open on whatever is applied now
  useEffect(() => {
    if (!visible) return;
    const from = value?.from ?? null;
    const to = value?.to ?? (from != null ? today : null);
    setA(from != null ? startOfDay(from) : null);
    setB(to != null ? startOfDay(to) : null);
    const d = new Date(to ?? now);
    setView({ y: d.getFullYear(), m: d.getMonth() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const lo = a != null && b != null ? Math.min(a, b) : a;
  const hi = a != null && b != null ? Math.max(a, b) : a;
  const tap = (ms: number) => {
    if (a == null || b != null) { setA(ms); setB(null); } else setB(ms);
  };
  const preset = (from: number, to: number = today) => { setA(startOfDay(from)); setB(startOfDay(to)); const d = new Date(to); setView({ y: d.getFullYear(), m: d.getMonth() }); };
  const d0 = new Date(now);
  const presets: { label: string; run: () => void }[] = [
    { label: 'Last 3 days', run: () => preset(today - 2 * DAY) },
    { label: 'Last 2 weeks', run: () => preset(today - 13 * DAY) },
    { label: 'This month', run: () => preset(new Date(d0.getFullYear(), d0.getMonth(), 1).getTime()) },
    { label: 'Last month', run: () => preset(new Date(d0.getFullYear(), d0.getMonth() - 1, 1).getTime(), new Date(d0.getFullYear(), d0.getMonth(), 0).getTime()) },
    { label: 'Last 6 months', run: () => preset(today - 183 * DAY) },
  ];
  const shift = (by: number) => setView((v) => { const d = new Date(v.y, v.m + by, 1); return { y: d.getFullYear(), m: d.getMonth() }; });
  const atLatestMonth = view.y === d0.getFullYear() && view.m === d0.getMonth();
  const chosen = lo != null ? spanOfDays(lo, hi ?? lo, now) : null;

  return (
    <Modal transparent animationType="slide" visible={visible} onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' }} onPress={onClose} accessibilityLabel="Close" />
      <View style={{ backgroundColor: t.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: space.lg, paddingBottom: insets.bottom + space.lg, gap: space.md }}>
        <View style={{ alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: t.surface3 }} />
        <Txt v="title">Choose dates</Txt>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          {presets.map((p) => (
            <Pressable key={p.label} onPress={p.run} accessibilityRole="button" accessibilityLabel={p.label}
              style={{ paddingHorizontal: space.md, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: t.line, backgroundColor: t.surface2 }}>
              <Txt v="small" dim style={{ fontWeight: '600' }}>{p.label}</Txt>
            </Pressable>
          ))}
        </View>

        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Pressable onPress={() => shift(-1)} hitSlop={10} accessibilityRole="button" accessibilityLabel="Previous month" style={{ padding: 6 }}>
            <Ionicons name="chevron-back" size={20} color={t.text2} />
          </Pressable>
          <Txt v="head">{monthName(view.m)} {view.y}</Txt>
          <Pressable onPress={() => shift(1)} disabled={atLatestMonth} hitSlop={10} accessibilityRole="button" accessibilityLabel="Next month" style={{ padding: 6, opacity: atLatestMonth ? 0.25 : 1 }}>
            <Ionicons name="chevron-forward" size={20} color={t.text2} />
          </Pressable>
        </View>
        <View>
          <View style={{ flexDirection: 'row' }}>
            {WEEKDAYS.map((w, i) => <Txt key={i} v="small" faint style={{ flex: 1, textAlign: 'center', paddingBottom: 4 }}>{w}</Txt>)}
          </View>
          {monthGrid(view.y, view.m).map((week, wi) => (
            <View key={wi} style={{ flexDirection: 'row' }}>
              {week.map((dayNo, di) => {
                if (dayNo == null) return <View key={di} style={{ flex: 1, height: 40 }} />;
                const ms = new Date(view.y, view.m, dayNo).getTime();
                const future = ms > today;
                const edge = ms === lo || ms === hi;
                const inside = lo != null && hi != null && ms > lo && ms < hi;
                return (
                  <Pressable key={di} disabled={future} onPress={() => tap(ms)} accessibilityRole="button"
                    accessibilityLabel={`${monthName(view.m)} ${dayNo}`} accessibilityState={{ selected: edge || inside, disabled: future }}
                    style={{ flex: 1, height: 40, alignItems: 'center', justifyContent: 'center', backgroundColor: inside ? `${t.accent}22` : 'transparent' }}>
                    <View style={{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: edge ? t.accent : 'transparent',
                      borderWidth: ms === today && !edge ? 1 : 0, borderColor: t.text3 }}>
                      <Txt num color={edge ? t.onAccent : future ? t.text3 : t.text} style={{ fontWeight: edge ? '800' : '500', opacity: future ? 0.4 : 1 }}>{dayNo}</Txt>
                    </View>
                  </Pressable>
                );
              })}
            </View>
          ))}
        </View>

        <Txt dim style={{ textAlign: 'center' }}>
          {chosen ? `${spanLabel(chosen, now)}${b == null ? ' — tap the last day' : ''}` : 'Tap the first day, then the last day'}
        </Txt>
        <Button label="Show these dates" disabled={!chosen} onPress={() => { if (chosen) { onApply(chosen); onClose(); } }} />
      </View>
    </Modal>
  );
}
