"""Scout P1 pure layer: EDGAR parsing (real saved filings, no network), the CMP
classifier (incl. no look-ahead), S1 clustering, S2 selection, every gate incl. unknown."""
from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

from zargar.domain import Bar
from zargar.techniques.scout import datasets as ds
from zargar.techniques.scout import gates as G
from zargar.techniques.scout.classify import (OPPORTUNISTIC, ROUTINE, UNCLASSIFIED, Classification,
                                              classify_insiders, classify_one, history_by_insider)
from zargar.techniques.scout.form4 import (ET, clean_ticker, parse_acceptance, parse_daily_index, parse_form4,
                                           parse_header, submissions_json_acceptance, trade_rows)
from zargar.techniques.scout.screens import (S1_KIND, S1_UNCLASSIFIED_KIND, S1Params, S2Params, entry_session_after,
                                             measure_reaction, reaction_day0, s1_purchases, screen_s1, screen_s2)

FIX = Path(__file__).parent / "fixtures" / "scout"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- parsing
def test_acceptance_header_is_et_wall_clock():
    ts = parse_acceptance("20261006090030")
    assert ts.tzinfo is not None and ts.utcoffset() == dt.timedelta(hours=-4)
    assert ts.astimezone(dt.timezone.utc).hour == 13


def test_submissions_json_double_offset_is_undone():
    # verified 2026-10-07 against the SGML headers (DATA-NOTES.md)
    assert submissions_json_acceptance("2026-07-31T00:30:28.000Z") == parse_acceptance("20260730163028")
    assert submissions_json_acceptance("2026-01-30T02:30:33.000Z") == parse_acceptance("20260129163033")
    assert submissions_json_acceptance("2026-10-06T16:00:45.000Z") == parse_acceptance("20261006080045")


def test_parse_sale_by_ten_pct_owner():
    f = parse_form4(read("form4_sale_tenpct.txt"))
    assert f.accession == "0001104659-26-113911" and f.form_type == "4"
    assert f.ticker == "AFL" and f.issuer_cik == "4977" and f.filed_date == "2026-10-06"
    assert f.acceptance_ts == parse_acceptance("20261006090030")
    [o] = f.owners
    assert o.cik == "1783464" and o.is_ten_pct and not o.is_director and not o.is_officer
    assert [(t.code, t.shares, t.price) for t in f.transactions] == [("S", 5671.0, 110.93), ("S", 7529.0, 111.57)]
    rows = trade_rows(f)
    assert len(rows) == 2 and rows[0]["row_key"] == "0001104659-26-113911:0"
    assert rows[0]["value"] == round(5671 * 110.93, 2)


def test_parse_director_purchase_true_false_booleans():
    f = parse_form4(read("form4_purchase_1.txt"))
    [o] = f.owners
    assert o.is_director and not o.is_officer           # booleans spelled true/false
    assert f.acceptance_ts == parse_acceptance("20261006180746")   # after the close
    assert all(t.code == "P" for t in f.transactions)
    assert f.transactions[0].shares == 276300 and f.transactions[0].price == 10.81
    f2 = parse_form4(read("form4_purchase_2.txt"))
    assert f2.ticker == "BORR" and f2.owners[0].is_director and f2.transactions[0].code == "P"


def test_joint_filing_repeats_rows_per_owner_and_skips_non_open_market():
    f = parse_form4(read("form4_joint.txt"))
    assert len(f.owners) == 2 and f.owners[0].is_officer and f.owners[0].officer_title == "Chief Executive Officer"
    assert {t.code for t in f.transactions} <= {"G", "A"}
    assert trade_rows(f) == []                          # gifts/awards are not stored


def test_header_items_for_8k():
    h = parse_header(read("8k_202.hdr.sgml"))
    assert h["form_type"] == "8-K" and "2.02" in h["items"] and h["filed_date"] == "2026-10-06"
    assert h["acceptance_ts"] == parse_acceptance("20261006161531")


def test_daily_index_dedupes_party_listings():
    text = (
        "Form Type   Company Name   CIK   Date Filed  File Name\n"
        "-----------------------------------------------------------\n"
        "4                AFLAC INC                                                     4977        20261006    edgar/data/4977/0001104659-26-113911.txt\n"
        "4                Japan Post Holdings Co., Ltd.                                 1783464     20261006    edgar/data/1783464/0001104659-26-113911.txt\n"
        "4/A              COLL WAYNE M                                                  1260770     20261006    edgar/data/1260770/0001683168-26-007656.txt\n"
        "8-K              B&G Foods, Inc.                                               1278027     20261006    edgar/data/1278027/0001104659-26-113896.txt\n"
        "SCHEDULE 13G/A   SOME FUND                                                     99          20261006    edgar/data/99/0000000099-26-000001.txt\n")
    rows = parse_daily_index(text)
    assert [(r.form_type, r.accession) for r in rows] == [("4", "0001104659-26-113911"), ("4/A", "0001683168-26-007656")]
    assert parse_daily_index(text, forms=("8-K",))[0].cik == "1278027"


def test_clean_ticker():
    assert clean_ticker("brk.b") == "BRK.B" and clean_ticker("NONE") is None and clean_ticker("ABC, ABCD") == "ABC"


def _zip(tmp_path) -> str:
    sub = ("ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
           "0000000001-26-000001\t02-JUL-2026\t4\t0000001234\tXYZ\n"
           "0000000001-26-000002\t03-JUL-2026\t3\t0000001234\tXYZ\n")
    own = ("ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
           "0000000001-26-000001\t0000000777\tDOE JANE\tDirector,Officer\tCFO\n")
    tr = ("ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tSECURITY_TITLE\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\t"
          "TRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\tDIRECT_INDIRECT_OWNERSHIP\n"
          "0000000001-26-000001\t11\tCommon\t30-JUN-2026\tM\t100\t1\tA\tD\n"
          "0000000001-26-000001\t12\tCommon\t01-JUL-2026\tP\t1000\t20.5\tA\tD\n")
    p = tmp_path / "q.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("SUBMISSION.tsv", sub)
        z.writestr("REPORTINGOWNER.tsv", own)
        z.writestr("NONDERIV_TRANS.tsv", tr)
    return str(p)


def test_quarterly_dataset_rows_match_daily_row_identity(tmp_path):
    filings, rows = ds.parse_quarter(_zip(tmp_path))
    assert [f["accession"] for f in filings] == ["0000000001-26-000001"]     # Form 3 ignored
    [r] = rows
    assert r["row_key"] == "0000000001-26-000001:1"     # document order across ALL codes (M was row 0)
    assert r["trans_code"] == "P" and r["trans_date"] == "2026-07-01" and r["value"] == 20500.0
    assert r["is_director"] and r["is_officer"] and r["insider_cik"] == "777" and r["ticker"] == "XYZ"
    assert r["acceptance_ts"] is None and r["filed_date"] == "2026-07-02"
    assert ds.ds_date("28-SEP-2026") == "2026-09-28"


# --------------------------------------------------------------------------- CMP
def t(cik, date, code="S", filed=None):
    return {"insider_cik": cik, "trans_date": date, "trans_code": code, "filed_date": filed or date}


def test_cmp_routine_opportunistic_unclassified():
    trades = [t("R", "2023-03-10"), t("R", "2024-03-02"), t("R", "2025-03-20"), t("R", "2025-08-01"),   # March x3
              t("O", "2023-02-10"), t("O", "2024-05-02"), t("O", "2025-11-20"),                         # every year, no repeat
              t("U", "2024-05-02"), t("U", "2025-05-02")]                                              # missed 2023
    c = classify_insiders(trades, 2026, coverage_start="2023-01-01")
    assert c["R"].label == ROUTINE and c["O"].label == OPPORTUNISTIC and c["U"].label == UNCLASSIFIED


def test_cmp_needs_full_coverage():
    trades = [t("O", "2023-11-10"), t("O", "2024-05-02"), t("O", "2025-11-20")]
    assert classify_insiders(trades, 2026, coverage_start="2023-10-01")["O"].label == UNCLASSIFIED
    assert classify_insiders(trades, 2026, coverage_start="2022-01-01")["O"].label == OPPORTUNISTIC


def test_cmp_no_look_ahead():
    # the March 2026 trade (current year) and a Dec 2025 trade FILED in Jan 2026 must not count
    trades = [t("X", "2023-03-10"), t("X", "2024-03-02"), t("X", "2025-12-30", filed="2026-01-02"),
              t("X", "2026-03-05")]
    h = history_by_insider(trades, 2026)
    assert 2026 not in h["X"] and 12 not in h["X"].get(2025, set())
    c = classify_insiders(trades, 2026, coverage_start="2020-01-01")["X"]
    assert c.label == UNCLASSIFIED                    # 2025 has no trade KNOWN before 2026
    # classification for 2027 sees all of them; 2024/2025/2026 -> March in 2024 + 2026 only
    assert classify_insiders(trades, 2027, coverage_start="2020-01-01")["X"].label == OPPORTUNISTIC


def test_cmp_ignores_non_open_market_codes():
    trades = [t("Y", "2023-03-10", code="A"), t("Y", "2024-03-02"), t("Y", "2025-03-20")]
    assert classify_insiders(trades, 2026, coverage_start="2020-01-01")["Y"].label == UNCLASSIFIED


# --------------------------------------------------------------------------- sessions
def test_entry_session_and_day0():
    pre = dt.datetime(2026, 10, 6, 9, 0, 30, tzinfo=ET)            # Tuesday pre-open
    post = dt.datetime(2026, 10, 6, 18, 7, tzinfo=ET)
    fri = dt.datetime(2026, 10, 9, 16, 30, tzinfo=ET)
    assert entry_session_after(pre) == "2026-10-06" and entry_session_after(post) == "2026-10-07"
    assert entry_session_after(fri) == "2026-10-12"
    assert reaction_day0(dt.datetime(2026, 10, 6, 12, 0, tzinfo=ET)) == "2026-10-06"
    assert reaction_day0(dt.datetime(2026, 10, 6, 16, 15, tzinfo=ET)) == "2026-10-07"
    assert entry_session_after(dt.datetime(2026, 11, 25, 20, 0, tzinfo=ET)) == "2026-11-27"   # Thanksgiving skipped


# --------------------------------------------------------------------------- S1
def buy(cik, date, value, *, acc=None, officer=True, director=False, accepted=None, form="4", issuer="100",
        ticker="ABC", code="P"):
    acc = acc or f"acc-{cik}-{date}"
    return {"accession": acc, "row_key": f"{acc}:0", "form_type": form, "issuer_cik": issuer, "ticker": ticker,
            "insider_cik": cik, "insider_name": f"N{cik}", "is_officer": officer, "is_director": director,
            "officer_title": None, "trans_date": date, "trans_code": code, "acq_disp": "A", "shares": value / 10,
            "price": 10.0, "value": float(value), "filed_date": date,
            "acceptance_ts": accepted or dt.datetime.fromisoformat(date + "T17:00:00").replace(tzinfo=ET),
            "source": "daily"}


def labels(**m):
    return lambda cik, year: Classification(m.get(cik, OPPORTUNISTIC), "test", year)


def test_s1_cluster_fires_at_completing_filing():
    p = S1Params()
    rows = s1_purchases([buy("1", "2026-10-01", 60_000), buy("2", "2026-10-05", 50_000),
                         buy("3", "2026-10-05", 5_000_000, officer=False, director=False)], p)   # 10% owner dropped
    assert len(rows) == 2
    [h] = screen_s1(rows, labels(), p)
    assert h.kind == S1_KIND and h.total_value == 110_000 and len(h.insiders) == 2
    assert h.signal_ts == dt.datetime(2026, 10, 5, 17, 0, tzinfo=ET) and h.entry_date == "2026-10-06"
    assert h.window == ("2026-10-01", "2026-10-05")


def test_s1_rejects_window_value_routine_and_amendments():
    p = S1Params()
    far = [buy("1", "2026-09-20", 80_000), buy("2", "2026-10-05", 80_000)]           # 16 days apart
    assert screen_s1(s1_purchases(far, p), labels(), p) == []
    small = [buy("1", "2026-10-01", 40_000), buy("2", "2026-10-02", 40_000)]
    assert screen_s1(s1_purchases(small, p), labels(), p) == []
    rows = [buy("1", "2026-10-01", 80_000), buy("2", "2026-10-02", 80_000)]
    assert screen_s1(s1_purchases(rows, p), labels(**{"2": ROUTINE}), p) == []
    amend = [buy("1", "2026-10-01", 80_000), buy("2", "2026-10-02", 80_000, form="4/A")]
    assert screen_s1(s1_purchases(amend, p), labels(), p) == []
    sales = [buy("1", "2026-10-01", 80_000), buy("2", "2026-10-02", 80_000, code="S")]
    assert screen_s1(s1_purchases(sales, p), labels(), p) == []


def test_s1_one_insider_twice_is_not_a_cluster_and_joint_value_dedupes():
    p = S1Params()
    rows = [buy("1", "2026-10-01", 80_000), buy("1", "2026-10-03", 80_000, acc="x2")]
    assert screen_s1(s1_purchases(rows, p), labels(), p) == []
    # a joint filing: the same row reported under two officers counts its value once
    j1 = buy("1", "2026-10-02", 60_000, acc="J")
    j2 = {**buy("2", "2026-10-02", 60_000, acc="J")}
    assert screen_s1(s1_purchases([j1, j2], p), labels(), p) == []          # 60k once, not 120k
    p2 = S1Params(min_value_usd=50_000)
    [h] = screen_s1(s1_purchases([j1, j2], p2), labels(), p2)
    assert h.total_value == 60_000 and len(h.insiders) == 2


def test_s1_unclassified_tracked_separately_and_one_hit_per_cluster():
    p = S1Params()
    rows = s1_purchases([buy("1", "2026-10-01", 80_000), buy("2", "2026-10-02", 80_000),
                         buy("3", "2026-10-03", 80_000)], p)
    lab = labels(**{"2": UNCLASSIFIED})
    main = screen_s1(rows, lab, p)
    assert len(main) == 1 and {i["insiderCik"] for i in main[0].insiders} == {"1", "3"}   # completes on day 3
    rows2 = s1_purchases([buy("1", "2026-10-01", 80_000), buy("2", "2026-10-02", 80_000)], p)
    assert screen_s1(rows2, lab, p) == []
    [u] = screen_s1(rows2, lab, p, include_unclassified=True)
    assert u.kind == S1_UNCLASSIFIED_KIND
    assert screen_s1(rows, lab, p, include_unclassified=True)[0].anchor_date == "2026-10-02"


def test_s1_point_in_time_uses_dataset_filing_date_conservatively():
    p = S1Params()
    a = {**buy("1", "2026-10-01", 80_000), "acceptance_ts": None, "filed_date": "2026-10-02"}
    b = {**buy("2", "2026-10-02", 80_000), "acceptance_ts": None, "filed_date": "2026-10-05"}
    [h] = screen_s1(s1_purchases([a, b], p), labels(), p)
    assert h.signal_time_approx and h.signal_ts.date() == dt.date(2026, 10, 5) and h.entry_date == "2026-10-06"


# --------------------------------------------------------------------------- S2
def daily(sym, start: str, closes: list[float], vols: list[float]) -> list[Bar]:
    import zargar.marketstructure.market_calendar as mcal
    d = dt.date.fromisoformat(start)
    out = []
    for c, v in zip(closes, vols):
        while not mcal.is_trading_day(d):
            d += dt.timedelta(days=1)
        ts = int(dt.datetime.combine(d, dt.time(9, 30), ET).timestamp() * 1000)
        out.append(Bar(sym, "1d", ts, c, c, c, c, int(v)))
        d += dt.timedelta(days=1)
    return out


def _series(jump: float, vol_mult: float):
    """22 flat sessions to 2026-10-05 (Mon), day 0 = 2026-10-06, day 1 = 10-07."""
    closes = [100.0] * 21 + [100.0 * (1 + jump / 2), 100.0 * (1 + jump)]
    vols = [1_000_000] * 21 + [1_000_000 * vol_mult, 1_500_000]
    return closes, vols


def test_s2_measure_and_rank():
    p = S2Params()
    start = "2026-09-04"
    bench = daily("SPY", start, [400.0] * 21 + [401.0, 402.0], [1] * 23)
    ev = lambda tk, acc: {"ticker": tk, "accession": acc,
                          "acceptance_ts": dt.datetime(2026, 10, 5, 16, 30, tzinfo=ET)}     # after close -> day0 10-06
    reactions = []
    for i, (jump, vm) in enumerate([(0.12, 3.0), (0.20, 1.5)] + [(0.01 * k, 3.0) for k in range(10)]):
        closes, vols = _series(jump, vm)
        reactions.append(measure_reaction(ev(f"T{i}", f"a{i}"), daily(f"T{i}", start, closes, vols), bench, p))
    r0 = reactions[0]
    assert r0.day0 == "2026-10-06" and r0.day1 == "2026-10-07"
    assert abs(r0.abnormal_return - (0.12 - 0.005)) < 1e-9 and r0.volume_ratio == 3.0
    hits, verdicts = screen_s2(reactions, p)
    # 12 events -> top ceil(1.2) = 2; T1 (+20%) fails volume, T0 (+12%) rank 2 passes
    assert [h.reaction.ticker for h in hits] == ["T0"]
    assert hits[0].entry_date == "2026-10-08" and hits[0].rank == 2 and hits[0].cutoff_rank == 2
    assert any(v["ticker"] == "T1" and "volume" in v["why"] for v in verdicts)


def test_s2_unmeasurable_event_is_recorded_not_ranked():
    p = S2Params()
    r = measure_reaction({"ticker": "Z", "accession": "z", "acceptance_ts": dt.datetime(2026, 10, 5, 8, 0, tzinfo=ET)},
                         [], [], p)
    assert r.abnormal_return is None and "missing" in r.why
    hits, verdicts = screen_s2([r], p)
    assert hits == [] and verdicts[0]["selected"] is False


def test_s2_negative_reaction_never_selected():
    p = S2Params()
    start = "2026-09-04"
    bench = daily("SPY", start, [400.0] * 23, [1] * 23)
    closes, vols = _series(-0.10, 4.0)
    r = measure_reaction({"ticker": "D", "accession": "d", "acceptance_ts": dt.datetime(2026, 10, 5, 17, 0, tzinfo=ET)},
                         daily("D", start, closes, vols), bench, p)
    hits, verdicts = screen_s2([r], p)
    assert hits == [] and "not positive" in verdicts[0]["why"]


# --------------------------------------------------------------------------- gates
GP = G.GateParams()


def test_gate_price_and_adv():
    assert G.gate_price(4.99, GP)["status"] == "fail" and G.gate_price(5.0, GP)["status"] == "pass"
    assert G.gate_price(None, GP)["status"] == "unknown"
    assert G.gate_adv([(10.0, 600_000)] * 20, GP)["status"] == "pass"
    assert G.gate_adv([(10.0, 400_000)] * 20, GP)["status"] == "fail"
    assert G.gate_adv([(10.0, 600_000)] * 5, GP)["status"] == "unknown"
    assert G.gate_price(1.0, G.GateParams(min_price=0))["status"] == "off"


def test_gate_spread_unknown_never_passes():
    assert G.gate_spread(None, GP, pending_why="pending")["status"] == "unknown"
    assert G.gate_spread(0.4, GP)["status"] == "pass" and G.gate_spread(0.6, GP)["status"] == "fail"


def test_gate_market_cap():
    assert G.gate_market_cap(None, GP)["status"] == "unknown"
    assert G.gate_market_cap(2.9e8, GP)["status"] == "fail" and G.gate_market_cap(3e8, GP)["status"] == "pass"


def test_gate_earnings_in_hold():
    assert G.gate_earnings_in_hold("2026-10-06", "2026-11-02", ["2026-10-20"], GP)["status"] == "fail"
    assert G.gate_earnings_in_hold("2026-10-06", "2026-11-02", ["2026-12-01"], GP)["status"] == "pass"
    assert G.gate_earnings_in_hold("2026-10-06", "2026-11-02", None, GP)["status"] == "unknown"
    assert G.gate_earnings_in_hold("2026-10-06", "2026-11-02", None,
                                   G.GateParams(no_earnings_in_hold=False))["status"] == "off"


def test_gate_corporate_actions_and_tips():
    acts = [{"type": "reverse_split", "date": "2026-06-01"}]
    assert G.gate_corporate_actions(acts, "2026-10-06", GP)["status"] == "fail"
    assert G.gate_corporate_actions([{"type": "reverse_split", "date": "2025-12-01"}], "2026-10-06", GP)["status"] == "pass"
    assert G.gate_corporate_actions(None, "2026-10-06", GP)["status"] == "unknown"
    assert G.gate_tips_mention([{"source": "discord-x"}], GP)["status"] == "fail"
    assert G.gate_tips_mention([], GP)["status"] == "pass"
    assert G.gate_tips_mention(None, GP)["status"] == "unknown"


def test_overall_status():
    assert G.overall({"a": {"status": "pass"}, "b": {"status": "off"}}) == "pass"
    assert G.overall({"a": {"status": "pass"}, "b": {"status": "unknown"}}) == "unknown"
    assert G.overall({"a": {"status": "fail"}, "b": {"status": "unknown"}}) == "fail"


def test_shares_market_cap_point_in_time():
    from zargar.techniques.scout.service import shares_market_cap
    data = {"units": {"shares": [
        {"end": "2026-04-30", "val": 1_000_000, "accn": "a", "filed": "2026-05-05"},
        {"end": "2026-07-31", "val": 600_000, "accn": "b", "filed": "2026-08-05"},      # class A
        {"end": "2026-07-31", "val": 400_000, "accn": "b", "filed": "2026-08-05"},      # class B
        {"end": "2026-10-31", "val": 9_000_000, "accn": "c", "filed": "2026-11-05"}]}}  # future: not known yet
    mcap, why = shares_market_cap(data, 50.0, "2026-10-06")
    assert mcap == 1_000_000 * 50.0 and "2026-07-31" in why
    assert shares_market_cap({}, 50.0, "2026-10-06")[0] is None
