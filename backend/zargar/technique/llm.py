"""Shared Claude plumbing for the technique layer.

One place for: model / effort / thinking-display settings, the async client,
media-type sniffing for uploaded images, a streaming helper that forwards
thinking and text deltas to a callback while accumulating the final message,
and conversion of SDK content blocks into JSON the UI and DB can hold.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

log = logging.getLogger("zargar.technique.llm")

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_MODEL = "claude-opus-5"


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    effort: str = "high"
    thinking_display: str = "summarized"   # summarized | omitted
    max_tokens: int = 16000

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def thinking_param(self) -> dict:
        # Opus 5 defaults `display` to "omitted"; the user asked to *see* the
        # reasoning, so summarized is the default here. Raw chain-of-thought is
        # never returned by the API on this model family.
        return {"type": "adaptive", "display": self.thinking_display}

    def output_config(self, extra: dict | None = None) -> dict:
        cfg: dict[str, Any] = {"effort": self.effort}
        if extra:
            cfg.update(extra)
        return cfg


def config_from_settings(api_key: str, get) -> LLMConfig:
    """Build an LLMConfig from the settings getter (`get(key, default)`)."""
    effort = str(get("llm.effort", "high"))
    if effort not in EFFORT_LEVELS:
        effort = "high"
    display = str(get("llm.thinking_display", "summarized"))
    if display not in ("summarized", "omitted"):
        display = "summarized"
    return LLMConfig(
        api_key=api_key,
        model=str(get("llm.model", DEFAULT_MODEL)) or DEFAULT_MODEL,
        effort=effort,
        thinking_display=display,
        max_tokens=int(get("llm.max_tokens", 16000)),
    )


def make_client(cfg: LLMConfig):
    import anthropic
    return anthropic.AsyncAnthropic(api_key=cfg.api_key)


# --- images ------------------------------------------------------------------

def sniff_media_type(data: bytes) -> str:
    """Real media type from magic bytes. The API rejects a mismatched label."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("unsupported image format (need PNG, JPEG, GIF, or WebP)")


def image_block(data: bytes, media_type: str | None = None) -> dict:
    mt = media_type or sniff_media_type(data)
    return {"type": "image", "source": {"type": "base64", "media_type": mt,
                                        "data": base64.standard_b64encode(data).decode()}}


def decode_data_url(url: str) -> tuple[bytes, str]:
    """'data:image/png;base64,....' → (bytes, sniffed media type)."""
    if not url.startswith("data:"):
        raise ValueError("not a data URL")
    head, _, b64 = url.partition(",")
    raw = base64.standard_b64decode(b64)
    return raw, sniff_media_type(raw)


# --- streaming ---------------------------------------------------------------

EventCb = Callable[[dict], Awaitable[None]] | Callable[[dict], None]


async def _emit(cb: EventCb | None, event: dict) -> None:
    if cb is None:
        return
    r = cb(event)
    if hasattr(r, "__await__"):
        await r


async def stream_message(client, cfg: LLMConfig, *, on_event: EventCb | None = None,
                         **params):
    """Run `client.messages.stream(**params)` forwarding deltas to `on_event`.

    Events emitted: thinking_delta {text}, text_delta {text},
    tool_use_start {id,name}, input_json_delta {partial}, message_done {usage}.
    Returns the final Message (with `.parsed_output` when output_format was set).
    """
    params.setdefault("model", cfg.model)
    params.setdefault("max_tokens", cfg.max_tokens)
    params.setdefault("thinking", cfg.thinking_param())
    oc = params.pop("output_config", None)
    params["output_config"] = cfg.output_config(oc)

    async with client.messages.stream(**params) as stream:
        async for ev in stream:
            et = ev.type
            if et == "content_block_start":
                blk = ev.content_block
                if blk.type == "tool_use":
                    await _emit(on_event, {"type": "tool_use_start", "id": blk.id, "name": blk.name})
                elif blk.type == "thinking":
                    await _emit(on_event, {"type": "thinking_start"})
                elif blk.type == "text":
                    await _emit(on_event, {"type": "text_start"})
            elif et == "content_block_delta":
                d = ev.delta
                if d.type == "thinking_delta" and d.thinking:
                    await _emit(on_event, {"type": "thinking_delta", "text": d.thinking})
                elif d.type == "text_delta" and d.text:
                    await _emit(on_event, {"type": "text_delta", "text": d.text})
                elif d.type == "input_json_delta" and d.partial_json:
                    await _emit(on_event, {"type": "input_json_delta", "partial": d.partial_json})
        msg = await stream.get_final_message()
    u = msg.usage
    await _emit(on_event, {"type": "message_done", "stopReason": msg.stop_reason,
                           "usage": {"input": u.input_tokens, "output": u.output_tokens,
                                     "cacheRead": getattr(u, "cache_read_input_tokens", 0) or 0,
                                     "cacheWrite": getattr(u, "cache_creation_input_tokens", 0) or 0}})
    return msg


def blocks_to_json(content) -> list[dict]:
    """SDK content blocks → plain dicts safe for JSONB and the wire.

    Thinking blocks keep their `signature` so the exact history can be replayed
    to the same model; the UI simply ignores that field.
    """
    out: list[dict] = []
    for b in content:
        t = getattr(b, "type", None)
        if t == "text":
            out.append({"type": "text", "text": b.text})
        elif t == "thinking":
            out.append({"type": "thinking", "thinking": b.thinking or "",
                        "signature": getattr(b, "signature", None)})
        elif t == "redacted_thinking":
            out.append({"type": "redacted_thinking", "data": b.data})
        elif t == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        else:
            try:
                out.append(b.model_dump())
            except Exception:  # pragma: no cover
                out.append({"type": str(t)})
    return out


def json_to_api_blocks(blocks: list[dict]) -> list[dict]:
    """Stored blocks → request content. Drops fields the API does not accept."""
    out: list[dict] = []
    for b in blocks:
        t = b.get("type")
        if t == "thinking":
            sig = b.get("signature")
            if sig:
                out.append({"type": "thinking", "thinking": b.get("thinking", ""), "signature": sig})
            # unsigned thinking (e.g. summarized-only) is not replayable — skip
        elif t in ("text", "tool_use", "tool_result", "image", "redacted_thinking"):
            out.append({k: v for k, v in b.items() if k != "meta"})
        # anything else (ui-only markers) is dropped
    return out


def text_of(content) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", "") == "text")
