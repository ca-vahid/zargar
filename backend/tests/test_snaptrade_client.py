"""SnapTradeClient: request signing, wire shape, and error classification."""
import httpx
import pytest

from zargar.brokers.snaptrade import (
    SnapTradeClient,
    SnapTradeError,
    SnapTradeUnknownOutcome,
    dashed_uuid,
    exec_id_for,
)


async def test_signing_vector():
    """The HMAC signature must match a precomputed vector exactly —
    any canonicalization drift (key order, separators, encoding) breaks auth."""
    client = SnapTradeClient("TESTCID", "test-consumer-key",
                             transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    sig = client._sign(
        "/api/v1/snapTrade/login",
        "clientId=TESTCID&timestamp=1700000000",
        {"connectionType": "trade"},
    )
    assert sig == "vlCK46CVm+F+x2bkud7p9Pbhiju1IKU7CknA0+n4jpY="
    await client.aclose()


async def test_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["signature"] = request.headers.get("Signature")
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = SnapTradeClient("CID", "KEY", transport=httpx.MockTransport(handler))
    result = await client.request("POST", "/api/v1/trade/place", {"units": 1})
    assert result == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/trade/place"
    assert seen["params"]["clientId"] == "CID"
    assert seen["params"]["timestamp"].isdigit()
    assert seen["signature"]  # non-empty base64
    assert b'"units"' in seen["body"]
    await client.aclose()


async def test_error_classification():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/bad":
            return httpx.Response(400, json={"detail": "nope"})
        if request.url.path == "/down":
            return httpx.Response(502, text="bad gateway")
        raise httpx.ConnectError("network broke")

    client = SnapTradeClient("CID", "KEY", transport=httpx.MockTransport(handler))
    with pytest.raises(SnapTradeError) as err:
        await client.request("GET", "/bad")
    assert err.value.status == 400 and "nope" in str(err.value)
    with pytest.raises(SnapTradeUnknownOutcome):
        await client.request("GET", "/down")
    with pytest.raises(SnapTradeUnknownOutcome):
        await client.request("GET", "/gone")
    await client.aclose()


def test_dashed_uuid_and_exec_id_determinism():
    hex_id = "a3f2b4c6d8e0f1a2b3c4d5e6f7a8b9c0"
    dashed = dashed_uuid(hex_id)
    assert dashed.replace("-", "") == hex_id
    assert len(dashed) == 36
    assert exec_id_for("bo-1", 2.0) == exec_id_for("bo-1", 2.0)
    assert exec_id_for("bo-1", 2.0) != exec_id_for("bo-1", 3.0)
    assert len(exec_id_for("bo-1", 2.0)) == 32
