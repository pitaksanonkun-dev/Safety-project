"""
verse_card.py — Build a crisp "ข้อพระคัมภีร์ประจำวัน" card as a PDF page.

Text is drawn as VECTOR text with PyMuPDF (MuPDF shapes Thai correctly — no
broken vowels/tone marks, and it stays sharp at any zoom / print resolution).
The floral border comes from card_template.png (raster), upscaled for clarity.

Verse source note: the supplied Bible PDF (bi7_SI.pdf) embeds a font with no
ToUnicode map, so its text can't be machine-read without OCR (not installed).
Verses therefore come from the curated VERSES pool below — edit freely.

Dependencies: PyMuPDF (fitz), Pillow (only to read/upscale the border image).
"""

from __future__ import annotations

import random
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from pythainlp.tokenize import word_tokenize

_APP_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = _APP_DIR / "card_template.png"

# TH Sarabun (the standard Thai document font) — bundled with the app so the
# characters render cleanly without overlap, regardless of installed fonts.
_FONT_DIR = _APP_DIR / "fonts"
_HEAD_FONT = str(_FONT_DIR / "THSarabun-Bold.ttf")     # heading (bold)
_VERSE_FONT = str(_FONT_DIR / "THSarabun.ttf")         # verse
_REF_FONT = str(_FONT_DIR / "THSarabun.ttf")

# (verse, thai_ref shown on card, english_abbrev used as the PDF file name)
VERSES = [
    ("เพราะว่าพระเจ้าทรงรักโลก จนได้ประทานพระบุตรองค์เดียวของพระองค์ "
     "เพื่อทุกคนที่วางใจในพระบุตรนั้นจะไม่พินาศ แต่มีชีวิตนิรันดร์", "ยอห์น 3:16", "Jhn 3.16"),
    ("พระยาห์เวห์ทรงเลี้ยงดูข้าพเจ้าดุจเลี้ยงแกะ ข้าพเจ้าจะไม่ขัดสน", "สดุดี 23:1", "Psa 23.1"),
    ("จงวางใจในพระยาห์เวห์ด้วยสุดใจของเจ้า และอย่าพึ่งพาความรอบรู้ของตนเอง", "สุภาษิต 3:5", "Pro 3.5"),
    ("เราทำสิ่งทั้งปวงได้โดยพระองค์ผู้ทรงเสริมกำลังข้าพเจ้า", "ฟีลิปปี 4:13", "Php 4.13"),
    ("จงชื่นชมยินดีในองค์พระผู้เป็นเจ้าทุกเวลา ข้าพเจ้าขอย้ำอีกครั้งว่า จงชื่นชมยินดีเถิด",
     "ฟีลิปปี 4:4", "Php 4.4"),
    ("องค์พระผู้เป็นเจ้าทรงเป็นความสว่างและความรอดของข้าพเจ้า ข้าพเจ้าจะกลัวผู้ใดเล่า",
     "สดุดี 27:1", "Psa 27.1"),
    ("จงมอบภาระของเจ้าไว้กับพระยาห์เวห์ และพระองค์จะทรงค้ำจุนเจ้า", "สดุดี 55:22", "Psa 55.22"),
    ("เพราะเรารู้แผนงานที่เรามีไว้สำหรับเจ้า เป็นแผนงานเพื่อสวัสดิภาพ ไม่ใช่เพื่ออันตราย "
     "เพื่อจะให้อนาคตและความหวังแก่เจ้า", "เยเรมีย์ 29:11", "Jer 29.11"),
    ("จงรักองค์พระผู้เป็นเจ้าผู้เป็นพระเจ้าของเจ้าด้วยสุดจิตสุดใจของเจ้า "
     "และด้วยสุดความคิดของเจ้า", "มัทธิว 22:37", "Mat 22.37"),
    ("ความรักนั้นก็อดทนนานและมีใจกรุณา ความรักไม่อิจฉา ไม่อวดตัว ไม่หยิ่งผยอง",
     "1 โครินธ์ 13:4", "1Co 13.4"),
]


def pick_verse() -> tuple[str, str, str]:
    return random.choice(VERSES)


def _wrap(text, font, size, max_w):
    """Wrap Thai text at real WORD boundaries (PyThaiNLP), so no word is split
    across lines. Falls back to char wrapping only for a single word that is
    itself wider than the line (very rare)."""
    def fits(s):
        return font.text_length(s, fontsize=size) <= max_w

    def char_wrap(run):
        out, cur = [], ""
        for ch in run:
            if fits(cur + ch) or not cur:
                cur += ch
            else:
                out.append(cur); cur = ch
        if cur:
            out.append(cur)
        return out

    tokens = word_tokenize(text, engine="newmm", keep_whitespace=True)
    lines, cur = [], ""
    for tok in tokens:
        if not cur:                      # starting a fresh line
            if tok.isspace():
                continue                 # don't begin a line with spaces
            if fits(tok):
                cur = tok
            else:
                parts = char_wrap(tok)
                lines.extend(parts[:-1]); cur = parts[-1]
            continue
        if fits(cur + tok):
            cur += tok
        else:
            lines.append(cur.rstrip())
            if tok.isspace():
                cur = ""
            elif fits(tok):
                cur = tok
            else:
                parts = char_wrap(tok)
                lines.extend(parts[:-1]); cur = parts[-1]
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def _border_png_and_aspect():
    """Return (png_bytes, aspect H/W) of the floral border, kept high-res."""
    img = Image.open(TEMPLATE_PATH).convert("RGB")
    W, H = img.size
    if W < 1200:                      # only upscale small templates
        img = img.resize((1400, round(H * 1400 / W)), Image.LANCZOS)
    buf = BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue(), H / W


def _center(page, text, baseline_y, fontfile, fontname, size, color, page_w):
    f = fitz.Font(fontfile=fontfile)
    w = f.text_length(text, fontsize=size)
    page.insert_text(fitz.Point((page_w - w) / 2, baseline_y), text,
                     fontname=fontname, fontfile=fontfile, fontsize=size,
                     color=color)


def render_card_doc(page_w: float = 520.0) -> tuple[fitz.Document, str]:
    """Return (1-page fitz PDF card, english_abbrev) for a random verse.
    The english abbrev (e.g. 'Jhn 3.16') is meant to be the output file name."""
    verse, ref, en_ref = pick_verse()
    border_png, aspect = _border_png_and_aspect()
    page_h = page_w * aspect

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)

    # floral border (raster) as full-page background; its centre is already a
    # clean cream area, so the text is drawn directly on it (no cover panel).
    page.insert_image(page.rect, stream=border_png)

    # writing column kept inside the gold frame, clear of the florals
    mx = page_w * 0.155
    top_m = page_h * 0.150
    bot_m = page_h * 0.150
    my = bot_m
    inner_w = page_w - 2 * mx

    # heading
    y = top_m
    _center(page, "ข้อพระคัมภีร์ประจำวัน", y, _HEAD_FONT, "HV",
            page_w * 0.044, (0.24, 0.28, 0.38), page_w)
    y += page_w * 0.044 * 1.2
    _center(page, "พระธรรมของพระเจ้า", y, _HEAD_FONT, "HV",
            page_w * 0.032, (0.47, 0.51, 0.59), page_w)

    # verse — auto-fit font size so the whole thing fits uncut
    vfile = _VERSE_FONT
    vfont = fitz.Font(fontfile=vfile)
    body = "\u201c" + verse + "\u201d"
    top = y + page_h * 0.045
    bot = page_h - my - page_h * 0.085           # leave room for the reference
    for size in range(int(page_w * 0.052), 12, -1):
        lines = _wrap(body, vfont, size, inner_w)
        line_h = size * 1.95
        if line_h * len(lines) <= (bot - top):
            break
    block_h = line_h * len(lines)
    vy = top + max(0.0, ((bot - top) - block_h) / 2) + size  # first baseline
    for ln in lines:
        _center(page, ln, vy, vfile, "AG", size, (0.17, 0.19, 0.24), page_w)
        vy += line_h

    # reference
    _center(page, f"\u2014  {ref}", page_h - my - page_h * 0.035,
            _REF_FONT, "HV", page_w * 0.030, (0.43, 0.47, 0.55), page_w)

    return doc, en_ref


if __name__ == "__main__":
    doc, en_ref = render_card_doc()
    doc[0].get_pixmap(matrix=fitz.Matrix(3, 3)).save("_card_preview.png")
    doc.close()
    print("wrote _card_preview.png | file name would be:", en_ref + ".pdf")
