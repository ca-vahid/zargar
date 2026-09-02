"""EM ingestion worker: pending video notes -> audio -> transcript -> the app.

docs/techniques/enhanced-market/INGESTION-PLAN.md phase 2. Runs as its OWN
process (like the Discord gateway) so the app never imports the media stack:
yt-dlp (download), ffmpeg (on PATH), faster-whisper (CPU transcription).

Loop: GET /api/technique/ingest/pending -> for each note: download the link's
audio -> transcribe -> POST /api/technique/ingest/transcript. A failure (still
live, no video, network) is POSTed as an error; the app retries it on later
polls up to `techniques.enhanced_market.ingest.transcribe_max_attempts`.

Usage (from backend/, in a venv that has yt-dlp + faster-whisper; scripts/em-ingest.ps1
creates backend/.venv-ingest for exactly this):
  ZARGAR_SESSION=$(python -m zargar.tools.mint_session) python -m zargar.tools.em_ingest
  python -m zargar.tools.em_ingest --once          # drain what's pending and exit
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

API_DEFAULT = "http://127.0.0.1:8420"


class _Deferred(Exception):
    """Control flow: the broadcast is still live - report a deferral, not a failure."""


def download_audio(url: str, out_dir: Path, note_id: str) -> Path:
    """yt-dlp -> mp3 next to the note id. Raises on failure (message is the reason)."""
    import yt_dlp  # type: ignore
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{note_id}.mp3"
    if target.exists() and target.stat().st_size > 10_000:
        return target
    opts = {
        "format": "bestaudio/best", "outtmpl": str(out_dir / f"{note_id}.%(ext)s"),
        "quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "5"}],
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    if not target.exists():
        cands = sorted(out_dir.glob(f"{note_id}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not cands:
            raise RuntimeError("download produced no file")
        target = cands[0]
    return target


def probe_live(url: str) -> tuple[bool, str]:
    """(is_live, title) without downloading. A broadcast that is still running
    would only yield the DVR-so-far; the worker defers until it has ended."""
    import yt_dlp  # type: ignore
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 30}) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next((e for e in info["entries"] if e), info)
    status = str(info.get("live_status") or "")
    live = bool(info.get("is_live")) or status == "is_live"
    return live, str(info.get("title") or "")


def transcribe(path: Path, model_name: str = "small") -> tuple[str, float]:
    from faster_whisper import WhisperModel  # type: ignore
    model = transcribe._models.get(model_name)  # type: ignore[attr-defined]
    if model is None:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        transcribe._models[model_name] = model  # type: ignore[attr-defined]
    segs, info = model.transcribe(str(path), vad_filter=True)
    lines = []
    dur = 0.0
    for s in segs:
        lines.append(f"[{int(s.start) // 60}:{int(s.start) % 60:02d}] {s.text.strip()}")
        dur = max(dur, float(s.end or 0))
    return "\n".join(lines), dur


transcribe._models = {}  # type: ignore[attr-defined]


async def run_once(api: str, headers: dict, media_dir: Path, model_name: str) -> int:
    import httpx
    done = 0
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get(f"{api}/api/technique/ingest/pending", headers=headers)
        if r.status_code != 200:
            print(f"[em-ingest] pending: HTTP {r.status_code} {r.text[:120]}")
            return 0
        try:
            notes = (r.json() or {}).get("notes") or []
        except ValueError:
            # the SPA fallback answers unknown routes with index.html: the app is up
            # but older than this worker (restart it with scripts\start.ps1)
            print("[em-ingest] pending: the app did not answer JSON - is it running the ingestion build? "
                  "(restart with scripts/start.ps1)")
            return 0
        for n in notes:
            nid, url = str(n.get("id")), str(n.get("mediaUrl") or "")
            force = bool(n.get("forcePartial"))
            print(f"[{time.strftime('%H:%M:%S')}] note {nid[:8]}: {url}{' (taking the partial replay)' if force else ''}")
            body: dict = {"noteId": nid}
            try:
                t0 = time.time()
                if not force:
                    live, title = await asyncio.to_thread(probe_live, url)
                    if live:
                        body.update({"deferred": True, "error": f"broadcast still live: {title[:80]}"})
                        print(f"    -> still live ({title[:60]!r}); will check again")
                        raise _Deferred()
                audio = await asyncio.to_thread(download_audio, url, media_dir, nid)
                text, dur = await asyncio.to_thread(transcribe, audio, model_name)
                body.update({"transcript": text, "durationSeconds": round(dur, 1), "model": model_name,
                             "seconds": round(time.time() - t0, 1), "partial": force})
                print(f"    -> {len(text)} chars, {dur / 60:.1f} min of audio, {time.time() - t0:.0f}s")
            except _Deferred:
                pass
            except Exception as exc:  # noqa: BLE001 - reported to the app, which retries/fails it
                body["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                print(f"    -> failed: {body['error']}")
            try:
                pr = await http.post(f"{api}/api/technique/ingest/transcript", headers=headers, json=body, timeout=120)
                st = (pr.json() or {}).get("status") if pr.status_code == 200 else f"HTTP {pr.status_code}"
                print(f"    -> app: {st}")
            except Exception as exc:  # noqa: BLE001
                print(f"    -> could not report to the app: {exc}")
            done += 1
    return done


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("ZARGAR_API", API_DEFAULT))
    p.add_argument("--session", default=os.environ.get("ZARGAR_SESSION", ""))
    p.add_argument("--interval", type=float, default=20.0, help="seconds between polls")
    p.add_argument("--model", default=os.environ.get("ZARGAR_WHISPER_MODEL", "small"))
    p.add_argument("--media-dir", default=os.environ.get("ZARGAR_INGEST_MEDIA", "em_ingest_media"))
    p.add_argument("--once", action="store_true", help="drain pending once and exit")
    a = p.parse_args()
    headers = {"Authorization": f"Bearer {a.session}"} if a.session else {}
    media_dir = Path(a.media_dir)
    print(f"[em-ingest] api={a.api} model={a.model} media={media_dir.resolve()} "
          f"{'(once)' if a.once else f'(every {a.interval:.0f}s)'}")

    async def loop() -> None:
        while True:
            try:
                await run_once(a.api, headers, media_dir, a.model)
            except Exception as exc:  # noqa: BLE001
                print(f"[em-ingest] poll failed: {exc}")
            if a.once:
                return
            await asyncio.sleep(a.interval)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        print("\n[em-ingest] stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
