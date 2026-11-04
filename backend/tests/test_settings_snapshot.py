"""Settings snapshot (2026-09-27): what a reset would change, secrets never exported, restore only what differs."""
from zargar.tools.settings_snapshot import changes, differences, digest, secret, unwrap


def test_differences_keep_decided_values_and_drop_secrets_and_unknown_keys():
    defaults = {"techniques.tip.prompt_cache": False, "risk.max_position_pct": 10.0, "mobile.vapid": {}, "x.same": 1}
    stored = {"techniques.tip.prompt_cache": True, "risk.max_position_pct": 50.0, "mobile.vapid": {"private": "k"},
              "x.same": 1, "orphan.key": 5}
    assert differences(stored, defaults) == {"risk.max_position_pct": 50.0, "techniques.tip.prompt_cache": True}


def test_secret_words_and_unwrap():
    assert secret("mobile.vapid") and secret("snaptrade.consumer_secret") and secret("x.api_key")
    assert not secret("techniques.tip.prompt_cache")
    assert unwrap('{"v": true}') is True and unwrap({"v": {"a": 1}}) == {"a": 1}


def test_restore_changes_only_what_differs_and_digest_is_stable():
    snap = {"a": 1, "b": {"x": [1, 2]}}
    assert changes(snap, {"a": 1, "b": {"x": [1]}}) == {"b": {"x": [1, 2]}}
    assert digest({"b": 2, "a": 1}) == digest({"a": 1, "b": 2})
