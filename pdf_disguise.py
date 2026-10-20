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

from pathlib import Path

import fitz  # PyMuPDF

import file_crypto
import verse_card

PAYLOAD_NAME = "docorg_payload"
ATTACH_FILENAME = "resource.dat"

# For JPG output: the encrypted blob is appended after the image, followed by a
# trailer (marker + blob length). JPEG viewers ignore trailing bytes, so the
# picture shows the verse while the data rides along, recoverable exactly.
JPG_MARKER = b"DOCORGJ1"          # 8 bytes
JPG_TRAILER_LEN = len(JPG_MARKER) + 8


def encrypt_file_to_pdf(src: str | Path, out_dir: str | Path, password: str,
                        bible_pdf=None) -> Path:
    """Encrypt `src` and emit a disguise PDF (<name>.pdf) in out_dir.
    `bible_pdf` is accepted for compatibility but ignored (verses come from
    verse_card). The original file is left untouched."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blob = file_crypto.make_blob(src.read_bytes(), src.name, password)

    # The original file name is stored INSIDE the encrypted payload, so the
    # visible PDF is named after the verse (an English Bible abbreviation).
    doc, en_ref = verse_card.render_card_doc()  # sharp vector card + file name
    try:
        doc.embfile_add(PAYLOAD_NAME, blob, filename=ATTACH_FILENAME, desc="resource")
        out_path = file_crypto._unique_path(out_dir / (en_ref + ".pdf"))
        doc.save(str(out_path))
    finally:
        doc.close()
    return out_path


def encrypt_file_to_jpg(src: str | Path, out_dir: str | Path, password: str,
                        zoom: float = 3.0) -> Path:
    """Encrypt `src` and emit a disguise JPG (<verse>.jpg) in out_dir: the verse
    card as an image with the encrypted payload appended. Original untouched."""
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

    out_bytes = jpg + blob + JPG_MARKER + len(blob).to_bytes(8, "big")
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
                          password: str) -> Path:
    """Extract the hidden payload from the disguise JPG and restore the file."""
    data = Path(jpg_path).read_bytes()
    if len(data) < JPG_TRAILER_LEN or data[-JPG_TRAILER_LEN:-8] != JPG_MARKER:
        raise ValueError("ไฟล์ JPG นี้ไม่มีข้อมูลที่ซ่อนไว้ (ไม่ใช่ไฟล์ของระบบ)")
    n = int.from_bytes(data[-8:], "big")
    blob = data[-(JPG_TRAILER_LEN + n):-JPG_TRAILER_LEN]

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
                          password: str) -> Path:
    """Extract the hidden payload from the disguise PDF and restore the file.
    Raises ValueError if the PDF has no payload, or InvalidTag on wrong password."""
    doc = fitz.open(str(pdf_path))
    try:
        if PAYLOAD_NAME not in doc.embfile_names():
            raise ValueError("ไฟล์ PDF นี้ไม่มีข้อมูลที่ซ่อนไว้ (ไม่ใช่ไฟล์ของระบบ)")
        blob = doc.embfile_get(PAYLOAD_NAME)
    finally:
        doc.close()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_name, data = file_crypto.read_blob(bytes(blob), password)
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
