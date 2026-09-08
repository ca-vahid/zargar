"""Cartel's per-technique Practice book contract; no shared-book fallback."""
DEFAULT_BOOK = 'techniques.options_cartel.default_portfolio'


def default_practice_book(engine):
    return getattr(engine, 'settings', {}).get(DEFAULT_BOOK, '') or ''


def is_archived(engine, portfolio):
    pid = portfolio.get('id') if isinstance(portfolio, dict) else portfolio.id
    positions = getattr(engine, 'positions', None)
    cached = positions.portfolio(pid) if positions is not None else None
    flag = portfolio.get('archived', False) if isinstance(portfolio, dict) else getattr(portfolio, 'archived', False)
    return bool(flag or (cached or {}).get('archived'))


def validate_account(engine, portfolio):
    if is_archived(engine, portfolio):
        raise ValueError('Archived accounts cannot receive new Cartel arms or entries')
    pid = portfolio.get('id') if isinstance(portfolio, dict) else portfolio.id
    kind = portfolio.get('kind') if isinstance(portfolio, dict) else portfolio.kind
    dedicated = default_practice_book(engine)
    if kind in ('sim', 'shadow') and dedicated and pid != dedicated:
        raise ValueError('Cartel must use its configured dedicated Practice book')
