"""
make_icon.py — generate icon.ico for the .exe.

Deliberately an innocent "document" motif (a page with a folded corner and text
lines on a calm blue), matching the Document Organizer cover story — NOT a lock
or safe, which would draw attention to what the program really does.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
OUT = Path(__file__).resolve().parent / "icon.ico"

BG = (0, 0, 0, 0)
PAGE = (245, 247, 250, 255)
PAGE_EDGE = (205, 212, 222, 255)
FOLD = (219, 225, 233, 255)
BAR = (74, 123, 180, 255)          # a calm blue title bar
LINE = (176, 186, 198, 255)
ACCENT = (46, 158, 79, 255)        # subtle green check (hint of "organized/done")


def _rounded(d, box, r, fill, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def draw(size: int) -> Image.Image:
    s = 4  # supersample for smooth edges
    W = size * s
    img = Image.new("RGBA", (W, W), BG)
    d = ImageDraw.Draw(img)

    m = int(W * 0.16)
    page = [m, int(W * 0.10), W - m, W - int(W * 0.10)]
    fold = int(W * 0.20)

    # page body (with a cut corner) + title bar
    _rounded(d, page, int(W * 0.04), PAGE, PAGE_EDGE, max(1, int(W * 0.006)))
    # folded top-right corner
    x1, y0 = page[2], page[1]
    d.polygon([(x1 - fold, y0), (x1, y0), (x1, y0 + fold)], fill=FOLD)
    d.line([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)],
           fill=PAGE_EDGE, width=max(1, int(W * 0.005)))
    # blue title bar
    bx = [page[0] + int(W * 0.08), page[1] + int(W * 0.10),
          page[2] - int(W * 0.08), page[1] + int(W * 0.185)]
    _rounded(d, bx, int(W * 0.02), BAR)
    # text lines
    lx0 = page[0] + int(W * 0.08)
    lx1 = page[2] - int(W * 0.08)
    ly = page[1] + int(W * 0.26)
    gap = int(W * 0.075)
    for i in range(5):
        x1b = lx1 if i % 3 != 2 else lx1 - int(W * 0.14)
        d.rounded_rectangle([lx0, ly, x1b, ly + int(W * 0.028)],
                            radius=int(W * 0.014), fill=LINE)
        ly += gap
    # small green check bottom-right (organized / done)
    cx, cy, r = page[2] - int(W * 0.14), page[3] - int(W * 0.14), int(W * 0.065)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)
    d.line([(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.4),
            (cx + r * 0.5, cy - r * 0.4)],
           fill=(255, 255, 255, 255), width=max(2, int(W * 0.012)))

    return img.resize((size, size), Image.LANCZOS)


def main():
    base = draw(256)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT, sizes=[(x, x) for x in sizes])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
