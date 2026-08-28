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


def test_collect_images_attachments_and_embeds():
    # alert rooms often post a CHART with little or no text — the picture must
    # reach the vision path (user, 2026-08-28)
    from zargar.tools.discord_gateway import collect_images
    msg = {"attachments": [
        {"content_type": "image/png", "url": "https://cdn.discordapp.com/a/chart.png"},
        {"content_type": "application/pdf", "url": "https://cdn.discordapp.com/a/doc.pdf"},
        {"filename": "SPY.JPEG", "url": "https://cdn.discordapp.com/a/spy.jpeg"}],
        "embeds": [{"image": {"url": "https://cdn.discordapp.com/e/embed.png"},
                    "thumbnail": {"url": "https://cdn.discordapp.com/a/chart.png"}}]}
    urls = collect_images(msg)
    assert urls == ["https://cdn.discordapp.com/a/chart.png",   # attachment first
                    "https://cdn.discordapp.com/a/spy.jpeg",    # by extension
                    "https://cdn.discordapp.com/e/embed.png"]   # embed, deduped


def test_collect_images_none():
    from zargar.tools.discord_gateway import collect_images
    assert collect_images({"content": "SPY 750P", "embeds": [{"title": "x"}]}) == []


def test_image_only_message_flattens_empty_but_has_image():
    from zargar.tools.discord_gateway import collect_images
    msg = {"content": "", "embeds": [],
           "attachments": [{"content_type": "image/png", "url": "https://cdn/x.png"}]}
    assert flatten_message(msg) == ""          # nothing to read...
    assert collect_images(msg) == ["https://cdn/x.png"]   # ...but a picture to see


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


def test_token_decrypt_roundtrip():
    # the leveldb value shape: base64('v10' + 12-byte nonce + AES-GCM(token)).
    # Round-trip it with a known key so the parse+decrypt path is locked
    # without a real Discord install (the DPAPI half is Windows/user-bound).
    import base64
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from zargar.tools.discord_token import _decrypt_token

    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    token = "Mzg0.abc.def-user-token"
    ct = AESGCM(key).encrypt(nonce, token.encode(), None)
    blob = base64.b64encode(b"v10" + nonce + ct)
    assert _decrypt_token(blob, key) == token
    # wrong key / non-v10 payload → None, never a crash
    assert _decrypt_token(blob, AESGCM.generate_key(bit_length=256)) is None
    assert _decrypt_token(base64.b64encode(b"junk"), key) is None


def test_token_marker_regex():
    from zargar.tools.discord_token import TOKEN_RE
    raw = b'somekey"dQw4w9WgXcQ:QUJDREVG"otherkey"dQw4w9WgXcQ:XYZ123"'
    matches = [m.group(1) for m in TOKEN_RE.finditer(raw)]
    assert matches == [b"QUJDREVG", b"XYZ123"]
