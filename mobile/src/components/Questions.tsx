import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { api, type DeskQuestion } from '../api/endpoints';
import { runAction } from '../lib/actions';
import { ago } from '../lib/format';
import { refreshAttention } from '../live/attention';
import { radius, space, useTheme } from '../theme';
import { Button, Card, Txt } from './ui';

/** One question from Claude with its answers. The first answer stands, so every tap is
 *  confirmed; an answer is words for Claude to act on, never an order by itself. */
export function QuestionCard({ q, onAnswered }: { q: DeskQuestion; onAnswered?: () => void }) {
  const t = useTheme();
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState(q.options.length === 0);
  const [text, setText] = useState('');

  const send = async (answer: string) => {
    setBusy(true);
    const ok = await runAction(
      { title: `Answer "${answer.length > 60 ? `${answer.slice(0, 57)}…` : answer}"?`, body: q.text, confirmLabel: 'Send answer' },
      () => api.answerQuestion(q.id, answer), 'Answer sent');
    setBusy(false);
    if (ok) { void refreshAttention().catch(() => {}); onAnswered?.(); }
  };

  return (
    <Card style={{ borderColor: t.accent, borderWidth: 1.5, gap: space.md }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <View style={{ width: 30, height: 30, borderRadius: 15, backgroundColor: t.accent, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="help" size={18} color={t.onAccent} />
        </View>
        <Txt v="label" color={t.accent} style={{ flex: 1 }}>{q.askedBy === 'claude' ? 'Claude asks' : `${q.askedBy} asks`}</Txt>
        <Txt v="small" faint>{ago(q.createdAt)}</Txt>
      </View>
      <Txt v="head" style={{ lineHeight: 22 }}>{q.text}</Txt>
      {!!q.detail && <Txt v="small" dim>{q.detail}</Txt>}
      {q.options.length > 0 && (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          {q.options.map((o, i) => (
            <Button key={o} label={o} kind={i === 0 ? 'primary' : 'plain'} disabled={busy} onPress={() => void send(o)}
              style={{ flexGrow: 1, flexBasis: q.options.length > 2 ? '45%' : 0 }} />
          ))}
        </View>
      )}
      {typing ? (
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          <TextInput value={text} onChangeText={setText} placeholder="Type your answer" placeholderTextColor={t.text3} multiline accessibilityLabel="Your answer"
            style={{ flex: 1, backgroundColor: t.surface2, color: t.text, borderRadius: radius.sm, paddingHorizontal: space.md, paddingVertical: 10, fontSize: 15, minHeight: 46 }} />
          <Button label="Send" disabled={busy || !text.trim()} onPress={() => void send(text.trim())} />
        </View>
      ) : (
        <Txt v="small" color={t.accent} onPress={() => setTyping(true)}>Answer in your own words</Txt>
      )}
      {!!q.expiresAt && <Txt v="small" faint>Claude waits for this until {new Date(q.expiresAt).toLocaleString()}.</Txt>}
    </Card>
  );
}
