"""
pdf_disguise.py — Hide an encrypted file inside an innocent-looking PDF.

Instead of producing an obvious `<name>.enc` blob, this wraps the encrypted
container inside a PDF that displays a pretty "ข้อพระคัมภีร์ประจำวัน" card
(a random verse, nicely typeset with a floral border — see verse_card.py) and
carries the encrypted data as a hidden embedded file. Feeding that PDF back in
extracts the payload and decrypts it to the original file.

This is a disguise for the user's OWN encrypted data (steganographic cover),
not a fabricated record.

Dependencies: PyMuPDF (fitz), Pillow (via verse_card). Reuses file_crypto.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz  # PyMuPDF

import file_crypto
import verse_card

PAYLOAD_NAME = "docorg_payload"
ATTACH_FILENAME = "resource.dat"

# For JPG output: the payload is appended after the image, followed by a trailer
# (marker + payload length). JPEG viewers ignore trailing bytes, so the picture
# shows the verse while the data rides along, recoverable exactly.
JPG_MARKER = b"DOCORGJ1"          # 8 bytes
JPG_TRAILER_LEN = len(JPG_MARKER) + 8

# The embedded payload starts with a 1-byte mode:
#   OFFLINE -> the full encrypted blob follows (actual size inside the file)
#   ONLINE  -> only a tiny JSON pointer follows; the blob lives on Google Drive
MODE_OFFLINE = 0
MODE_ONLINE = 1


def _build_payload(blob: bytes, name_hint: str, online: bool, drive) -> bytes:
    """Offline: mode + blob. Online: upload blob to Drive, keep a small pointer."""
    if not online:
        return bytes([MODE_OFFLINE]) + blob
    if drive is None:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Google Drive — ไม่สามารถเข้ารหัสแบบ Online ได้")
    drive_id = drive.upload_bytes(blob, name_hint + ".dat")
    pointer = json.dumps({"v": 1, "drive_id": drive_id}).encode("utf-8")
    return bytes([MODE_ONLINE]) + pointer


def _resolve_payload(payload: bytes, drive) -> bytes:
    """Return the encrypted blob from a payload, downloading from Drive if online."""
    payload = bytes(payload)
    # Backward compatibility: old files embedded the raw blob with no mode byte.
    if payload[:len(file_crypto.MAGIC)] == file_crypto.MAGIC:
        return payload
    mode, body = payload[0], payload[1:]
    if mode == MODE_OFFLINE:
        return body
    if mode == MODE_ONLINE:
        info = json.loads(body.decode("utf-8"))
        if drive is None:
            raise RuntimeError(
                "ไฟล์นี้เป็นแบบ Online — ต้องตั้งค่า Google Drive ก่อนจึงจะถอดรหัสได้")
        return drive.download_bytes(info["drive_id"])
    raise ValueError("payload mode ไม่รู้จัก (ไฟล์อาจเสียหาย)")


def encrypt_file_to_pdf(src: str | Path, out_dir: str | Path, password: str,
                        online: bool = False, drive=None) -> Path:
    """Encrypt `src` and emit a disguise PDF (<verse>.pdf) in out_dir.
    online=True uploads the blob to Google Drive and embeds only a small pointer.
    The original file is left untouched."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blob = file_crypto.make_blob(src.read_bytes(), src.name, password)

    # The visible PDF is named after the verse (an English Bible abbreviation);
    # the original file name is stored INSIDE the encrypted blob.
    doc, en_ref = verse_card.render_card_doc()  # sharp vector card + file name
    try:
        payload = _build_payload(blob, en_ref, online, drive)
        doc.embfile_add(PAYLOAD_NAME, payload, filename=ATTACH_FILENAME, desc="resource")
        out_path = file_crypto._unique_path(out_dir / (en_ref + ".pdf"))
        doc.save(str(out_path))
    finally:
        doc.close()
    return out_path


def encrypt_file_to_jpg(src: str | Path, out_dir: str | Path, password: str,
                        online: bool = False, drive=None, zoom: float = 3.0) -> Path:
    """Encrypt `src` and emit a disguise JPG (<verse>.jpg) in out_dir: the verse
    card as an image with the payload appended. Original untouched.
    online=True uploads the blob to Drive and appends only a small pointer."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blob = file_crypto.make_blob(src.read_bytes(), src.name, password)

    doc, en_ref = verse_card.render_card_doc()
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        try:
            jpg = pix.tobytes("jpg", jpg_quality=92)
        except TypeError:                       # older PyMuPDF signature
            jpg = pix.tobytes("jpeg")
    finally:
        doc.close()

    payload = _build_payload(blob, en_ref, online, drive)
    out_bytes = jpg + payload + JPG_MARKER + len(payload).to_bytes(8, "big")
    out_path = file_crypto._unique_path(out_dir / (en_ref + ".jpg"))
    out_path.write_bytes(out_bytes)
    return out_path


def is_disguise_jpg(path: str | Path) -> bool:
    """True if this JPG carries our appended encrypted payload."""
    try:
        with open(path, "rb") as f:
            f.seek(-JPG_TRAILER_LEN, 2)
            trailer = f.read(JPG_TRAILER_LEN)
        return trailer[:len(JPG_MARKER)] == JPG_MARKER
    except Exception:
        return False


def decrypt_jpg_to_folder(jpg_path: str | Path, out_dir: str | Path,
                          password: str, drive=None) -> Path:
    """Extract the payload from the disguise JPG and restore the file
    (downloading from Drive first if it is an online pointer)."""
    data = Path(jpg_path).read_bytes()
    if len(data) < JPG_TRAILER_LEN or data[-JPG_TRAILER_LEN:-8] != JPG_MARKER:
        raise ValueError("ไฟล์ JPG นี้ไม่มีข้อมูลที่ซ่อนไว้ (ไม่ใช่ไฟล์ของระบบ)")
    n = int.from_bytes(data[-8:], "big")
    payload = data[-(JPG_TRAILER_LEN + n):-JPG_TRAILER_LEN]

    blob = _resolve_payload(payload, drive)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_name, content = file_crypto.read_blob(blob, password)
    out_path = file_crypto._unique_path(out_dir / original_name)
    out_path.write_bytes(content)
    return out_path


def is_disguise_pdf(path: str | Path) -> bool:
    """True if this PDF carries our hidden encrypted payload."""
    try:
        doc = fitz.open(str(path))
        try:
            return PAYLOAD_NAME in doc.embfile_names()
        finally:
            doc.close()
    except Exception:
        return False


def decrypt_pdf_to_folder(pdf_path: str | Path, out_dir: str | Path,
                          password: str, drive=None) -> Path:
    """Extract the payload from the disguise PDF and restore the file
    (downloading from Drive first if it is an online pointer)."""
    doc = fitz.open(str(pdf_path))
    try:
        if PAYLOAD_NAME not in doc.embfile_names():
            raise ValueError("ไฟล์ PDF นี้ไม่มีข้อมูลที่ซ่อนไว้ (ไม่ใช่ไฟล์ของระบบ)")
        payload = doc.embfile_get(PAYLOAD_NAME)
    finally:
        doc.close()

    blob = _resolve_payload(payload, drive)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_name, data = file_crypto.read_blob(blob, password)
    out_path = file_crypto._unique_path(out_dir / original_name)
    out_path.write_bytes(data)
    return out_path


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = d / "report.txt"
        src.write_bytes("ข้อมูลลับสุดยอด secret payload ".encode() * 40)

        pdf = encrypt_file_to_pdf(src, d / "out", "pw123")
        print("disguise PDF:", pdf.name, "| is ours:", is_disguise_pdf(pdf))
        assert pdf.suffix == ".pdf" and src.exists()

        back = decrypt_pdf_to_folder(pdf, d / "restored", "pw123")
        assert back.read_bytes() == src.read_bytes()

        try:
            decrypt_pdf_to_folder(pdf, d / "restored", "wrong")
            raise SystemExit("SECURITY BUG: wrong password worked")
        except Exception as e:
            assert "InvalidTag" in type(e).__name__ or isinstance(e, Exception)

        print("pdf_disguise self-test OK — encrypt->verse-card PDF, restore, wrong-pw rejected")
