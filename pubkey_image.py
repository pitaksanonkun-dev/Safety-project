"""
pubkey_image.py — export / import an X25519 PUBLIC key as a Bible-and-key PNG.

The exported image is the bundled "Holy Bible + golden key" picture with a random
Thai Bible verse written onto the book cover. It carries the public key three
ways for robustness:

  * a PNG tEXt chunk (clean, no visual artifact)
  * an appended trailer after the PNG stream
  * a small QR in the corner (survives chat-app recompression, e.g. LINE)

A public key is NOT a secret, so this is encoding for easy transfer, not
encryption. Reading tries the tEXt chunk, then the trailer, then the QR, so the
file can be imported into the recipient list to decrypt-to that person.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo
from pythainlp.tokenize import word_tokenize

import app_paths
import file_crypto
import qr_pointer
import recipient_crypto
import verse_card

PNG_TEXT_KEY = "docorg_pk"
PNG_MARKER = b"DOCORGPKIMG1"

TEMPLATE = app_paths.resource_dir() / "bible_key_template.png"
VERSE_FONT = str(app_paths.resource_dir() / "fonts" / "THSarabun-Bold.ttf")

# Verse text box on the book cover, as fractions of the image (tuned to template)
TXT_X, TXT_Y = 0.255, 0.560      # top-left of the text box (lower cover, below key)
TXT_W = 0.430                    # text width
TXT_SIZE = 0.027                 # font size
TXT_GOLD = (0.98, 0.90, 0.62)    # warm gold that reads on the dark leather
TXT_REF = (0.90, 0.82, 0.55)


def _wrap(text: str, font: fitz.Font, size: float, max_w: float) -> list[str]:
    toks = word_tokenize(text or "", engine="newmm", keep_whitespace=True)
    lines, cur = [], ""
    for t in toks:
        if font.text_length(cur + t, fontsize=size) <= max_w or not cur:
            cur += t
        else:
            lines.append(cur.rstrip())
            cur = t.lstrip()
    if cur.strip() or not lines:
        lines.append(cur.rstrip())
    return lines


def _verse_layer(verse, width_px: int, size_px: float) -> Image.Image:
    """Render the Thai verse (correct shaping via fitz) onto a transparent RGBA
    image `width_px` wide."""
    thai = verse[0] if isinstance(verse, (list, tuple)) else str(verse)
    ref = verse[1] if isinstance(verse, (list, tuple)) and len(verse) > 1 else ""
    font = fitz.Font(fontfile=VERSE_FONT)
    lines = _wrap(thai, font, size_px, width_px)
    line_h = size_px * 1.5
    height_px = int(size_px + line_h * len(lines) + (line_h * 1.2 if ref else size_px * 0.4))

    doc = fitz.open()
    page = doc.new_page(width=width_px, height=height_px)   # 1 pt == 1 px here
    page.insert_font(fontname="v", fontfile=VERSE_FONT)
    y = size_px
    for ln in lines:
        w = font.text_length(ln, fontsize=size_px)
        page.insert_text(((width_px - w) / 2, y), ln, fontname="v",
                         fontsize=size_px, color=TXT_GOLD)
        y += line_h
    if ref:
        rtxt = "— " + ref
        rw = font.text_length(rtxt, fontsize=size_px * 0.9)
        page.insert_text(((width_px - rw) / 2, y + line_h * 0.2), rtxt,
                         fontname="v", fontsize=size_px * 0.9, color=TXT_REF)
    pix = page.get_pixmap(alpha=True)
    doc.close()
    return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)


def _compose(public_raw: bytes):
    """Return (PIL RGBA image, fingerprint) — the Bible image + a random verse +
    a small QR carrying the key."""
    enc = recipient_crypto.encode_public(public_raw)
    fp = recipient_crypto.fingerprint(public_raw)
    base = Image.open(TEMPLATE).convert("RGBA")
    W, H = base.size

    verse = verse_card.pick_verse()
    layer = _verse_layer(verse, int(W * TXT_W), W * TXT_SIZE)
    x0, y0 = int(W * TXT_X), int(H * TXT_Y)
    tw, th = layer.size
    # a soft dark plaque behind the verse so the gold text stays readable over
    # the busy leather / key, like an engraved plate on the cover
    pad = int(W * 0.018)
    plaque = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(plaque).rounded_rectangle(
        [0, 0, tw + 2 * pad - 1, th + 2 * pad - 1],
        radius=int(W * 0.018), fill=(18, 14, 10, 155))
    base.alpha_composite(plaque, (x0 - pad, y0 - pad))
    base.alpha_composite(layer, (x0, y0))

    try:    # QR, bottom-right on the transparent corner (reliable contrast)
        q = max(150, round(W * 0.12))
        m = round(W * 0.015)
        qr = qr_pointer.make_qr_image(enc, px=q).convert("RGBA")
        base.alpha_composite(qr, (W - q - m, H - q - m))
    except Exception:
        pass
    return base, fp, enc


def export_png(public_raw: bytes, out_path) -> tuple[Path, str]:
    """Write the Bible-and-key PNG carrying `public_raw`. Returns (path, fp)."""
    img, fp, enc = _compose(public_raw)
    meta = PngInfo()
    meta.add_text(PNG_TEXT_KEY, enc)
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=meta)
    data = buf.getvalue()
    enc_b = enc.encode("utf-8")
    data += PNG_MARKER + len(enc_b).to_bytes(4, "big") + enc_b   # trailer fallback

    out_path = file_crypto._unique_path(Path(out_path))
    out_path.write_bytes(data)
    return out_path, fp


_PK_RE = re.compile(r"DOCORGPK1:[A-Za-z0-9_\-]+")


def _token(text):
    """Pull a DOCORGPK1:... public-key string out of arbitrary text, or None."""
    if not text:
        return None
    m = _PK_RE.search(text)
    return m.group(0) if m else None


def _decode_image(data: bytes):
    """Find the key in an image (PNG/JPG bytes): tEXt chunk, trailer, then QR."""
    # 1) PNG tEXt chunk
    try:
        img = Image.open(io.BytesIO(data))
        enc = (getattr(img, "text", {}) or {}).get(PNG_TEXT_KEY) \
            or (img.info or {}).get(PNG_TEXT_KEY)
        if enc:
            return enc
    except Exception:
        pass
    # 2) appended trailer
    i = data.rfind(PNG_MARKER)
    if i != -1:
        body = data[i + len(PNG_MARKER):]
        if len(body) >= 4:
            n = int.from_bytes(body[:4], "big")
            enc = body[4:4 + n].decode("utf-8", "ignore")
            if _token(enc):
                return _token(enc)
    # 3) QR (survives chat recompression)
    try:
        return _token(qr_pointer.read_text_from_image_bytes(data))
    except Exception:
        return None


def _decode_pdf(data: bytes):
    """Find the key in a PDF: metadata, embedded files, then page-rendered QR."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        md = doc.metadata or {}
        for field in ("keywords", "subject", "title"):
            tok = _token(md.get(field))
            if tok:
                return tok
        try:
            for name in doc.embfile_names():
                tok = _token(bytes(doc.embfile_get(name)).decode("utf-8", "ignore"))
                if tok:
                    return tok
        except Exception:
            pass
        for pno in range(min(doc.page_count, 3)):
            png = doc[pno].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
            tok = _token(qr_pointer.read_text_from_image_bytes(png))
            if tok:
                return tok
    finally:
        doc.close()
    return None


def read_pubkey(path) -> bytes:
    """Return the embedded public_raw bytes from a PNG/JPG OR PDF, or raise."""
    data = Path(path).read_bytes()
    is_pdf = str(path).lower().endswith(".pdf") or data[:5] == b"%PDF-"
    enc = _decode_pdf(data) if is_pdf else _decode_image(data)
    if not enc:                      # cross-try in case the extension was wrong
        enc = _decode_image(data) if is_pdf else _decode_pdf(data)
    if not enc:
        raise ValueError("ไม่พบ public key ในไฟล์นี้ (อาจไม่ใช่ไฟล์กุญแจของระบบ)")
    return recipient_crypto.decode_public(enc)        # validates + returns raw


read_png = read_pubkey            # backward-compatible alias


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    priv, pub = recipient_crypto.generate_keypair()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_pubkey_sample.png")
    p, fp = export_png(pub, out)
    assert read_png(p) == pub, "round-trip mismatch (tEXt/trailer)"
    # QR-only fallback after a JPEG recompress that strips metadata+trailer
    jp = p.with_suffix(".jpg")
    Image.open(p).convert("RGB").save(jp, "JPEG", quality=80)
    assert read_png(jp) == pub, "QR fallback failed"
    print("pubkey_image OK  fp=", fp, " ->", p)
