import { type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  type StyleProp,
  type TextProps,
  type TextStyle,
  View,
  type ViewStyle,
} from 'react-native';

import { radius, space, toneColor, useTheme } from '../theme';

type Variant = 'hero' | 'title' | 'head' | 'body' | 'small' | 'label';
const TYPE: Record<Variant, TextStyle> = {
  hero: { fontSize: 30, fontWeight: '700', letterSpacing: -0.5 },
  title: { fontSize: 20, fontWeight: '700' },
  head: { fontSize: 16, fontWeight: '600' },
  body: { fontSize: 14, lineHeight: 20 },
  small: { fontSize: 12, lineHeight: 16 },
  label: { fontSize: 11, fontWeight: '600', letterSpacing: 0.6, textTransform: 'uppercase' },
};

export function Txt({ v = 'body', dim, faint, color, num, style, ...rest }: TextProps & {
  v?: Variant; dim?: boolean; faint?: boolean; color?: string; num?: boolean;
}) {
  const t = useTheme();
  return (
    <Text
      {...rest}
      style={[TYPE[v], { color: color ?? (faint ? t.text3 : dim ? t.text2 : t.text) },
        num && { fontVariant: ['tabular-nums'] }, style]}
    />
  );
}

/** A signed amount in gain / loss ink. */
export function Delta({ value, text, v = 'body', style }: { value: number | null | undefined; text: string; v?: Variant; style?: StyleProp<TextStyle> }) {
  const t = useTheme();
  const sign = value == null || !Number.isFinite(value) || Math.abs(value) < 0.005 ? 0 : value > 0 ? 1 : -1;
  return <Txt v={v} num color={toneColor(t, sign)} style={style}>{text}</Txt>;
}

export function Screen({ children, onRefresh, refreshing, padded = true }: {
  children: ReactNode; onRefresh?: () => void; refreshing?: boolean; padded?: boolean;
}) {
  const t = useTheme();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: t.bg }}
      contentContainerStyle={[{ paddingBottom: space.xl * 2 }, padded && { padding: space.lg, gap: space.lg }]}
      keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh
        ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={t.text3} colors={[t.accent]} progressBackgroundColor={t.surface} />
        : undefined}>
      {children}
    </ScrollView>
  );
}

export function Card({ children, style, onPress }: { children: ReactNode; style?: StyleProp<ViewStyle>; onPress?: () => void }) {
  const t = useTheme();
  const base: ViewStyle = { backgroundColor: t.surface, borderRadius: radius.md, padding: space.lg, gap: space.sm };
  if (!onPress) return <View style={[base, style]}>{children}</View>;
  return (
    <Pressable onPress={onPress} android_ripple={{ color: t.surface3 }}
      style={({ pressed }) => [base, pressed && { opacity: 0.85 }, style]}>
      {children}
    </Pressable>
  );
}

export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <View style={{ gap: space.sm }}>
      <View style={styles.rowBetween}>
        <Txt v="label" faint>{title}</Txt>
        {right}
      </View>
      {children}
    </View>
  );
}

/** One line: what it is on the left, its value on the right. */
export function Row({ left, sub, right, rightSub, onPress, last }: {
  left: ReactNode; sub?: ReactNode; right?: ReactNode; rightSub?: ReactNode; onPress?: () => void; last?: boolean;
}) {
  const t = useTheme();
  const body = (
    <View style={[styles.rowBetween, { paddingVertical: space.md, borderBottomWidth: last ? 0 : StyleSheet.hairlineWidth, borderBottomColor: t.line, gap: space.md }]}>
      <View style={{ flex: 1, gap: 2 }}>
        {typeof left === 'string' ? <Txt v="head">{left}</Txt> : left}
        {typeof sub === 'string' ? <Txt v="small" dim numberOfLines={2}>{sub}</Txt> : sub}
      </View>
      {(right != null || rightSub != null) && (
        <View style={{ alignItems: 'flex-end', gap: 2 }}>
          {typeof right === 'string' ? <Txt num>{right}</Txt> : right}
          {typeof rightSub === 'string' ? <Txt v="small" dim num>{rightSub}</Txt> : rightSub}
        </View>
      )}
    </View>
  );
  if (!onPress) return body;
  return <Pressable onPress={onPress} android_ripple={{ color: t.surface3 }}>{body}</Pressable>;
}

export type PillKind = 'ok' | 'bad' | 'warn' | 'dim' | 'accent';
export function Pill({ text, kind = 'dim' }: { text: string; kind?: PillKind }) {
  const t = useTheme();
  const ink = kind === 'ok' ? t.up : kind === 'bad' ? t.down : kind === 'warn' ? t.warn : kind === 'accent' ? t.accent : t.text2;
  return (
    <View style={{ borderRadius: 999, borderWidth: 1, borderColor: ink, paddingHorizontal: 8, paddingVertical: 2, alignSelf: 'flex-start' }}>
      <Txt v="small" color={ink} style={{ fontWeight: '600' }}>{text}</Txt>
    </View>
  );
}

export function Button({ label, onPress, kind = 'primary', busy, disabled, small, style }: {
  label: string; onPress: () => void; kind?: 'primary' | 'plain' | 'danger' | 'good'; busy?: boolean; disabled?: boolean;
  small?: boolean; style?: StyleProp<ViewStyle>;
}) {
  const t = useTheme();
  const bg = kind === 'primary' ? t.accent : kind === 'danger' ? t.downFill : kind === 'good' ? t.upFill : t.surface2;
  const ink = kind === 'plain' ? t.text : '#ffffff';
  const off = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={off}
      onPress={onPress}
      android_ripple={{ color: 'rgba(255,255,255,0.15)' }}
      style={({ pressed }) => [
        { backgroundColor: bg, borderRadius: radius.sm, minHeight: small ? 36 : 46, paddingHorizontal: small ? space.md : space.lg,
          alignItems: 'center', justifyContent: 'center', opacity: off ? 0.5 : pressed ? 0.85 : 1 },
        style,
      ]}>
      {busy ? <ActivityIndicator color={ink} /> : <Txt v={small ? 'small' : 'body'} color={ink} style={{ fontWeight: '600' }}>{label}</Txt>}
    </Pressable>
  );
}

/** Underline tabs — the web app's convention for switching views in place. */
export function Tabs<T extends string>({ value, options, onChange }: {
  value: T; options: { key: T; label: string; badge?: number }[]; onChange: (k: T) => void;
}) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: 'row', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.line }}>
      {options.map((o) => {
        const on = o.key === value;
        return (
          <Pressable key={o.key} onPress={() => onChange(o.key)} accessibilityRole="tab" accessibilityState={{ selected: on }}
            style={{ paddingVertical: space.md, marginRight: space.xl, borderBottomWidth: 2, borderBottomColor: on ? t.accent : 'transparent', flexDirection: 'row', gap: 6, alignItems: 'center' }}>
            <Txt color={on ? t.text : t.text3} style={{ fontWeight: on ? '700' : '500' }}>{o.label}</Txt>
            {!!o.badge && (
              <View style={{ backgroundColor: t.accent, borderRadius: 999, minWidth: 18, paddingHorizontal: 5, alignItems: 'center' }}>
                <Txt v="small" color={t.onAccent} style={{ fontWeight: '700' }}>{o.badge}</Txt>
              </View>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

/** Small choice chips (chart ranges, book picker). */
export function Chips<T extends string>({ value, options, onChange }: {
  value: T; options: { key: T; label: string }[]; onChange: (k: T) => void;
}) {
  const t = useTheme();
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
      {options.map((o) => {
        const on = o.key === value;
        return (
          <Pressable key={o.key} onPress={() => onChange(o.key)} accessibilityRole="button" accessibilityState={{ selected: on }}
            style={{ paddingHorizontal: space.md, paddingVertical: 7, borderRadius: 999, backgroundColor: on ? t.surface3 : 'transparent', borderWidth: 1, borderColor: on ? t.surface3 : t.line }}>
            <Txt v="small" color={on ? t.text : t.text2} style={{ fontWeight: on ? '700' : '500' }}>{o.label}</Txt>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

export function Empty({ text }: { text: string }) {
  return <Txt dim style={{ paddingVertical: space.md }}>{text}</Txt>;
}

export function Loading() {
  const t = useTheme();
  return <View style={{ paddingVertical: space.xl, alignItems: 'center' }}><ActivityIndicator color={t.text3} /></View>;
}

/** What failed and what to do, in the place the data would have been. */
export function Problem({ error, onRetry }: { error: string; onRetry?: () => void }) {
  const t = useTheme();
  return (
    <View style={{ gap: space.sm, paddingVertical: space.sm }}>
      <Txt color={t.down}>{error}</Txt>
      {onRetry && <Button small kind="plain" label="Try again" onPress={onRetry} style={{ alignSelf: 'flex-start' }} />}
    </View>
  );
}

/** Loading / failed / empty / data — every list on every screen goes through this. */
export function Async<T>({ state, empty, children }: {
  state: { data: T | null; error: string | null; loading: boolean; refresh: () => void };
  empty?: string; children: (data: T) => ReactNode;
}) {
  if (state.data == null) {
    if (state.error) return <Problem error={state.error} onRetry={state.refresh} />;
    return <Loading />;
  }
  if (empty && Array.isArray(state.data) && state.data.length === 0) return <Empty text={empty} />;
  return <>{children(state.data)}</>;
}

export const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  row: { flexDirection: 'row', alignItems: 'center' },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' },
});
