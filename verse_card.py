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

import app_paths
_APP_DIR = app_paths.resource_dir()          # bundled assets (works as .py or .exe)
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


def _border_bytes_and_aspect():
    """Return (jpeg_bytes, aspect H/W) of the floral border. JPEG keeps the
    embedded image small (the watercolour compresses well) so the card PDF stays
    well under 1 MB; the verse text is vector and stays sharp regardless."""
    img = Image.open(TEMPLATE_PATH).convert("RGB")
    W, H = img.size
    target = 1200                     # smaller border image -> ~half file size
    if W != target:
        img = img.resize((target, round(H * target / W)), Image.LANCZOS)
    buf = BytesIO(); img.save(buf, format="JPEG", quality=78)
    return buf.getvalue(), H / W


def _center(page, text, baseline_y, fontfile, fontname, size, color, page_w):
    f = fitz.Font(fontfile=fontfile)
    w = f.text_length(text, fontsize=size)
    page.insert_text(fitz.Point((page_w - w) / 2, baseline_y), text,
                     fontname=fontname, fontfile=fontfile, fontsize=size,
                     color=color)


def render_card_doc(page_w: float = 520.0,
                    verse: tuple[str, str, str] | None = None
                    ) -> tuple[fitz.Document, str]:
    """Return (1-page fitz PDF card, english_abbrev). Pass `verse` (a VERSES
    tuple) to force a specific verse — used so the Online pointer shows the SAME
    verse as the file uploaded to Drive. Otherwise a random verse is chosen."""
    verse_txt, ref, en_ref = verse if verse is not None else pick_verse()
    border_png, aspect = _border_bytes_and_aspect()
    page_h = page_w * aspect

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)

    # floral border (raster) as full-page background; its centre is already a
    # clean cream area, so the text is drawn directly on it (no cover panel).
    page.insert_image(page.rect, stream=border_png)

    # writing column kept inside the gold frame, clear of the florals
    mx = page_w * 0.125
    top_m = page_h * 0.135
    bot_m = page_h * 0.135
    my = bot_m
    inner_w = page_w - 2 * mx

    # heading (larger)
    y = top_m
    _center(page, "ข้อพระคัมภีร์ประจำวัน", y, _HEAD_FONT, "HV",
            page_w * 0.052, (0.24, 0.28, 0.38), page_w)
    y += page_w * 0.052 * 1.25
    _center(page, "พระธรรมของพระเจ้า", y, _HEAD_FONT, "HV",
            page_w * 0.038, (0.47, 0.51, 0.59), page_w)

    # verse — auto-fit font size so the whole thing fits uncut
    vfile = _VERSE_FONT
    vfont = fitz.Font(fontfile=vfile)
    top = y + page_h * 0.05
    bot = page_h - my - page_h * 0.075           # leave room for the reference
    size = int(page_w * 0.072)
    while size >= 16:
        # wrap the plain verse (slightly narrower to leave room for the quotes),
        # so the quotation marks never land on a line by themselves
        lines = _wrap(verse_txt, vfont, size, inner_w - size)
        line_h = size * 1.9
        if line_h * len(lines) <= (bot - top):
            break
        size -= 1
    if lines:
        lines[0] = "\u201c" + lines[0]
        lines[-1] = lines[-1] + "\u201d"
    block_h = line_h * len(lines)
    vy = top + max(0.0, ((bot - top) - block_h) / 2) + size  # first baseline
    for ln in lines:
        _center(page, ln, vy, vfile, "AG", size, (0.17, 0.19, 0.24), page_w)
        vy += line_h

    # reference \u2014 which verse it is (bigger), nudged up to clear the florals
    _center(page, f"\u2014  {ref}", page_h - my - page_h * 0.05,
            _REF_FONT, "HV", page_w * 0.050, (0.33, 0.37, 0.46), page_w)

    return doc, en_ref


if __name__ == "__main__":
    doc, en_ref = render_card_doc()
    doc[0].get_pixmap(matrix=fitz.Matrix(3, 3)).save("_card_preview.png")
    doc.close()
    print("wrote _card_preview.png | file name would be:", en_ref + ".pdf")
