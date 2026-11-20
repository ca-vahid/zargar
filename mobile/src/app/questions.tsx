import { ApiError } from '@/api/client';
import { api, type DeskQuestion } from '@/api/endpoints';
import { EmptyArt } from '@/components/graphics';
import { QuestionCard } from '@/components/Questions';
import { Async, Card, Pill, Row, Screen, Section, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { dayTime } from '@/lib/format';

const load = () => api.questions().catch((e) => { if (e instanceof ApiError && e.status === 404) return [] as DeskQuestion[]; throw e; });

/** What Claude has asked: the open ones to answer, then the record of what was answered. */
export default function QuestionsScreen() {
  const list = usePoll(load, 15000, [], 'questions');
  return (
    <Screen attention={false} onRefresh={list.refresh} refreshing={list.refreshing}>
      <Async state={list}>
        {(all: DeskQuestion[]) => {
          const open = all.filter((q) => q.status === 'open');
          const past = all.filter((q) => q.status !== 'open');
          return (
            <>
              {open.length === 0 && <EmptyArt text="Nothing is waiting for your answer. When Claude needs a decision from you it appears here and on Home." />}
              {open.map((q) => <QuestionCard key={q.id} q={q} onAnswered={list.refresh} />)}
              {past.length > 0 && (
                <Section title="Earlier">
                  <Card>
                    {past.map((q, i) => (
                      <Row key={q.id} last={i === past.length - 1}
                        left={<Txt>{q.text}</Txt>}
                        sub={<Txt v="small" dim>{q.status === 'answered' ? `You answered: ${q.answer}` : q.status === 'expired' ? 'Not answered in time' : 'Withdrawn'}</Txt>}
                        right={<Pill kind={q.status === 'answered' ? 'ok' : 'dim'} text={q.status === 'answered' ? 'Answered' : q.status === 'expired' ? 'Expired' : 'Withdrawn'} />}
                        rightSub={dayTime(q.answeredAt ?? q.createdAt)} />
                    ))}
                  </Card>
                </Section>
              )}
            </>
          );
        }}
      </Async>
    </Screen>
  );
}
