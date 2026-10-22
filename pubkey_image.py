"""
pubkey_image.py — export / import an X25519 PUBLIC key as a devotional-looking PNG.

The PNG shows a random Thai Bible-verse card (the same innocuous disguise used
elsewhere) and carries the public key three ways for robustness:

  * a PNG tEXt chunk (clean, no visual artifact)
  * an appended trailer after the PNG stream
  * a small QR in the corner (survives chat-app recompression, e.g. LINE)

A public key is NOT a secret, so this is encoding for easy transfer, not
encryption. Reading tries the tEXt chunk, then the trailer, then the QR.
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import file_crypto
import qr_pointer
import recipient_crypto
import verse_card

PNG_TEXT_KEY = "docorg_pk"
PNG_MARKER = b"DOCORGPKIMG1"


def _card_png(verse=None, zoom: float = 3.0):
    doc, en_ref = verse_card.render_card_doc(verse=verse)
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    return img, en_ref


def export_png(public_raw: bytes, out_path) -> tuple[Path, str]:
    """Render a random-verse card PNG carrying `public_raw`. Returns (path, fp)."""
    enc = recipient_crypto.encode_public(public_raw)
    fp = recipient_crypto.fingerprint(public_raw)
    verse = verse_card.pick_verse()
    img, _en_ref = _card_png(verse=verse)

    # small QR bottom-right so the key survives recompression (e.g. LINE)
    try:
        q = max(130, round(img.width * 0.09))
        m = round(img.width * 0.02)
        qr = qr_pointer.make_qr_image(enc, px=q)
        img.paste(qr, (img.width - q - m, img.height - q - m))
    except Exception:
        pass

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


def read_png(path) -> bytes:
    """Return the embedded public_raw bytes, or raise ValueError if none/invalid."""
    data = Path(path).read_bytes()
    enc = None

    # 1) PNG tEXt chunk
    try:
        img = Image.open(io.BytesIO(data))
        enc = (getattr(img, "text", {}) or {}).get(PNG_TEXT_KEY) \
            or (img.info or {}).get(PNG_TEXT_KEY)
    except Exception:
        enc = None

    # 2) appended trailer
    if not enc:
        i = data.rfind(PNG_MARKER)
        if i != -1:
            body = data[i + len(PNG_MARKER):]
            if len(body) >= 4:
                n = int.from_bytes(body[:4], "big")
                enc = body[4:4 + n].decode("utf-8", "ignore")

    # 3) QR (survives chat recompression)
    if not enc:
        try:
            enc = qr_pointer.read_text_from_image_bytes(data)
        except Exception:
            enc = None

    if not enc:
        raise ValueError("ไม่พบ public key ในไฟล์นี้ (อาจไม่ใช่ไฟล์กุญแจของระบบ)")
    return recipient_crypto.decode_public(enc)        # validates + returns raw


if __name__ == "__main__":
    import tempfile
    priv, pub = recipient_crypto.generate_keypair()
    with tempfile.TemporaryDirectory() as d:
        p, fp = export_png(pub, Path(d) / "verse.png")
        assert p.exists() and p.suffix == ".png"
        got = read_png(p)
        assert got == pub, "round-trip mismatch"
        # simulate metadata stripping: re-save without the tEXt chunk/trailer
        stripped = Image.open(p).convert("RGB")
        sp = Path(d) / "stripped.jpg"
        stripped.save(sp, "JPEG", quality=80)
        got2 = read_png(sp)        # must still read via the QR
        assert got2 == pub, "QR fallback failed"
        print("pubkey_image self-test OK  fp=", fp)
