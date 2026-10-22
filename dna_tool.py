"""
dna_tool.py — a small GUI that shows THIS machine's DNA and exports it as JSON.

Run it on the machine you want to authorise. It displays the MAC, motherboard
UUID and the SHA-256 "DNA", and the "Export JSON" button saves authorized_dna.json
— feed that file to the installer's "import DNA" step to bind the installation to
this machine.

It only READS hardware ids and writes a JSON file. No destructive action.

Dependencies: customtkinter
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

import machine_id

BG, CARD, ROW = "#0f1115", "#191c23", "#20242d"
STROKE, TEXT, MUTED = "#2a2f3a", "#e6eaf0", "#8a93a3"
ACCENT, ACCENT_D, GREEN = "#38bdf8", "#0ea5e9", "#34d399"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _font(size=14, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def export_json(out_path) -> Path:
    comp = machine_id.components()
    comp["exported"] = datetime.now().isoformat(timespec="seconds")
    out = Path(out_path)
    out.write_text(json.dumps(comp, ensure_ascii=False, indent=2), "utf-8")
    return out


class DnaTool(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Machine DNA Tool")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.comp = machine_id.components()

        ctk.CTkLabel(self, text="🔑 รหัสเครื่องนี้ (Machine DNA)",
                     font=_font(19, "bold"), text_color=TEXT).pack(pady=(20, 4))
        ctk.CTkLabel(self, text="นำไฟล์ JSON ที่ export ไปใช้กับตัวติดตั้งเพื่อผูกโปรแกรมกับเครื่องนี้",
                     font=_font(12), text_color=MUTED, wraplength=500).pack(pady=(0, 12))

        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=STROKE)
        card.pack(fill="x", padx=22)
        for label, val in [("DNA (SHA-256)", self.comp["dna_sha256"]),
                           ("ย่อ (short)", machine_id.machine_dna_short()),
                           ("MAC", self.comp["mac"]),
                           ("Motherboard UUID", self.comp["motherboard_uuid"])]:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=6)
            ctk.CTkLabel(row, text=label, width=150, anchor="w", font=_font(12),
                         text_color=MUTED).pack(side="left")
            box = ctk.CTkEntry(row, fg_color=ROW, border_color=STROKE,
                               text_color=TEXT)
            box.insert(0, val or "(ไม่พบ)")
            box.configure(state="readonly")
            box.pack(side="left", fill="x", expand=True)

        self.status = ctk.CTkLabel(self, text="", text_color=GREEN, font=_font(12))
        self.status.pack(pady=(12, 4))
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=(4, 10))
        ctk.CTkButton(btns, text="คัดลอก DNA", width=150, fg_color=ROW,
                      hover_color=STROKE, command=self._copy).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Export JSON…", width=180, fg_color=ACCENT,
                      hover_color=ACCENT_D, command=self._export).pack(side="left", padx=6)

    def _copy(self):
        try:
            self.clipboard_clear(); self.clipboard_append(self.comp["dna_sha256"])
            self.status.configure(text="คัดลอก DNA แล้ว ✓", text_color=GREEN)
        except Exception:
            pass

    def _export(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="บันทึกไฟล์ DNA", defaultextension=".json",
            initialfile="authorized_dna.json",
            initialdir=os.environ.get("USERPROFILE", str(Path.home())),
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            out = export_json(path)
            self.status.configure(text=f"บันทึกแล้ว: {out}", text_color=GREEN)
        except Exception as exc:
            self.status.configure(text=f"ล้มเหลว: {exc}", text_color="#f05252")


def main():
    DnaTool().mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile
        p = export_json(Path(tempfile.mkdtemp()) / "authorized_dna.json")
        ok = json.loads(p.read_text("utf-8")).get("dna_sha256")
        print("DNA TOOL SELFTEST OK | dna=", ok, "| file=", p)
        sys.exit(0 if ok else 1)
    main()
