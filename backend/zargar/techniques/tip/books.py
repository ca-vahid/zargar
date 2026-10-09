"""Tips books: one method, several accounts (W6, 2026-10-03; design in
docs/techniques/tip/research/2026-10-02-tips-review/E-architecture.md §5).

`techniques.tip.books` binds the Tips method to one or more books. The analyst appraises a signal ONCE; each
enabled binding then gets its own proposal, sized and gated by that book's own budget and caps. An empty list keeps
the pre-W6 behaviour: one synthesized binding from `techniques.tip.default_portfolio`.

Pure helpers (no I/O). Per-book knob resolution: binding field -> `techniques.tip.<key>` -> caller default.
"""
from __future__ import annotations

import contextvars
from dataclasses import asdict, dataclass, field

ROLES = ("practice", "live")

# binding field -> the global settings key it overrides
KNOBS = {
    "budgetPerTip": "techniques.tip.budget_per_tip",
    "maxOpenPositions": "techniques.tip.max_open_positions",
    "capitalCap": "techniques.tip.live_capital_cap",
    "reserveSlots": "techniques.tip.reserve_slots",
    "minBudget": "techniques.tip.min_budget",
    "riskPct": "techniques.tip.risk_pct",
    "riskBudgetPerTip": "techniques.tip.risk_budget_per_tip",
    "maxPremiumPerTip": "techniques.tip.max_premium_per_tip",
    "maxOpenRiskPct": "techniques.tip.max_open_risk_pct",     # v0.9 V5.1 (2026-10-05)
    # 2026-10-08 setup review (small-account costs and concentration)
    "onePerName": "techniques.tip.one_position_per_name",
    "minTradeNotional": "techniques.tip.min_trade_notional",
    "minExitNotional": "techniques.tip.min_exit_order_notional",
    "swingStaleSessions": "techniques.tip.horizon_swing_sessions",
}


@dataclass
class Binding:
    portfolioId: str
    role: str = "practice"
    enabled: bool = True
    primary: bool = False
    mode: str = "auto"                     # auto | proposal (a proposal-mode book never self-approves)
    allowLiveAuto: bool | None = None      # live-role books: this book may self-approve (None = legacy rule)
    armAtLevel: bool = True                # at-level takes arm a waiting plan in this book
    mirror: bool | None = None             # mirror the source's own exits (None = the policy default)
    sharesOnly: bool | None = None         # None = techniques.tip.live_shares_only for live/paper books
    overrides: dict = field(default_factory=dict)   # KNOBS fields set on this binding
    legacy: bool = False                   # synthesized from default_portfolio (empty books list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(d.pop("overrides") or {})
        return d


def _parse_one(raw: dict) -> Binding:
    raw = dict(raw or {})
    ov = {k: raw[k] for k in KNOBS if raw.get(k) is not None}
    return Binding(portfolioId=str(raw.get("portfolioId") or ""), role=str(raw.get("role") or "practice"),
                   enabled=bool(raw.get("enabled", True)), primary=bool(raw.get("primary", False)),
                   mode=str(raw.get("mode") or "auto"),
                   allowLiveAuto=(None if raw.get("allowLiveAuto") is None else bool(raw.get("allowLiveAuto"))),
                   armAtLevel=bool(raw.get("armAtLevel", raw.get("role") != "live")),
                   mirror=(None if raw.get("mirror") is None else bool(raw.get("mirror"))),
                   sharesOnly=(None if raw.get("sharesOnly") is None else bool(raw.get("sharesOnly"))),
                   overrides=ov)


def validate(raw_list, portfolio_of) -> list[str]:
    """Problems with a `techniques.tip.books` value ([] = valid). `portfolio_of(pid)` -> the portfolio dict or None."""
    errs: list[str] = []
    if raw_list in (None, []):
        return errs
    if not isinstance(raw_list, list):
        return ["techniques.tip.books must be a list"]
    seen: set[str] = set()
    primaries = 0
    for i, raw in enumerate(raw_list):
        if not isinstance(raw, dict):
            errs.append(f"book {i}: not an object")
            continue
        b = _parse_one(raw)
        if not b.portfolioId:
            errs.append(f"book {i}: portfolioId missing")
            continue
        if b.portfolioId in seen:
            errs.append(f"book {i}: duplicate portfolio {b.portfolioId}")
        seen.add(b.portfolioId)
        if b.role not in ROLES:
            errs.append(f"book {i}: role must be one of {ROLES}")
        if b.mode not in ("auto", "proposal"):
            errs.append(f"book {i}: mode must be auto or proposal")
        pf = portfolio_of(b.portfolioId)
        if pf is None:
            errs.append(f"book {i}: portfolio {b.portfolioId} does not exist")
        else:
            kind = pf.get("kind")
            if pf.get("archived"):
                errs.append(f"book {i}: portfolio {pf.get('name')} is archived")
            if kind == "shadow" or pf.get("book"):
                errs.append(f"book {i}: shadow/research books are never bound")
            if b.role == "live" and kind not in ("live", "paper"):
                errs.append(f"book {i}: role live needs a live or paper account (got {kind})")
            if b.role == "practice" and kind != "sim":
                errs.append(f"book {i}: role practice needs a sim book (got {kind})")
        for k, v in b.overrides.items():
            try:
                if float(v) < 0:
                    errs.append(f"book {i}: {k} must be >= 0")
            except (TypeError, ValueError):
                errs.append(f"book {i}: {k} must be a number")
        primaries += 1 if b.primary else 0
    if primaries > 1:
        errs.append("exactly one book may be primary")
    return errs


def resolve_books(settings, portfolio_of, fallback_pid: str | None = None) -> list[Binding]:
    """The bindings in force, primary first. Empty/invalid list -> one legacy binding on
    `techniques.tip.default_portfolio` (or `fallback_pid`). Disabled bindings are kept (callers skip them) so the
    record can say why a book got nothing. Exactly one binding is primary: the flagged one, else the first enabled
    practice book, else the first enabled."""
    raw = settings.get("techniques.tip.books", []) or []
    out: list[Binding] = []
    if isinstance(raw, list) and raw and not validate(raw, portfolio_of):
        out = [_parse_one(r) for r in raw]
    if not out:
        pid = str(settings.get("techniques.tip.default_portfolio", "") or settings.get("trading.default_portfolio", "")
                  or fallback_pid or "")
        if not pid or portfolio_of(pid) is None:
            pid = fallback_pid or ""
        if not pid:
            return []
        pf = portfolio_of(pid) or {}
        return [Binding(portfolioId=pid, role=("live" if pf.get("kind") in ("live", "paper") else "practice"),
                        primary=True, legacy=True)]
    if not any(b.primary for b in out):
        pick = next((b for b in out if b.enabled and b.role == "practice"), None) or next(
            (b for b in out if b.enabled), out[0])
        pick.primary = True
    out.sort(key=lambda b: (not b.primary,))
    return out


def primary(settings, portfolio_of, fallback_pid: str | None = None) -> Binding | None:
    bs = resolve_books(settings, portfolio_of, fallback_pid)
    return next((b for b in bs if b.primary), bs[0] if bs else None)


def binding_for(settings, portfolio_of, pid: str) -> Binding | None:
    return next((b for b in resolve_books(settings, portfolio_of) if b.portfolioId == pid), None)


def knob(binding: Binding | None, key: str, settings, default=None):
    """binding override -> the global techniques.tip key -> default."""
    if binding is not None and key in KNOBS and binding.overrides.get(key) is not None:
        return binding.overrides[key]
    gk = KNOBS.get(key, key)
    v = settings.get(gk, default)
    return default if v is None else v


def rescale_qty(qty_hint, *, primary_budget: float | None, book_budget: float | None) -> int:
    """The analyst sized its quantity against the PRIMARY book; another book takes it in proportion to its own
    budget (never more than the hint)."""
    try:
        q = int(qty_hint or 0)
    except (TypeError, ValueError):
        return 0
    if q <= 0:
        return 0
    if not primary_budget or not book_budget or primary_budget <= 0 or book_budget >= primary_budget:
        return q
    return max(1, int(q * float(book_budget) / float(primary_budget)))


# ---- the binding the current proposal is being built for (so deep helpers - the risk budget - read per-book knobs
# without threading a parameter through every call)
_CURRENT: contextvars.ContextVar[Binding | None] = contextvars.ContextVar("tip_book", default=None)


def current() -> Binding | None:
    return _CURRENT.get()


class use:
    """with books.use(binding): ... - deep helpers see the binding through `current()` / `BookSettings`."""

    def __init__(self, binding: Binding | None):
        self.binding, self._tok = binding, None

    def __enter__(self):
        self._tok = _CURRENT.set(self.binding)
        return self.binding

    def __exit__(self, *exc):
        _CURRENT.reset(self._tok)
        return False


# V5.2 / V6.2 / V6.3 (2026-10-05): a per-idea multiplier (<= 1) on the RISK budget while a card is built - the
# source's fractional Kelly, the regime guard and the chase filter in enforce mode. Read only by BookSettings for the
# two risk-budget keys, so the geometry gate and the risk-first sizer size against the same scaled budget.
_RISK_SCALE: contextvars.ContextVar[float] = contextvars.ContextVar("tip_risk_scale", default=1.0)
RISK_KEYS = ("techniques.tip.risk_pct", "techniques.tip.risk_budget_per_tip")


def risk_scale() -> float:
    return _RISK_SCALE.get()


class scale_risk:
    """with books.scale_risk(0.5): ... - the risk budget the deep helpers see is multiplied (clamped to 0..1)."""

    def __init__(self, scale: float | None):
        try:
            v = float(1.0 if scale is None else scale)
        except (TypeError, ValueError):
            v = 1.0
        self.scale, self._tok = max(0.0, min(1.0, v)), None

    def __enter__(self):
        self._tok = _RISK_SCALE.set(self.scale)
        return self.scale

    def __exit__(self, *exc):
        _RISK_SCALE.reset(self._tok)
        return False


class BookSettings:
    """A read-only settings view that answers the overridden KNOBS keys from the current binding (and applies the
    current per-idea risk scale to the risk-budget keys)."""

    def __init__(self, settings, binding: Binding | None = None):
        self._s, self._b = settings, binding if binding is not None else current()
        self._rev = {v: k for k, v in KNOBS.items()}

    def get(self, key, default=None):
        v = self._get(key, default)
        sc = _RISK_SCALE.get()
        if key in RISK_KEYS and sc < 1.0 and v is not None:
            try:
                return float(v) * sc
            except (TypeError, ValueError):
                return v
        return v

    def _get(self, key, default=None):
        b = self._b
        if b is not None:
            f = self._rev.get(key)
            if f is not None and b.overrides.get(f) is not None:
                return b.overrides[f]
        return self._s.get(key, default)

    def __getattr__(self, name):
        return getattr(self._s, name)


def live_unattended(settings, binding: Binding | None) -> bool:
    """User decision 2026-10-03 ("more autonomous than manual - I often can't answer for hours"): a LIVE book whose
    binding carries its own allowLiveAuto acknowledgement decides its cards like unattended Practice - the analyst's
    take approves, skip/watch declines on the record - instead of leaving them for a person.
    `techniques.tip.live_unattended` False restores 'live keeps the human'."""
    if binding is None or binding.legacy or binding.role != "live" or not binding.allowLiveAuto:
        return False
    try:
        return bool(settings.get("techniques.tip.live_unattended", True))
    except Exception:                                      # noqa: BLE001
        return False
