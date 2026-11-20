import Ionicons from '@expo/vector-icons/Ionicons';
import { useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api } from '../api/endpoints';
import type { Portfolio } from '../api/types';
import { useConvert } from '../hooks/useCurrency';
import { usePoll } from '../hooks/usePoll';
import { type BookGroup, dayMove, dayMovePct, GROUP_LABEL, groupOf } from '../lib/books';
import { money, pct, signedMoney } from '../lib/format';
import { radius, space, useTheme } from '../theme';
import { Sparkline } from './graphics';
import { Delta, Txt } from './ui';

type IconName = keyof typeof Ionicons.glyphMap;
const GROUP_ICON: Record<BookGroup, IconName> = {
  real: 'business-outline', paper: 'document-text-outline', practice: 'flask-outline', research: 'telescope-outline',
};

function GroupIcon({ group, size = 40 }: { group: BookGroup; size?: number }) {
  const t = useTheme();
  const ink = group === 'real' ? t.accent : group === 'paper' ? t.series : group === 'practice' ? t.series3 : t.text3;
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: `${ink}22`, borderWidth: 1, borderColor: `${ink}55`, alignItems: 'center', justifyContent: 'center' }}>
      <Ionicons name={GROUP_ICON[group]} size={size * 0.48} color={ink} />
    </View>
  );
}

/** One account in the list: what it is, what it is worth, how today is going. */
function AccountRow({ book, selected, onPress }: { book: Portfolio; selected: boolean; onPress: () => void }) {
  const t = useTheme();
  const conv = useConvert();
  const curve = usePoll(() => api.equity(book.id, { since: Date.now() - 24 * 3600e3, points: 40 }), 0, [book.id]);
  const values = useMemo(() => {
    const v = (curve.data ?? []).map((p) => p[1]);
    return book.equity != null ? [...v, book.equity] : v;
  }, [curve.data, book.equity]);
  const eq = conv(book.equity ?? book.cash, book.baseCurrency);
  const move = conv(dayMove(book), book.baseCurrency).value;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected }}
      accessibilityLabel={`${book.name}, ${money(eq.value, eq.cur)}`} android_ripple={{ color: t.surface3 }}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.md,
        borderWidth: 1.5, borderColor: selected ? t.accent : t.line, backgroundColor: selected ? `${t.accent}14` : t.surface2 }}>
      <GroupIcon group={groupOf(book)} />
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="head" numberOfLines={2}>{book.name}</Txt>
        <Txt v="small" dim num>{money(eq.value, eq.cur)}</Txt>
      </View>
      <Sparkline values={values} width={58} height={26} up={move == null ? undefined : move >= 0} />
      <View style={{ alignItems: 'flex-end', minWidth: 74 }}>
        <Delta v="small" value={move} text={signedMoney(move, eq.cur, 0)} />
        <Delta v="small" value={move} text={pct(dayMovePct(book))} />
      </View>
      {selected && <Ionicons name="checkmark-circle" size={20} color={t.accent} />}
    </Pressable>
  );
}

/** The account on screen, as one large control: tap it to see every account side by
 *  side with its value and today's move, or use the arrows to step to the next one. */
export function AccountPicker({ books, selected, onSelect, footer }: {
  books: Portfolio[]; selected: Portfolio; onSelect: (id: string) => void; footer?: React.ReactNode;
}) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const index = Math.max(0, books.findIndex((b) => b.id === selected.id));
  const step = (by: number) => onSelect(books[(index + by + books.length) % books.length].id);
  const groups = useMemo(() => {
    const out = new Map<BookGroup, Portfolio[]>();
    for (const b of books) out.set(groupOf(b), [...(out.get(groupOf(b)) ?? []), b]);
    return [...out.entries()];
  }, [books]);

  const arrow = (dir: -1 | 1) => (
    <Pressable onPress={() => step(dir)} disabled={books.length < 2} hitSlop={8} accessibilityRole="button"
      accessibilityLabel={dir < 0 ? 'Previous account' : 'Next account'}
      style={{ width: 40, alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center', opacity: books.length < 2 ? 0.25 : 1 }}>
      <Ionicons name={dir < 0 ? 'chevron-back' : 'chevron-forward'} size={22} color={t.text2} />
    </Pressable>
  );

  return (
    <>
      <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: t.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: t.line, overflow: 'hidden' }}>
        {arrow(-1)}
        <Pressable onPress={() => setOpen(true)} accessibilityRole="button" accessibilityLabel={`Account: ${selected.name}. Tap to choose another.`}
          android_ripple={{ color: t.surface3 }}
          style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.md }}>
          <GroupIcon group={groupOf(selected)} size={38} />
          <View style={{ flex: 1 }}>
            <Txt v="head" numberOfLines={1}>{selected.name}</Txt>
            <Txt v="small" dim>{GROUP_LABEL[groupOf(selected)]} · {index + 1} of {books.length}</Txt>
          </View>
          <Ionicons name="chevron-down" size={18} color={t.text3} />
        </Pressable>
        {arrow(1)}
      </View>
      {books.length > 1 && (
        <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 6 }} accessibilityElementsHidden>
          {books.map((b, i) => (
            <View key={b.id} style={{ width: i === index ? 18 : 6, height: 6, borderRadius: 3, backgroundColor: i === index ? t.accent : t.surface3 }} />
          ))}
        </View>
      )}

      <Modal transparent animationType="slide" visible={open} onRequestClose={() => setOpen(false)} statusBarTranslucent>
        <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' }} onPress={() => setOpen(false)} accessibilityLabel="Close" />
        <View style={{ maxHeight: '78%', backgroundColor: t.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, paddingTop: space.md, paddingBottom: insets.bottom + space.lg }}>
          <View style={{ alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: t.surface3, marginBottom: space.md }} />
          <Txt v="title" style={{ paddingHorizontal: space.lg, marginBottom: space.sm }}>Choose an account</Txt>
          <ScrollView contentContainerStyle={{ paddingHorizontal: space.lg, gap: space.sm, paddingBottom: space.md }}>
            {groups.map(([group, list]) => (
              <View key={group} style={{ gap: space.sm }}>
                <Txt v="label" faint style={{ marginTop: space.sm }}>{GROUP_LABEL[group]}</Txt>
                {list.map((b) => (
                  <AccountRow key={b.id} book={b} selected={b.id === selected.id} onPress={() => { onSelect(b.id); setOpen(false); }} />
                ))}
              </View>
            ))}
            {footer}
          </ScrollView>
        </View>
      </Modal>
    </>
  );
}
