import * as Haptics from 'expo-haptics';
import { AppState, Platform } from 'react-native';

import { ApiError } from '../api/client';
import { api, type DeskQuestion } from '../api/endpoints';
import { type Workspace, workspaceOf } from '../lib/books';
import { newYorkDate } from '../lib/market';
import { type StandingOrder, withStale } from '../lib/standing';
import { type Attention, useStore } from '../store';

// One watcher for the whole app: what waits for the person, on either workspace, whatever
// screen is open. It polls (questions and standing orders have no live topic) while the app
// is in the foreground, and says so once - a buzz and a line - when something new arrives.

const EVERY_MS = 20000;
let timer: ReturnType<typeof setInterval> | null = null;
let sub: { remove: () => void } | null = null;
let known = new Set<string>();
let first = true;

/** The pure half: what needs the person, from the server's two lists. */
export function attentionOf(
  questions: DeskQuestion[], orders: StandingOrder[], kindOf: (portfolioId: string) => string | undefined, today: string | null,
): Attention {
  const out: Attention = { questions: questions.filter((q) => q.status === 'open'), drafts: { live: 0, practice: 0 }, failed: { live: 0, practice: 0 } };
  for (const o of withStale(orders, today)) {
    const ws: Workspace = workspaceOf(kindOf(o.portfolioId));
    if (o.status === 'draft') out.drafts[ws] += 1;
    else if (o.status === 'failed') out.failed[ws] += 1;
  }
  return out;
}

/** One key per thing that can be new: a question, a plan to arm, a failed order. */
export function attentionKeys(questions: DeskQuestion[], orders: StandingOrder[], today: string | null): string[] {
  const keys = questions.filter((q) => q.status === 'open').map((q) => `q:${q.id}`);
  for (const o of withStale(orders, today)) {
    if (o.status === 'draft') keys.push(`draft:${o.planId ?? o.id}`);
    else if (o.status === 'failed') keys.push(`failed:${o.id}`);
  }
  return [...new Set(keys)];
}

function announce(fresh: string[], a: Attention) {
  const q = fresh.filter((k) => k.startsWith('q:')).length;
  const drafts = fresh.filter((k) => k.startsWith('draft:')).length;
  const failed = fresh.filter((k) => k.startsWith('failed:')).length;
  const text = q ? (q === 1 ? `Claude asks: ${a.questions[0]?.text ?? 'a question for you'}` : `${q} questions are waiting for your answer`)
    : failed ? `${failed} standing order${failed > 1 ? 's' : ''} failed` : `${drafts} plan${drafts > 1 ? 's are' : ' is'} waiting for your arm`;
  useStore.getState().toast(failed && !q ? 'error' : 'info', text);
  if (Platform.OS !== 'web') void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
}

export async function refreshAttention(): Promise<void> {
  const st = useStore.getState();
  if (!st.user) return;
  // an older server has no questions route: that is "no questions", not an error
  const questions = await api.questions(true).catch((e) => { if (e instanceof ApiError && e.status === 404) return [] as DeskQuestion[]; throw e; });
  const standing = await api.standing();
  const today = newYorkDate(Date.now());
  const books = useStore.getState().portfolios;
  if (!books.length) return; // the snapshot has not arrived: an order's workspace is not known yet
  const next = attentionOf(questions, standing.orders, (pid) => books.find((b) => b.id === pid)?.kind, today);
  useStore.getState().set({ attention: next });
  const keys = attentionKeys(questions, standing.orders, today);
  const fresh = keys.filter((k) => !known.has(k));
  known = new Set(keys);
  if (fresh.length && (first ? true : true)) announce(fresh, next);
  first = false;
}

const tick = () => { if (AppState.currentState === 'active') void refreshAttention().catch(() => {}); };

export function startAttention(): () => void {
  stopAttention();
  known = new Set();
  first = true;
  tick();
  timer = setInterval(tick, EVERY_MS);
  sub = AppState.addEventListener('change', (s) => { if (s === 'active') tick(); });
  return stopAttention;
}

export function stopAttention() {
  if (timer) clearInterval(timer);
  timer = null;
  sub?.remove();
  sub = null;
}
