"""
installer.py — a friendly GUI setup wizard for the "PC Health & Wellness Tracker".

It copies the Health & Wellness program to a folder the user picks (no admin
needed — defaults under %LOCALAPPDATA%), optionally creates Desktop / Start-Menu
shortcuts, and can save this machine's DNA for the optional node-lock feature.

It only copies files and makes shortcuts — it performs NO destructive action.

Payload: the program it installs ("Health & Wellness.exe"). When this installer
is built into its own .exe it bundles the payload (found in sys._MEIPASS);
otherwise the payload is taken from next to this script / the dist folder.

Dependencies: customtkinter
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import customtkinter as ctk

APP_NAME = "Health & Wellness"
PAYLOAD_NAME = "Health & Wellness.exe"
_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0

BG, CARD, ROW = "#0f1115", "#191c23", "#20242d"
STROKE, TEXT, MUTED = "#2a2f3a", "#e6eaf0", "#8a93a3"
ACCENT, ACCENT_D, GREEN = "#38bdf8", "#0ea5e9", "#34d399"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _font(size=14, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def payload_path() -> Path | None:
    """Locate the program to install."""
    cands = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            cands.append(Path(base) / PAYLOAD_NAME)
        cands.append(Path(sys.executable).resolve().parent / PAYLOAD_NAME)
    here = Path(__file__).resolve().parent
    cands += [here / PAYLOAD_NAME, here / "dist" / PAYLOAD_NAME]
    for c in cands:
        if c.is_file():
            return c
    return None


def default_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / APP_NAME


def _make_shortcut(lnk: Path, target: Path, workdir: Path, icon: Path | None = None):
    icon_line = f'$s.IconLocation="{icon}";' if icon else ""
    ps = (f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut("{lnk}");'
          f'$s.TargetPath="{target}";$s.WorkingDirectory="{workdir}";'
          f'{icon_line}$s.Save()')
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   creationflags=_NO_WINDOW, capture_output=True)


def do_install(dest_dir: Path, desktop: bool, startmenu: bool,
               save_dna: bool, progress=None, authorized=None) -> Path:
    """Copy the payload + optional shortcuts/DNA. Returns the installed exe path.
    `authorized`: list of machine-DNA hashes to bind this install to (node-lock
    gate)."""
    src = payload_path()
    if not src:
        raise FileNotFoundError(
            f"ไม่พบไฟล์โปรแกรม '{PAYLOAD_NAME}' — วางตัวติดตั้งไว้ข้างไฟล์โปรแกรม")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / PAYLOAD_NAME

    if progress:
        progress("กำลังคัดลอกโปรแกรม…", 0.2)
    shutil.copy2(src, target)

    if authorized:
        if progress:
            progress("กำลังผูกกับเครื่องที่อนุญาต (DNA)…", 0.5)
        try:
            import node_guard
            # Bind by embedding INSIDE the exe only — no separate node_authorized.json
            # (which would look like a deletable lock). The embedded binding can't be
            # removed by deleting a file.
            node_guard.embed_into_exe(target, authorized)
        except Exception:
            pass

    if desktop:
        if progress:
            progress("กำลังสร้างทางลัดบนเดสก์ท็อป…", 0.6)
        desk = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
        try:
            _make_shortcut(desk / f"{APP_NAME}.lnk", target, dest_dir)
        except Exception:
            pass

    if startmenu:
        if progress:
            progress("กำลังสร้างใน Start Menu…", 0.75)
        sm = (Path(os.environ.get("APPDATA", Path.home()))
              / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        try:
            sm.mkdir(parents=True, exist_ok=True)
            _make_shortcut(sm / f"{APP_NAME}.lnk", target, dest_dir)
        except Exception:
            pass

    if save_dna:
        if progress:
            progress("กำลังบันทึกรหัสเครื่อง (DNA)…", 0.9)
        try:
            import json
            import machine_id
            (dest_dir / "authorized_dna.json").write_text(
                json.dumps(machine_id.components(), ensure_ascii=False, indent=2),
                "utf-8")
        except Exception:
            pass

    if progress:
        progress("เสร็จสิ้น", 1.0)
    return target


class Installer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — ตัวติดตั้ง")
        self.geometry("560x440")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        self.dest = ctk.StringVar(value=str(default_install_dir()))
        self.v_desktop = ctk.StringVar(value="on")
        self.v_startmenu = ctk.StringVar(value="on")
        self.v_dna = ctk.StringVar(value="off")
        self.v_launch = ctk.StringVar(value="on")
        self.authorized_dnas: list[str] = []      # machine-DNA hashes to bind to
        self.installed_path: Path | None = None

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=22, pady=20)
        self.step = 0
        self._render()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _title(self, text, sub=""):
        ctk.CTkLabel(self.body, text=text, font=_font(20, "bold"),
                     text_color=TEXT).pack(anchor="w", pady=(0, 2))
        if sub:
            ctk.CTkLabel(self.body, text=sub, font=_font(12), text_color=MUTED,
                         wraplength=500, justify="left").pack(anchor="w", pady=(0, 14))

    def _nav(self, back=True, next_text="ถัดไป", next_cmd=None):
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(side="bottom", fill="x", pady=(18, 0))
        if back and self.step > 0:
            ctk.CTkButton(bar, text="ย้อนกลับ", width=110, fg_color=ROW,
                          hover_color=STROKE, command=self._back).pack(side="left")
        ctk.CTkButton(bar, text=next_text, width=150, fg_color=ACCENT,
                      hover_color=ACCENT_D,
                      command=next_cmd or self._next).pack(side="right")

    def _render(self):
        self._clear()
        [self._welcome, self._location, self._step_options, self._installing,
         self._finish][self.step]()

    def _next(self):
        self.step += 1
        self._render()

    def _back(self):
        self.step -= 1
        self._render()

    # ---- steps -------------------------------------------------------
    def _welcome(self):
        self._title("ยินดีต้อนรับสู่การติดตั้ง",
                    "PC Health & Wellness Tracker — โปรแกรมติดตามสุขภาพ "
                    "(ดื่มน้ำ, Intermittent Fasting, เช็คลิสต์)\n\n"
                    "ตัวติดตั้งนี้จะคัดลอกโปรแกรมไปยังเครื่องของคุณ และสร้างทางลัดให้")
        ok = payload_path() is not None
        ctk.CTkLabel(
            self.body,
            text=("พร้อมติดตั้ง ✓" if ok else
                  f"⚠️ ไม่พบไฟล์ {PAYLOAD_NAME} — วางตัวติดตั้งไว้ข้างไฟล์โปรแกรม"),
            text_color=(GREEN if ok else "#e6b800")).pack(anchor="w")
        self._nav(back=False)

    def _location(self):
        self._title("เลือกโฟลเดอร์ติดตั้ง",
                    "ไม่ต้องใช้สิทธิ์ผู้ดูแล (ติดตั้งในพื้นที่ของผู้ใช้)")
        rowf = ctk.CTkFrame(self.body, fg_color="transparent")
        rowf.pack(fill="x")
        ctk.CTkEntry(rowf, textvariable=self.dest, fg_color=ROW,
                     border_color=STROKE).pack(side="left", fill="x", expand=True,
                                               padx=(0, 8))
        ctk.CTkButton(rowf, text="เลือก…", width=90, fg_color=ROW,
                      hover_color=STROKE, command=self._browse).pack(side="right")
        self._nav()

    def _browse(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="เลือกโฟลเดอร์ติดตั้ง",
                                    initialdir=self.dest.get())
        if d:
            self.dest.set(str(Path(d) / APP_NAME))

    def _step_options(self):          # NOT "_options" — that name is used by tkinter.Misc
        self._title("ตัวเลือกการติดตั้ง")
        for var, label in [
                (self.v_desktop, "สร้างทางลัดบนเดสก์ท็อป"),
                (self.v_startmenu, "สร้างใน Start Menu"),
                (self.v_dna, "บันทึกรหัสเครื่องนี้ (Machine DNA) ลงโฟลเดอร์ติดตั้ง")]:
            ctk.CTkCheckBox(self.body, text=label, variable=var, onvalue="on",
                            offvalue="off", fg_color=ACCENT, hover_color=ACCENT_D,
                            text_color=TEXT).pack(anchor="w", pady=6)

        ctk.CTkLabel(self.body, text="— ผูกการติดตั้งกับเครื่องที่อนุญาต (Node-lock) —",
                     text_color=MUTED, font=_font(12)).pack(anchor="w", pady=(10, 2))
        ctk.CTkButton(self.body, text="นำเข้าไฟล์ DNA (authorized_dna.json)…",
                      width=320, fg_color=ROW, hover_color=STROKE,
                      command=self._import_dna).pack(anchor="w")
        self.dna_lbl = ctk.CTkLabel(
            self.body, text=self._dna_summary(), text_color=MUTED,
            font=_font(11), wraplength=500, justify="left")
        self.dna_lbl.pack(anchor="w", pady=(4, 0))
        self._nav(next_text="ติดตั้ง", next_cmd=self._go_install)

    def _dna_summary(self) -> str:
        if not self.authorized_dnas:
            return "ยังไม่ผูก — ติดตั้งแล้วใช้ได้ทุกเครื่อง (ถ้ารู้รหัส)"
        short = ", ".join(h[:12].upper() for h in self.authorized_dnas)
        return f"ผูกกับ {len(self.authorized_dnas)} เครื่อง: {short}"

    def _import_dna(self):
        from tkinter import filedialog, messagebox
        import json
        paths = filedialog.askopenfilenames(
            title="เลือกไฟล์ DNA (authorized_dna.json)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        for p in paths or []:
            try:
                d = json.loads(Path(p).read_text("utf-8"))
                h = (d.get("dna_sha256") or "").strip().lower()
                if len(h) == 64 and h not in self.authorized_dnas:
                    self.authorized_dnas.append(h)
            except Exception as exc:
                messagebox.showwarning("นำเข้า DNA", f"อ่านไฟล์ไม่ได้: {exc}", parent=self)
        self.dna_lbl.configure(text=self._dna_summary())

    def _go_install(self):
        self.step = 3
        self._render()

    def _installing(self):
        self._title("กำลังติดตั้ง…")
        self.pbar = ctk.CTkProgressBar(self.body, progress_color=ACCENT)
        self.pbar.set(0)
        self.pbar.pack(fill="x", pady=(10, 6))
        self.pstat = ctk.CTkLabel(self.body, text="เริ่ม…", text_color=MUTED)
        self.pstat.pack(anchor="w")

        dest = Path(self.dest.get())
        opts = (self.v_desktop.get() == "on", self.v_startmenu.get() == "on",
                self.v_dna.get() == "on")
        authorized = list(self.authorized_dnas)
        holder = {}

        def work():
            try:
                def prog(msg, frac):
                    holder["msg"], holder["frac"] = msg, frac
                holder["result"] = do_install(dest, *opts, progress=prog,
                                              authorized=authorized)
            except Exception as exc:
                holder["error"] = exc
            holder["done"] = True

        threading.Thread(target=work, daemon=True).start()

        def poll():
            if "frac" in holder:
                self.pbar.set(holder["frac"])
                self.pstat.configure(text=holder.get("msg", ""))
            if holder.get("done"):
                if holder.get("error"):
                    self.pstat.configure(text=f"ล้มเหลว: {holder['error']}",
                                         text_color="#f05252")
                    ctk.CTkButton(self.body, text="ย้อนกลับ", width=120, fg_color=ROW,
                                  command=lambda: self._set_step(2)).pack(pady=12)
                else:
                    self.installed_path = holder["result"]
                    self.step = 4
                    self._render()
            else:
                self.after(80, poll)

        self.after(80, poll)

    def _set_step(self, s):
        self.step = s
        self._render()

    def _finish(self):
        self._title("ติดตั้งเสร็จสมบูรณ์ ✓",
                    f"โปรแกรมถูกติดตั้งไว้ที่:\n{self.installed_path}")
        ctk.CTkCheckBox(self.body, text="เปิดโปรแกรมเลยหลังปิดหน้านี้",
                        variable=self.v_launch, onvalue="on", offvalue="off",
                        fg_color=ACCENT, hover_color=ACCENT_D,
                        text_color=TEXT).pack(anchor="w", pady=10)
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(side="bottom", fill="x", pady=(18, 0))
        ctk.CTkButton(bar, text="เสร็จสิ้น", width=150, fg_color=GREEN,
                      hover_color="#249e5c", command=self._done).pack(side="right")

    def _done(self):
        launch = self.v_launch.get() == "on" and self.installed_path
        self.destroy()
        if launch:
            try:
                os.startfile(str(self.installed_path))     # Windows
            except Exception:
                try:
                    subprocess.Popen([str(self.installed_path)])
                except Exception:
                    pass


def main():
    Installer().mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile
        d = Path(tempfile.mkdtemp()) / "inst"
        try:
            out = do_install(d, False, False, False)
            print("INSTALLER SELFTEST OK | payload=", payload_path(),
                  "| installed=", out, "| exists=", out.is_file())
            sys.exit(0)
        except Exception as e:
            print("INSTALLER SELFTEST FAIL:", e)
            sys.exit(1)
    main()
