"""Download a public video's audio and transcribe it into notes/video/<id>-<slug>.md.

Reuses the EM ingestion helpers (yt-dlp + faster-whisper, CPU). Run from backend/ with the
ingest venv:

    cd backend
    .venv-ingest/Scripts/python.exe ../docs/techniques/team2/tools/transcribe_video.py \
        https://www.youtube.com/watch?v=xm8pWnaAZU4 [more urls] [--model small]

Audio lands in notes/video/media/ (gitignored); the transcript is Markdown with [m:ss]
timestamps and a frontmatter block (url, title, uploader, upload date, duration, model).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTES = HERE.parent / "notes" / "video"
MEDIA = NOTES / "media"
BACKEND = HERE.parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from zargar.tools.em_ingest import download_audio, transcribe  # noqa: E402


def info(url: str) -> dict:
    import yt_dlp  # type: ignore
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 30}) as ydl:
        return ydl.extract_info(url, download=False) or {}


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:60]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--model", default=os.environ.get("ZARGAR_WHISPER_MODEL", "small"))
    a = ap.parse_args()
    NOTES.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    gi = MEDIA / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n!.gitignore\n", encoding="utf-8")
    for url in a.urls:
        t0 = time.time()
        meta = info(url)
        vid = str(meta.get("id") or re.sub(r"\W", "", url)[-11:])
        title = str(meta.get("title") or vid)
        print(f"[{vid}] {title!r} — downloading", flush=True)
        audio = download_audio(url, MEDIA, vid)
        print(f"[{vid}] audio {audio.stat().st_size / 1e6:.1f} MB — transcribing with {a.model} (CPU)", flush=True)
        text, dur = transcribe(audio, a.model)
        up = str(meta.get("upload_date") or "")
        up_iso = f"{up[:4]}-{up[4:6]}-{up[6:]}" if len(up) == 8 else up
        fm = (
            "---\n"
            f"source: {url}\n"
            f"title: {title}\n"
            f"uploader: {meta.get('uploader') or meta.get('channel') or ''}\n"
            f"uploaded: {up_iso}\n"
            f"duration_min: {dur / 60:.1f}\n"
            f"kind: video transcript (auto, faster-whisper {a.model}, CPU; names/tickers may be misheard)\n"
            f"captured: {dt.date.today().isoformat()}\n"
            "---\n\n"
            f"# {title}\n\n"
            f"{(meta.get('description') or '').strip()}\n\n---\n\n"
        )
        out = NOTES / f"{up_iso or 'undated'}-{vid}-{slugify(title)}.md"
        out.write_text(fm + text + "\n", encoding="utf-8")
        print(f"[{vid}] wrote {out.name}: {len(text)} chars, {dur / 60:.1f} min, {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
