import { api } from '@/api/endpoints';
import { Async, Card, Pill, type PillKind, Row, Screen, Section, Txt } from '@/components/ui';
import { usePoll } from '@/hooks/usePoll';
import { ago, money } from '@/lib/format';
import { useStore } from '@/store';

const yes = (ok: boolean | undefined | null, good: string, bad: string) => (
  <Pill kind={(ok ? 'ok' : 'bad') as PillKind} text={ok ? good : bad} />
);

export default function SystemScreen() {
  const broker = useStore((s) => s.broker);
  const conn = useStore((s) => s.conn);
  const apiUrl = useStore((s) => s.apiUrl);
  const health = usePoll(() => api.health(), 30000);
  const intake = usePoll(() => api.intakeLiveness(), 30000);

  return (
    <Screen onRefresh={() => { health.refresh(); intake.refresh(); }} refreshing={health.refreshing}>
      <Section title="Server">
        <Card>
          <Async state={health}>
            {(h) => (
              <>
                <Row left="Engine" sub={`Version ${h.version}${h.build ? ` · build ${h.build.slice(0, 8)}` : ''}`} right={yes(h.ok && h.started, 'Running', 'Not healthy')} />
                <Row left="Armed plans" right={<Txt num>{h.local?.armed ?? '—'}</Txt>} />
                <Row left="Clock" sub="Difference from network time"
                  right={<Txt num>{h.local?.clockSkewMs != null ? `${Math.round(h.local.clockSkewMs)} ms` : '—'}</Txt>} />
                <Row left="Host memory free" right={<Txt num>{h.local?.delivery?.hostFreeGb != null ? `${h.local.delivery.hostFreeGb.toFixed(1)} GB` : '—'}</Txt>} />
                <Row last left="Event loop" sub={`${h.local?.delivery?.loopStalls ?? 0} stalls since start`}
                  right={<Txt num>{h.local?.delivery?.eventLoopLagMs != null ? `${h.local.delivery.eventLoopLagMs.toFixed(1)} ms lag` : '—'}</Txt>} />
              </>
            )}
          </Async>
        </Card>
      </Section>

      <Section title="Links">
        <Card>
          <Row left="This phone" sub={apiUrl.replace(/^https?:\/\//, '')}
            right={<Pill kind={conn === 'live' ? 'ok' : conn === 'connecting' ? 'warn' : 'bad'} text={conn === 'live' ? 'Live' : conn === 'connecting' ? 'Connecting' : 'Offline'} />} />
          <Row left="Price feed" sub={broker?.quoteSource ? `Source: ${broker.quoteSource}` : undefined} right={yes(broker?.feedConnected, 'Connected', 'Down')} />
          <Row left="IBKR" sub={broker?.ibkr ? `${broker.ibkr.account ?? ''} · spendable ${money(broker.ibkr.spendable, broker.ibkr.bookCurrency)} · read ${ago(broker.ibkr.syncedAt)}` : undefined}
            right={yes(broker?.ibkrConnected, 'Connected', 'Disconnected')} />
          <Row last left="SnapTrade" right={yes(broker?.snaptradeConnected, 'Connected', 'Disconnected')} />
        </Card>
      </Section>

      <Section title="Tip intake">
        <Card>
          <Async state={intake}>
            {(l) => (
              <>
                <Row left="Discord intake" sub={l.reasons.length ? l.reasons.join(' · ') : `Watching ${l.gateway?.watched ?? 0} channels`}
                  right={<Pill kind={l.state === 'live' ? 'ok' : 'bad'} text={l.state === 'live' ? 'Live' : l.state} />} />
                <Row last left="Last message" right={<Txt dim>{ago(l.gateway?.lastMessageAt) || '—'}</Txt>} />
              </>
            )}
          </Async>
        </Card>
      </Section>
    </Screen>
  );
}
