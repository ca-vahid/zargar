"""Post-process gpt-image-2 output for theme-agnostic use.

- Gold-on-black art -> black-to-alpha (screen-style unpremultiply), so the
  gold linework floats over any background.
- Mixed-tone art -> circular feathered medallion keeping its own dark ground.
"""
import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ART = pathlib.Path(r"C:\Cursor\zargar\frontend\public\art")


def black_to_alpha(name: str, out: str, max_size: int | None = None,
                   floor: int = 8) -> None:
    img = Image.open(ART / name).convert("RGB")
    r, g, b = img.split()
    alpha = ImageOps.grayscale(Image.merge("RGB", (r, g, b)))
    # alpha from max channel: keeps gold halos as soft transparency
    px_rgb = img.load()
    out_img = Image.new("RGBA", img.size)
    px_out = out_img.load()
    for y in range(img.height):
        for x in range(img.width):
            pr, pg, pb = px_rgb[x, y]
            a = max(pr, pg, pb)
            if a <= floor:
                px_out[x, y] = (0, 0, 0, 0)
            else:
                scale = 255.0 / a
                px_out[x, y] = (
                    min(255, int(pr * scale)),
                    min(255, int(pg * scale)),
                    min(255, int(pb * scale)),
                    a,
                )
    if max_size:
        out_img.thumbnail((max_size, max_size), Image.LANCZOS)
    out_img.save(ART / out)
    print(f"{out}: {out_img.size}, {(ART / out).stat().st_size // 1024} KB")


def medallion(name: str, out: str, size: int = 512, feather: int = 24) -> None:
    img = Image.open(ART / name).convert("RGBA")
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                    (img.width + side) // 2, (img.height + side) // 2))
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((feather, feather, size - feather, size - feather), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    img.putalpha(mask)
    img.save(ART / out)
    print(f"{out}: {img.size}, {(ART / out).stat().st_size // 1024} KB")


def shrink(name: str, out: str, width: int) -> None:
    img = Image.open(ART / name)
    ratio = width / img.width
    img = img.resize((width, int(img.height * ratio)), Image.LANCZOS)
    img.save(ART / out, quality=88)
    print(f"{out}: {img.size}, {(ART / out).stat().st_size // 1024} KB")


black_to_alpha("logo.png", "logo-mark.png", max_size=512)
black_to_alpha("hero-ornament.png", "hero-ornament-alpha.png", max_size=1024)
black_to_alpha("sidebar-flourish.png", "sidebar-flourish-alpha.png", max_size=512)
medallion("empty-state.png", "empty-medallion.png")
shrink("splash.png", "splash-1600.webp", 1600)

# favicon from the processed mark
fav = Image.open(ART / "logo-mark.png").copy()
fav.thumbnail((64, 64), Image.LANCZOS)
fav.save(ART / "favicon.png")
print("favicon.png saved")
