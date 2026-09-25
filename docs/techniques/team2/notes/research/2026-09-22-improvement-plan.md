# Team2 improvement plan — 2026-09-22

Written after a −$2,217 Practice day, at the user's request to make the approach more profitable.
Everything below is measured unless it says otherwise. All Team2 books are simulated; no real money
was at risk.

---

## 1. The honest bottom line

**No change we know of makes the automated Team2 method profitable, and I am not going to pretend
otherwise.** Eleven single-factor changes have now been measured on real option prints — nine on
2026-09-19 and two tonight — and none clears the frozen criterion. The fastest route to *more
money* is therefore not a tweak; it is to stop paying for evidence we already have, cut the cost
that is certain, and let the programmes that could actually find an edge finish.

What we did prove tonight is valuable: the one untested idea the author's own words supported
(premium stop as a backstop) **does not help**. That spares us from changing a rule on the strength
of one memorable trade.

## 2. How Casey did today — not verified

I could not get his posts. X refuses automated logged-out access (HTTP 402), its embed endpoint
rate-limited us (429), and the Chrome extension that reaches your signed-in browser was not
connected. Web search surfaced a recap ("QQQ puts −25%, SPY calls +130%") with no date I could tie to
today, so I am not reporting it as today's.

Even when we get it, his public recaps are self-selected — he states he reviews only trades he
personally alerted — so they are evidence about his entries and exits, not an unbiased P&L. To
compare fairly: **connect the Chrome extension and I will pull `from:Team2Trading` for the day** and
set his exits beside ours on the same contracts.

## 3. Where we stand

| book | total since start | today | state |
|---|---|---|---|
| Team2 Control | −$1,337 (−13.4%) | −$1,011 | reference book, never auto-paused by design; its plans hit their own loss halts at 10:39 |
| Team2 C1 Conjunction | −$1,322 (−13.2%) | −$649 | **auto-paused at 10:30** when it crossed its $1,000 threshold — which is why it skipped the losing 10:38 re-entry |
| Team2 Sizing 0.5 | −$748 (−7.5%) | −$557 | $52 from its $800 threshold |
| EM Practice | −$123 (−1.2%) | −$175 | the EM desk's A/B baseline |
| EM Experimental | −$269 (−2.7%) | −$269 | the EM desk's A/B arm |
| Tips Practice | −$820 (−8.2%) | +$213 | |

Every active Practice book on the platform is down. Across three Team2 sessions, all seven book-days
lost, **−$3,408** in total, of which **$772 (23%) is commissions**.

**The protections worked today.** Every exit was decided on the held contract's own quote and fill
(the F129 fix deployed last night), C1 paused itself on its preregistered threshold, and Control's
plans stopped on their loss halts. The losses are the method's, not the machinery's.

### Correction to my earlier review

I told you C1 was past its threshold and not paused, and that Control's drawdown was unmonitored.
Both were wrong. I read a field that the portfolio API does not carry. C1 paused itself at 10:30, and
Control carries no drawdown threshold on purpose because it is the untouched reference the other
two are compared against.

## 4. Why the method loses, as far as the evidence goes

| lever | evidence | verdict |
|---|---|---|
| premium-stop width | H6 tonight: +0.18 points at −40%, and no stop at all is no better | **not the leak** |
| candle stop, target, trims, entry zone, re-plans, brackets | nine arms, 2026-09-19 | none clears the criterion |
| **costs** | about zero edge at no fee, −3.7% per trade at the books' fee, −7.6% at one tick | **the one certain drag** |
| dearer contract (H5) | the only arm with an interval above zero, at one tick, and for arithmetic reasons | reduces the bleed; its own mean stays negative |

The cost arithmetic is mechanical. Fees are charged **per contract**, so a $0.52 contract pays
$2.08 per round trip on $52 of premium — **4.0%** — before the spread. A $1.20 contract pays the same
fee on $120, 1.7%. Buying 38 cheap contracts rather than 16 dearer ones for the same premium roughly
doubles the fee drag. That does not create an edge, but it is the only lever the data says moves the
number in the right direction.

## 5. Book cleanup

| book | action | why |
|---|---|---|
| **Team2 Practice** | **archived** tonight (reversible) | idle since 2026-09-17, superseded by the three experiment books, no plans, no positions, no setting pointing at it |
| EM Practice, EM Experimental | **kept** | not useless — they are the two arms of the EM desk's live A/B comparison and both traded today. Removing either would destroy that experiment. Not ours to remove |
| Options Cartel Practice – Capital | left for its owner | never traded; the Cartel desk's to decide |
| Shadow: flow-scan and flow-scan (armed) | left for their owner | idle since 2026-09-01 or never traded; the Tips/Flow desk's to decide |

## 6. Done tonight

1. **Archived** the idle Team2 Practice book.
2. **Tested H6** — premium stop as a backstop — registered and committed before running, on 69
   sessions of real option prints. **Failed.** The premium stop stays at 25%.
3. **Built `team2_exit_review`**, a read-only after-close report of every exit: who decided it,
   whether structure was intact, when it broke, and what the contract did next. It turns the one
   thing the replay could not see into a daily count. Over the three sessions so far: seven exit
   decisions, one premium stop cut well ahead of structure (today, 29 minutes early).
4. **Recorded the OPRA vendor timestamp** on every option quote and on every premium-stop
   confirmation, without changing any decision. The confirmation rule still counts polls; the record
   now says whether those polls were genuinely distinct vendor prints. The obvious fix — confirming on
   the vendor stamp — is **not** safe, because a genuine standing bleed keeps the same stamp and would
   never confirm. We now measure how often the defect bites before redesigning the rule.

Items 3 and 4 are on PR (see section 9) and are **not deployed**: item 4 touches the shared option-quote
path, so the other desks see it first.

## 7. The plan

### Phase 1 — this week: stop paying for evidence we have

- **Run the exit review and the opportunity audit after every close.** Both are order-free. They
  answer the two open questions — does the live premium stop cut intact trades often enough to
  matter, and how many candidates never reach contract selection — with prospective evidence.
- **Keep the selection study collecting** (2 of 60 counted sessions). It is the only programme
  designed to find *which setups* carry an edge, which is where a real improvement would come from.
- **No new replay arms on the training window.** Eleven tests on the same 69 sessions already strain
  it; each further arm raises the chance of a false pass.

### Phase 2 — needs your decision: exposure while evidence accumulates

The books are simulated, so their losses cost nothing real. Their value is **execution evidence**:
real fills against real quotes, which is what calibrates cost. The question is how much of it we
need, at what size.

| option | effect | cost to the experiment |
|---|---|---|
| **A. keep all three books as they are** (recommended) | the Control/Sizing/C1 comparison runs to its 20-session review as registered | none |
| B. halve every book's size | cuts simulated losses about in half | breaks the comparison: Control stops being the reference |
| C. pause all Team2 entries, keep only the order-free studies | stops the losses | loses fill-versus-quote evidence entirely |

I recommend **A**. The comparison was designed with preregistered thresholds; C1 has already done
what it was built to do and paused itself. Changing the design mid-run to save simulated dollars
would discard the only thing those dollars buy.

### Phase 3 — the author gap

Our automation loses; the author reports wins. That gap is either discretion we do not capture
(which trades he skips, where he actually takes profit) or selection in what he publishes. The
2026-09-19 comparison found his entries mostly undocumented. The one route to closing it is his
actual trade list for the same days — connect Chrome and I will build a side-by-side ledger.

### Phase 4 — the 20-session review, and real money

- At **20 sessions** (about 2026-10-15) the registered review decides each experiment arm. If no arm
  is positive after costs, the recommendation will be to retire Team2 *automation* to an
  observation-only instrument and keep its studies running.
- **No Team2 real money** until an arm passes a preregistered criterion on held-out data. Nothing is
  close today.
- **If you want the certain cost win sooner:** H5, a dearer contract, is the candidate. It failed the
  criterion, so it cannot be activated on the existing evidence. It could be registered as a fresh
  prospective Practice test — a new book, which needs your explicit approval.

## 8. What I am deliberately not doing

- **Not tuning the premium stop** to another width on the same data. That would be a search, not a
  test.
- **Not removing the EM books.** They are a live experiment belonging to another desk.
- **Not deploying the shared-quote change tonight** without the other desks having seen it.
- **Not treating one trade as a pattern**, in either direction.

## 9. Decisions needed from you

1. **Exposure:** option A, B or C above. I recommend A.
2. **Deployment:** approve deploying the exit-review tool and the vendor-stamp recording after
   tomorrow's close, once the other desks have reviewed the shared-path part.
3. **Casey's trade log:** connect the Chrome extension so I can pull his posts and build the
   side-by-side comparison.
4. **Optional:** register H5 (dearer contract) as a prospective Practice test on a new book.
