"""Fetch tweet text + attached images through X's public syndication endpoint (no login).

    python docs/techniques/team2/tools/fetch_tweet_media.py <tweet_id> [<tweet_id> ...] [--tag slug]

For each id: GET https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=a, save the JSON to
notes/x/images/<id>.json, download every photo to notes/x/images/<id>-<n>.jpg (largest size),
and print the tweet date, text and the saved file names. Images are what carry the author's
alert screenshots and chart annotations (contract, trims, zones) — the text never does.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import httpx

HERE = pathlib.Path(__file__).resolve().parent
IMG = HERE.parent / "notes" / "x" / "images"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
      "Accept": "application/json,text/plain,*/*"}


def fetch(tid: str, http: httpx.Client) -> dict | None:
    for token in ("a", "1", "x"):
        r = http.get("https://cdn.syndication.twimg.com/tweet-result", params={"id": tid, "token": token})
        if r.status_code == 200 and r.text.strip().startswith("{"):
            try:
                return r.json()
            except ValueError:
                continue
    return None


def main() -> None:
    ids = [a for a in sys.argv[1:] if a.isdigit()]
    IMG.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as http:
        for tid in ids:
            d = fetch(tid, http)
            if not d:
                print(f"{tid}: not available via syndication")
                continue
            (IMG / f"{tid}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            photos = d.get("photos") or []
            saved = []
            for i, p in enumerate(photos, 1):
                url = p.get("url")
                if not url:
                    continue
                out = IMG / f"{tid}-{i}.jpg"
                if not out.exists():
                    rr = http.get(url, params={"name": "large"})
                    if rr.status_code == 200:
                        out.write_bytes(rr.content)
                    else:
                        print(f"  photo {i}: HTTP {rr.status_code}")
                        continue
                saved.append(out.name)
            video = "video" if (d.get("video") or any(m.get("type") == "video" for m in d.get("mediaDetails") or [])) else ""
            parent = d.get("parent", {}).get("id_str") if isinstance(d.get("parent"), dict) else ""
            print(f"\n=== {tid} {d.get('created_at','')[:16]} {'(reply to '+parent+')' if parent else ''} {video}")
            print(d.get("text", "").strip())
            print("  images:", ", ".join(saved) or "none")
            time.sleep(0.4)


if __name__ == "__main__":
    main()
