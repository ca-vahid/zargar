"""Research performance must not pool Practice and quarantined shadow evidence."""
from zargar.techniques.tip import holdstudy as hs


def row(kind, **extra):
    return {"id": kind, "positionId": kind, "arm": "carry", "symbol": "XYZ", "legSymbol": "XYZ",
        "secType": "STK", "qty": 10, "entryPrice": 100, "multiplier": 1,
        "plannedRisk": 50, "plannedRiskQty": 10, "bookKind": kind,
        "precloseQuote": {"bid": 101}, "precloseStatus": "fresh",
        "nextOpenQuote": {"bid": 102}, "nextOpenStatus": "fresh", **extra}


def test_practice_and_shadow_results_are_not_one_performance_bucket():
    result = hs.aggregate([hs.compare_row(row("sim")), hs.compare_row(row("shadow"))])
    assert all(len(group.get("books", {})) <= 1 for group in result["setups"].values()), \
        "book counts alongside a mixed net-PnL sum are not separated performance"


def test_quarantined_book_is_not_adequate_performance_evidence():
    result = hs.compare_row(row("shadow", quarantined=True, quarantineReason="unreconciled inventory"))
    assert not result["adequate"], "quarantined inventory produced an adequate research result"
