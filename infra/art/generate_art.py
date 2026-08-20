"""Regenerate the transparent assets — flat vector, real alpha, zero glow."""
import base64
import os
import pathlib
import sys

import httpx

KEY = os.environ["OPENAI_API_KEY"]
OUT = pathlib.Path(r"C:\Cursor\zargar\frontend\public\art")

FLAT = (
    "CRITICAL: true transparent alpha background (PNG), absolutely NO background "
    "fill, NO black, NO glow, NO drop shadow, NO vignette — sticker-style flat "
    "vector illustration with clean edges, as if exported from Figma. "
    "Palette: burnished gold #c9a227, warm brass #a8862e, charcoal #2b2b28 line "
    "accents only. Subtle Persian girih geometric influence. No text."
)

ASSETS = [
    {
        "name": "logo.png",
        "size": "1024x1024",
        "quality": "high",
        "prompt": "A square app logo mark: bold minimal monogram letter Z built from "
        "an ascending candlestick chart (the diagonal stroke is a rising series of "
        "small gold candlesticks, top and bottom strokes are solid gold slabs), "
        "flat vector with crisp edges, readable at 32 pixels, centered with 10% "
        "padding. " + FLAT,
    },
    {
        "name": "hero-ornament.png",
        "size": "1536x1024",
        "quality": "medium",
        "prompt": "A decorative line-art ornament: a single-line-weight elegant gold "
        "outline of a bull mid-stride whose back merges into a rising candlestick "
        "chart, with one small girih star flourish near the tail. Thin delicate "
        "lines only, mostly empty space. " + FLAT,
    },
    {
        "name": "empty-state.png",
        "size": "1024x1024",
        "quality": "medium",
        "prompt": "A small friendly spot illustration: an open goldsmith's ledger "
        "book with a tiny brass telescope beside it and a dotted gold chart line "
        "rising off the page. Flat duotone vector (gold + warm gray), soft "
        "rounded shapes, no floor shadow. " + FLAT,
    },
    {
        "name": "sidebar-flourish.png",
        "size": "1024x1536",
        "quality": "medium",
        "prompt": "An extremely subtle vertical corner ornament: faint thin gold "
        "girih arabesque lines rising from the bottom edge and dissolving into "
        "nothing by the middle, like delicate filigree. Very low visual weight, "
        "at most 15% of the canvas covered. " + FLAT,
    },
]


def main() -> int:
    failures = 0
    with httpx.Client(timeout=300) as client:
        for asset in ASSETS:
            target = OUT / asset["name"]
            print(f"generating {asset['name']} ...", flush=True)
            resp = client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {KEY}"},
                json={
                    "model": "gpt-image-2",
                    "prompt": asset["prompt"],
                    "size": asset["size"],
                    "quality": asset["quality"],
                    "background": "transparent",
                    "output_format": "png",
                    "n": 1,
                },
            )
            if resp.status_code != 200:
                print(f"  FAILED {resp.status_code}: {resp.text[:300]}")
                failures += 1
                continue
            b64 = resp.json()["data"][0]["b64_json"]
            target.write_bytes(base64.b64decode(b64))
            print(f"  saved {target} ({target.stat().st_size // 1024} KB)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
