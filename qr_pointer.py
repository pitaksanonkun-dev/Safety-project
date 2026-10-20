"""
qr_pointer.py — encode a small online pointer as a QR code and read it back.

Apps like LINE recompress images and strip any data appended after the JPEG,
which breaks the trailer-based pointer. A QR code lives in the visible PIXELS,
so it survives recompression. For Online mode we therefore also stamp the
pointer as a QR on the card; decrypting can read it even from a recompressed
copy.

Dependencies: qrcode[pil] (make), opencv-python-headless + numpy (read).
"""

from __future__ import annotations

import io

import cv2
import numpy as np
import qrcode
from PIL import Image

_MAGIC = "DOV1"          # marks our pointer QR


def encode_pointer(drive_id: str, kind: str) -> str:
    return f"{_MAGIC}\t{kind}\t{drive_id}"


def decode_pointer(text: str):
    """Return (drive_id, kind) or None if `text` is not our pointer."""
    if not text or not text.startswith(_MAGIC + "\t"):
        return None
    parts = text.split("\t")
    if len(parts) != 3:
        return None
    _magic, kind, drive_id = parts
    return drive_id, kind


def make_qr_image(data: str, px: int = 300,
                  fill=(35, 32, 28), back=(245, 243, 236),
                  border: int = 2) -> Image.Image:
    """High-error-correction QR sized ~px. Defaults to a dark-grey code on a
    cream background (the card colour) with a small quiet zone, so it blends in
    and shows no stark white box — yet still scans after recompression."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # ~30% recoverable
        box_size=10, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill, back_color=back).convert("RGB")
    return img.resize((px, px), Image.NEAREST)


def read_pointer_from_image_bytes(img_bytes: bytes):
    """Scan an image (PNG/JPG bytes) for our pointer QR; return (drive_id, kind) or None."""
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    detector = cv2.QRCodeDetector()
    # try the whole image, then an upscaled copy (helps on small/recompressed QRs)
    for scale in (1.0, 2.0):
        probe = img if scale == 1.0 else cv2.resize(
            img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            data, _pts, _ = detector.detectAndDecode(probe)
        except cv2.error:
            data = ""
        ptr = decode_pointer(data)
        if ptr:
            return ptr
    return None


if __name__ == "__main__":
    # prove a QR survives LINE-style JPEG recompression
    data = encode_pointer("1AbCdEfGhIjKlMnOpQrStUvWxYz0123456", "jpg")

    # build a "card": grey background with the QR stamped in a corner
    bg = Image.new("RGB", (1040, 1860), (245, 243, 236))
    qr = make_qr_image(data, px=260)
    bg.paste(qr, (1040 - 260 - 40, 1860 - 260 - 40))

    buf = io.BytesIO(); bg.save(buf, "JPEG", quality=92)
    original = buf.getvalue()

    # simulate LINE: decode then re-encode at a lower quality a couple of times
    recompressed = original
    for q in (70, 60):
        im = Image.open(io.BytesIO(recompressed)).convert("RGB")
        im = im.resize((int(im.width * 0.9), int(im.height * 0.9)))
        b = io.BytesIO(); im.save(b, "JPEG", quality=q); recompressed = b.getvalue()

    print("read from original    :", read_pointer_from_image_bytes(original))
    print("read after recompress :", read_pointer_from_image_bytes(recompressed))
