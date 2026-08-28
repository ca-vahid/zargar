"""Pure-logic tests for the experimental Discord gateway listener.

No token, no socket — only the message flattening / filtering / identify shape,
which is the part that must be right for the OWLS alert DMs to intake cleanly.
"""
from zargar.tools.discord_gateway import (
    OP_IDENTIFY, describe_author, flatten_message, _identify)


def test_flatten_embed_alert():
    # OWLS alert: content empty, the trade lives in the embed
    msg = {"content": "", "author": {"username": "OWLS Capital Clanker", "bot": True},
           "embeds": [{"author": {"name": "RegardedTrader (Jon)"},
                       "description": "OPEN:\nNTR 82.5C 03/19/2027 Exp. At 4.60",
                       "footer": {"text": "Informational purposes only."}}]}
    text = flatten_message(msg)
    assert "RegardedTrader (Jon)" in text
    assert "NTR 82.5C 03/19/2027 Exp. At 4.60" in text
    assert "Informational purposes only." in text


def test_flatten_plain_content():
    msg = {"content": "SPY 750P 09/18 Exp. At 3.38!!", "embeds": []}
    assert flatten_message(msg) == "SPY 750P 09/18 Exp. At 3.38!!"


def test_flatten_embed_fields():
    msg = {"content": "", "embeds": [{"title": "Trade", "fields": [
        {"name": "Ticker", "value": "AAPL"}, {"name": "Strike", "value": "240C"}]}]}
    text = flatten_message(msg)
    assert "Trade" in text and "Ticker: AAPL" in text and "Strike: 240C" in text


def test_describe_author_bot_flag():
    assert describe_author({"author": {"global_name": "Clanker", "bot": True}}) == "Clanker [bot]"
    assert describe_author({"author": {"username": "jon"}}) == "jon"
    assert describe_author({}) == "unknown"


def test_identify_is_user_shaped():
    ident = _identify("secret-token")
    assert ident["op"] == OP_IDENTIFY
    assert ident["d"]["token"] == "secret-token"
    # user accounts must NOT send intents (bot-only); presence + properties only
    assert "intents" not in ident["d"]
    assert ident["d"]["properties"]["os"] == "Windows"
    assert ident["d"]["compress"] is False
