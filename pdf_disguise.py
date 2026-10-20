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

import io
import json
from pathlib import Path

import fitz  # PyMuPDF

import file_crypto
import verse_card
import qr_pointer

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


def _pdf_bytes_from_payload(payload: bytes, qr_data: str | None = None,
                            verse=None) -> tuple[bytes, str]:
    """Render a verse-card PDF with `payload` embedded; return (bytes, verse_name).
    If qr_data is given, also stamp a QR (survives if the PDF is turned into an
    image, e.g. shared through a chat app). Pass `verse` to pin a specific verse."""
    doc, en_ref = verse_card.render_card_doc(verse=verse)
    try:
        if qr_data:
            page = doc[0]
            png = _qr_png(qr_data)
            w = page.rect.width
            s = w * 0.17
            page.insert_image(fitz.Rect(w - s - 12, 12, w - 12, 12 + s), stream=png)
        doc.embfile_add(PAYLOAD_NAME, payload, filename=ATTACH_FILENAME, desc="resource")
        return doc.tobytes(deflate=True), en_ref
    finally:
        doc.close()


def _qr_png(data: str) -> bytes:
    buf = io.BytesIO()
    qr_pointer.make_qr_image(data, px=360).save(buf, "PNG")
    return buf.getvalue()


def _jpg_bytes_from_payload(payload: bytes, qr_data: str | None = None,
                            verse=None, zoom: float = 3.0) -> tuple[bytes, str]:
    """Render a verse-card JPG with `payload` appended; return (bytes, verse_name).
    If qr_data is given, stamp a QR onto the image so the pointer survives chat-app
    recompression (which strips the appended trailer). Pass `verse` to pin one."""
    from PIL import Image
    doc, en_ref = verse_card.render_card_doc(verse=verse)
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()

    if qr_data:
        q = round(pix.width * 0.17)
        qr = qr_pointer.make_qr_image(qr_data, px=q)
        img.paste(qr, (pix.width - q - 12, 12))

    buf = io.BytesIO(); img.save(buf, "JPEG", quality=92)
    jpg = buf.getvalue()
    return jpg + payload + JPG_MARKER + len(payload).to_bytes(8, "big"), en_ref


def _extract_payload_from_bytes(data: bytes, kind: str) -> bytes:
    """Pull the embedded payload out of a disguise file given as raw bytes."""
    data = bytes(data)
    if kind == "jpg":
        if len(data) < JPG_TRAILER_LEN or data[-JPG_TRAILER_LEN:-8] != JPG_MARKER:
            raise ValueError("ไฟล์ JPG บน Google Drive ไม่ถูกต้อง")
        n = int.from_bytes(data[-8:], "big")
        return data[-(JPG_TRAILER_LEN + n):-JPG_TRAILER_LEN]
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if PAYLOAD_NAME not in doc.embfile_names():
            raise ValueError("ไฟล์ PDF บน Google Drive ไม่มีข้อมูลที่ซ่อนไว้")
        return bytes(doc.embfile_get(PAYLOAD_NAME))
    finally:
        doc.close()


def _resolve_payload(payload: bytes, drive) -> tuple[bytes, str | None]:
    """Return (encrypted_blob, online_drive_id_or_None). An online pointer is
    fetched from Drive via a PUBLIC download (no credentials needed), so anyone
    with the file — even a different Gmail — can decrypt it."""
    payload = bytes(payload)
    # Backward compatibility: old files embedded the raw blob with no mode byte.
    if payload[:len(file_crypto.MAGIC)] == file_crypto.MAGIC:
        return payload, None
    mode, body = payload[0], payload[1:]
    if mode == MODE_OFFLINE:
        return body, None
    if mode == MODE_ONLINE:
        info = json.loads(body.decode("utf-8"))
        drive_id = info["drive_id"]
        try:
            from drive_client import public_download_bytes
            full = public_download_bytes(drive_id)             # no auth needed
        except Exception as exc:
            raise RuntimeError(
                "ดาวน์โหลดไฟล์จาก Google Drive ไม่ได้ (ไฟล์อาจถูกลบไปแล้ว "
                f"หรือไม่ได้แชร์แบบสาธารณะ)\nรายละเอียด: {exc}")
        inner = _extract_payload_from_bytes(full, info.get("kind", "pdf"))
        blob, _ = _resolve_payload(inner, drive)               # inner is offline
        return blob, drive_id
    raise ValueError("payload mode ไม่รู้จัก (ไฟล์อาจเสียหาย)")


def _encrypt_file(src, out_dir, password, online, drive, kind: str) -> Path:
    """Shared encrypt path for kind in {'pdf','jpg'}.
    Offline: the disguise file holds the full data.
    Online: the FULL disguise PDF/JPG is uploaded to Drive; the LOCAL file is a
    small pointer PDF/JPG of the same kind that redirects to it."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    make_bytes = _jpg_bytes_from_payload if kind == "jpg" else _pdf_bytes_from_payload
    suffix = "." + kind
    mime = "image/jpeg" if kind == "jpg" else "application/pdf"

    blob = file_crypto.make_blob(src.read_bytes(), src.name, password)
    offline_payload = bytes([MODE_OFFLINE]) + blob

    if not online:
        out_bytes, en_ref = make_bytes(offline_payload)
    else:
        if drive is None:
            raise RuntimeError("ยังไม่ได้ตั้งค่า Google Drive — เข้ารหัสแบบ Online ไม่ได้")
        # pin ONE verse so the Drive file and the local pointer show the same card
        chosen = verse_card.pick_verse()
        # full disguise file (same chosen format) goes to Drive — openable, data inside
        full_bytes, en_full = make_bytes(offline_payload, verse=chosen)
        drive_id = drive.upload_bytes(full_bytes, en_full + suffix, mime=mime)
        # share 'anyone with the link' so another person/Gmail can also decrypt
        try:
            drive.make_public(drive_id)
        except Exception:
            pass
        pointer = bytes([MODE_ONLINE]) + json.dumps(
            {"v": 1, "drive_id": drive_id, "kind": kind}).encode("utf-8")
        # the local pointer also carries the pointer as a QR, so it still works
        # after a chat app recompresses the image and strips the trailer
        qr_data = qr_pointer.encode_pointer(drive_id, kind)
        out_bytes, en_ref = make_bytes(pointer, qr_data=qr_data, verse=chosen)

    out_path = file_crypto._unique_path(out_dir / (en_ref + suffix))
    out_path.write_bytes(out_bytes)
    return out_path


def encrypt_file_to_pdf(src: str | Path, out_dir: str | Path, password: str,
                        online: bool = False, drive=None) -> Path:
    """Encrypt `src` to a disguise PDF. Online: upload a full PDF to Drive and
    keep a small pointer PDF locally. The original file is left untouched."""
    return _encrypt_file(src, out_dir, password, online, drive, "pdf")


def encrypt_file_to_jpg(src: str | Path, out_dir: str | Path, password: str,
                        online: bool = False, drive=None, zoom: float = 3.0) -> Path:
    """Encrypt `src` to a disguise JPG. Online: upload a full JPG to Drive and
    keep a small pointer JPG locally. The original file is left untouched."""
    return _encrypt_file(src, out_dir, password, online, drive, "jpg")


def is_disguise_jpg(path: str | Path) -> bool:
    """True if this JPG carries our appended encrypted payload."""
    try:
        with open(path, "rb") as f:
            f.seek(-JPG_TRAILER_LEN, 2)
            trailer = f.read(JPG_TRAILER_LEN)
        return trailer[:len(JPG_MARKER)] == JPG_MARKER
    except Exception:
        return False


def _online_pointer_payload(drive_id: str, kind: str) -> bytes:
    return bytes([MODE_ONLINE]) + json.dumps(
        {"v": 1, "drive_id": drive_id, "kind": kind}).encode("utf-8")


def _maybe_delete(drive_id, drive) -> None:
    """Delete the online Drive file after a successful decrypt (owner only;
    a recipient with a different Gmail simply can't, which is fine)."""
    if drive_id and drive is not None:
        try:
            drive.delete_file(drive_id)
        except Exception:
            pass


def decrypt_jpg_to_folder(jpg_path: str | Path, out_dir: str | Path,
                          password: str, drive=None) -> Path:
    """Restore the original file from a disguise JPG. Reads the appended pointer,
    or — if a chat app stripped it — the QR stamped on the image. Online files
    are downloaded from Drive and then deleted there."""
    data = Path(jpg_path).read_bytes()
    if len(data) >= JPG_TRAILER_LEN and data[-JPG_TRAILER_LEN:-8] == JPG_MARKER:
        n = int.from_bytes(data[-8:], "big")
        payload = data[-(JPG_TRAILER_LEN + n):-JPG_TRAILER_LEN]
    else:
        ptr = qr_pointer.read_pointer_from_image_bytes(data)   # survives recompression
        if not ptr:
            raise ValueError("ไฟล์ JPG นี้ไม่มีข้อมูลที่ซ่อนไว้ หรือถูกแก้ไขจนอ่านไม่ได้")
        payload = _online_pointer_payload(*ptr)

    blob, used_drive_id = _resolve_payload(payload, drive)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_name, content = file_crypto.read_blob(blob, password)
    out_path = file_crypto._unique_path(out_dir / original_name)
    out_path.write_bytes(content)
    _maybe_delete(used_drive_id, drive)
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
        if PAYLOAD_NAME in doc.embfile_names():
            payload = bytes(doc.embfile_get(PAYLOAD_NAME))
        else:
            # embedded file stripped (e.g. PDF flattened to an image) -> read QR
            png = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
            ptr = qr_pointer.read_pointer_from_image_bytes(png)
            if not ptr:
                raise ValueError("ไฟล์ PDF นี้ไม่มีข้อมูลที่ซ่อนไว้ (ไม่ใช่ไฟล์ของระบบ)")
            payload = _online_pointer_payload(*ptr)
    finally:
        doc.close()

    blob, used_drive_id = _resolve_payload(payload, drive)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_name, data = file_crypto.read_blob(blob, password)
    out_path = file_crypto._unique_path(out_dir / original_name)
    out_path.write_bytes(data)
    _maybe_delete(used_drive_id, drive)
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
