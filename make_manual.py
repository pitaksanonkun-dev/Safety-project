"""
make_manual.py — append an addendum (recipient-key mode + the standalone .exe)
to the existing user manual, rendered as crisp Thai vector text.

It reads  คู่มือการใช้งาน-Document-Organizer.pdf, adds the new pages, and writes
คู่มือการใช้งาน-Document-Organizer.pdf back (the original is backed up first).

Thai text is wrapped on real word boundaries with PyThaiNLP and drawn with the
bundled TH Sarabun font, the same approach as the verse card.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows console may be cp1252
except Exception:
    pass

import fitz  # PyMuPDF
from pythainlp.tokenize import word_tokenize

import app_paths

HERE = Path(__file__).resolve().parent
FONT_DIR = app_paths.resource_dir() / "fonts"
F_REG = str(FONT_DIR / "THSarabun.ttf")
F_BOLD = str(FONT_DIR / "THSarabun-Bold.ttf")

MANUAL = HERE / "คู่มือการใช้งาน-Document-Organizer.pdf"

PAGE_W, PAGE_H = 595, 842           # A4 in points
MARGIN = 54
INK = (0.12, 0.14, 0.18)
BLUE = (0.18, 0.36, 0.60)
GREEN = (0.16, 0.52, 0.30)
GREY = (0.42, 0.46, 0.52)

# content: ("h1"|"h2"|"body"|"bullet"|"note"|"space", text)
CONTENT = [
    ("h1", "ภาคผนวก (ปรับปรุง 2026-10-21)"),
    ("h2", "1. โหมดส่งไฟล์แบบ “ถึงผู้รับ” (recipient-key) — ผู้รับไม่ต้องพิมพ์รหัสผ่าน"),
    ("body", "ที่หน้าหลักจะมีปุ่มเลือก “วิธีเข้ารหัส / Encrypt with” สองแบบ:"),
    ("bullet", "รหัสผ่าน (password): โหมดเดิม ผู้ถอดต้องพิมพ์รหัสผ่านเดียวกับที่ผู้ส่งตั้งไว้"),
    ("bullet", "ถึงผู้รับ (recipient-key): เข้ารหัสถึงบุคคลเจาะจง ผู้รับถอดได้โดยไม่ต้องพิมพ์รหัสผ่านใด ๆ"),
    ("space", ""),
    ("h2", "ขั้นตอนตั้งค่าครั้งแรก (ทำครั้งเดียวต่อผู้รับ 1 คน)"),
    ("bullet", "ฝั่งผู้รับ: เปิดโปรแกรม > login > เมนู ตั้งค่า > “กุญแจสาธารณะของฉัน” > กดคัดลอก แล้วส่งข้อความ DOCORGPK1:... ให้ผู้ส่ง (ส่งผ่าน LINE ได้ ไม่เป็นความลับ)"),
    ("bullet", "ฝั่งผู้ส่ง: เมนู ตั้งค่า > “รายชื่อผู้รับ (Contacts)” > วาง public key ที่ได้รับ + ตั้งชื่อ > กดเพิ่มผู้รับ"),
    ("space", ""),
    ("h2", "การใช้งานประจำวัน"),
    ("bullet", "ผู้ส่ง: เลือกวิธีเข้ารหัสเป็น “ถึงผู้รับ” > กดเข้ารหัสไฟล์ > เลือกผู้รับ > ได้ไฟล์ PDF/JPG ส่งให้เขา"),
    ("bullet", "ผู้รับ: เปิดไฟล์ที่ได้ > กดถอดรหัสไฟล์ > ไม่ต้องพิมพ์รหัสผ่าน (โปรแกรมใช้ private key ของผู้รับที่ปลดล็อกตอน login โดยอัตโนมัติ)"),
    ("space", ""),
    ("h2", "ทำไมปลอดภัย"),
    ("bullet", "สิ่งที่ฝังไปในไฟล์คือ public key ซึ่งไม่เป็นความลับ ส่วน private key อยู่ในเครื่องผู้รับเท่านั้น ไม่เคยเดินทางไปกับไฟล์"),
    ("bullet", "ถ้าไฟล์หลุดหรือถูกดักระหว่างทาง ผู้อื่นก็ถอดไม่ได้ เพราะไม่มี private key ของผู้รับ"),
    ("bullet", "รหัสผ่านตอน login ยังจำเป็นเสมอ เพราะเป็นตัวปกป้อง private key ของคุณเองไม่ให้ผู้ที่ขโมย vault ไปใช้สวมรอยได้"),
    ("note", "สรุป: ห้ามฝังรหัสผ่านไปในไฟล์เด็ดขาด เพราะจะทำให้ใครได้ไฟล์ก็ถอดได้ = ยกเลิกการเข้ารหัสทั้งหมด โหมด recipient-key จึงเป็นวิธีที่ถูกต้องสำหรับ “ไม่ต้องพิมพ์รหัส”"),

    ("h1", "2. ไฟล์โปรแกรมแบบ .exe และการแจกจ่าย (portable)"),
    ("body", "โปรแกรมสามารถ build เป็นไฟล์ Document Organizer.exe ไฟล์เดียว ที่รันได้โดยเครื่องปลายทางไม่ต้องติดตั้ง Python"),
    ("h2", "ตำแหน่งเก็บข้อมูล (สำคัญมาก)"),
    ("bullet", "vault_store, app_settings.json และ token จะถูกสร้างในโฟลเดอร์เดียวกับไฟล์ .exe เสมอ"),
    ("bullet", "ควรวาง .exe ไว้ในโฟลเดอร์ของมันเอง และถ้าจะย้าย ให้ย้ายทั้งโฟลเดอร์ (ไม่งั้นที่ใหม่จะเริ่ม vault เปล่า)"),
    ("bullet", "Windows SmartScreen/Antivirus อาจเตือนเพราะ .exe ไม่ได้เซ็นลายเซ็นดิจิทัล เป็นเรื่องปกติ ให้กด More info > Run anyway"),
    ("space", ""),
    ("h2", "ปุ่ม “สร้างชุดแจกจ่าย” (Export portable copy)"),
    ("bullet", "เมนู ตั้งค่า > สร้างชุดแจกจ่ายสำหรับเครื่องอื่น > เลือกโฟลเดอร์ปลายทาง > โปรแกรมทำให้เสร็จทันที"),
    ("bullet", "ถ้าเป็น .exe: จะคัดลอกไฟล์ .exe ไปไว้ให้พร้อมส่ง (ส่งไฟล์ .exe นั้นไปเครื่องอื่นได้เลย)"),
    ("bullet", "ถ้าเป็นชุดโค้ด .py: จะได้โฟลเดอร์ + ไฟล์ .zip (เครื่องปลายทางต้องมี Python; launcher ติดตั้งไลบรารีให้เอง)"),
    ("bullet", "ทั้งสองแบบจะไม่รวม vault_store/บัญชี/การตั้งค่าของคุณ เครื่องปลายทางจะสร้าง vault และกุญแจของตัวเองใหม่ เป็นอิสระ"),
    ("space", ""),
    ("h2", "การ build .exe ใหม่ (สำหรับผู้ดูแล)"),
    ("bullet", "ดับเบิลคลิก build_exe.bat หรือรัน: python -m PyInstaller build_exe.spec"),
    ("bullet", "ผลลัพธ์อยู่ในโฟลเดอร์ dist\\ ชื่อ Document Organizer.exe"),
    ("note", "อย่าคัดลอกโฟลเดอร์ vault_store ของคุณไปเครื่องอื่น ให้แต่ละเครื่องสร้าง vault ของตัวเอง เพื่อให้กุญแจไม่ซ้ำกันและปลอดภัยสูงสุด"),
]

STYLE = {
    "h1":    dict(font=F_BOLD, size=19, color=BLUE,  before=16, after=8, lh=1.35),
    "h2":    dict(font=F_BOLD, size=15, color=INK,   before=11, after=5, lh=1.35),
    "body":  dict(font=F_REG,  size=14, color=INK,   before=2,  after=3, lh=1.4),
    "bullet":dict(font=F_REG,  size=14, color=INK,   before=1,  after=2, lh=1.4),
    "note":  dict(font=F_REG,  size=13, color=GREEN, before=6,  after=6, lh=1.4),
    "space": dict(font=F_REG,  size=7,  color=INK,   before=0,  after=0, lh=1.0),
}


def _wrap(text: str, font: fitz.Font, size: float, max_w: float) -> list[str]:
    if not text:
        return [""]
    tokens = word_tokenize(text, engine="newmm", keep_whitespace=True)
    lines, cur = [], ""
    for tok in tokens:
        trial = cur + tok
        if font.text_length(trial, fontsize=size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip())
            cur = tok.lstrip()
    if cur.strip() or not lines:
        lines.append(cur.rstrip())
    return lines


class Flow:
    def __init__(self, doc):
        self.doc = doc
        self.fonts = {F_REG: fitz.Font(fontfile=F_REG),
                      F_BOLD: fitz.Font(fontfile=F_BOLD)}
        self._new_page()

    def _new_page(self):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page.insert_font(fontname="reg", fontfile=F_REG)
        self.page.insert_font(fontname="bold", fontfile=F_BOLD)
        self.y = MARGIN

    def _draw_line(self, s, fontname, font, size, color, x):
        if self.y + size * 1.4 > PAGE_H - MARGIN:
            self._new_page()
        self.page.insert_text((x, self.y + size), s, fontname=fontname,
                              fontsize=size, color=color)
        self.y += size * 1.0

    def add(self, kind, text):
        st = STYLE[kind]
        fname = "bold" if st["font"] == F_BOLD else "reg"
        font = self.fonts[st["font"]]
        size, lh = st["size"], st["lh"]
        self.y += st["before"]
        bullet = kind == "bullet"
        x = MARGIN + (16 if bullet else 0)
        avail = PAGE_W - MARGIN - x
        lines = _wrap(text, font, size, avail)
        for i, ln in enumerate(lines):
            if bullet and i == 0:
                self.page.insert_text((MARGIN, self.y + size), "•",
                                      fontname="reg", fontsize=size, color=BLUE)
            if self.y + size * lh > PAGE_H - MARGIN:
                self._new_page()
            self.page.insert_text((x, self.y + size), ln, fontname=fname,
                                  fontsize=size, color=st["color"])
            self.y += size * lh
        self.y += st["after"]


def main():
    if not MANUAL.exists():
        raise SystemExit(f"ไม่พบคู่มือเดิม: {MANUAL}")
    # back up the original once
    backup = MANUAL.with_name(MANUAL.stem + "_backup.pdf")
    if not backup.exists():
        shutil.copy2(MANUAL, backup)

    addendum = fitz.open()
    flow = Flow(addendum)
    for kind, text in CONTENT:
        flow.add(kind, text)

    base = fitz.open(str(MANUAL))
    base.insert_pdf(addendum)
    tmp = MANUAL.with_suffix(".tmp.pdf")
    base.save(str(tmp), deflate=True)
    base.close()
    addendum.close()
    tmp.replace(MANUAL)
    print("อัปเดตคู่มือแล้ว:", MANUAL)
    print("สำรองต้นฉบับไว้ที่:", backup)


if __name__ == "__main__":
    main()
