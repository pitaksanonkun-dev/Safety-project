"""
gui.py — CustomTkinter front end for the encrypted vault.

Screens:
  - Login: a single password field, nothing else (minimal, no hints).
           The entered password routes to whichever vault it unlocks.
  - Dashboard: file-explorer style — drag & drop area + table of files,
               with Add / Extract / Remove / Lock, plus a menu bar:
                 File > Encrypt files to folder  (originals kept)
                 File > Decrypt files back       (restore to usable files)
                 Settings > Set output folder    (remembered across runs)
               Encrypt/Decrypt produce / read self-contained .enc files in a
               folder you choose, using the login password.

Deliberately NOT included: any duress-wipe, silent-exfiltration, or
metadata-timestomping behaviour. This is a straightforward personal vault.

Argon2 derivation runs on a worker thread so the UI never freezes.

Dependencies:
    pip install customtkinter tkinterdnd2 cryptography argon2-cffi
"""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:  # drag & drop is optional
    _HAS_DND = False

from vault import VaultStore
import file_crypto
import pdf_disguise
import recipient_crypto
import make_portable
try:
    import drive_client
    _HAS_DRIVE_LIB = True
except Exception:          # google libs not installed
    _HAS_DRIVE_LIB = False

# Anchor the store to the program folder (next to this file), so the vault is
# always found regardless of the working directory a launcher starts us in.
_APP_DIR = Path(__file__).resolve().parent
STORE_DIR = str(_APP_DIR / "vault_store")
SETTINGS_PATH = _APP_DIR / "app_settings.json"
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def write_share_file(path: Path, vault_id: str, index: int, data: bytes) -> None:
    """Write one recovery share as JSON (self-contained: carries the vault id)."""
    path.write_text(json.dumps(
        {"vault_id": vault_id, "index": index, "share": data.hex()}), "utf-8")


def read_share_file(path: Path) -> tuple[str | None, int, bytes]:
    """Read a share file. Accepts GUI JSON or the CLI 'idx:hex' format.
    Returns (vault_id_or_None, index, share_bytes)."""
    text = Path(path).read_text("utf-8").strip()
    if text.startswith("{"):
        obj = json.loads(text)
        return obj.get("vault_id"), int(obj["index"]), bytes.fromhex(obj["share"])
    # legacy CLI format: "idx:hex"
    idx_str, hex_str = text.split(":", 1)
    return None, int(idx_str), bytes.fromhex(hex_str)


class VaultApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Document Organizer")
        self.geometry("760x520")
        self.minsize(640, 440)

        # Enable drag & drop if tkinterdnd2 is available. tkinterdnd2 patches
        # drop_target_register onto all widgets once tkdnd is loaded into this
        # Tk interpreter via _require(root).
        self.dnd_ok = False
        if _HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ok = True
            except Exception:
                self.dnd_ok = False

        self.store = VaultStore(STORE_DIR)
        self.store.init()
        self.ov = None            # OpenVault once unlocked
        self.password = None      # kept in memory for file encrypt/decrypt
        self.pending_files = []   # files dropped, waiting to be encrypted

        # Persisted, non-secret settings (e.g. the encrypted-output folder).
        self.settings = self._load_settings()
        self.enc_out_dir = self.settings.get("enc_out_dir") or ""
        self.out_format = self.settings.get("out_format") or "PDF"   # "PDF" | "JPG"
        self.net_mode = self.settings.get("net_mode") or "Offline"   # "Online" | "Offline"
        self.drive_method = self.settings.get("drive_method") or "oauth"  # "oauth" | "sa"
        self.drive_sa_json = self.settings.get("drive_sa_json") or ""
        self.drive_oauth_client = self.settings.get("drive_oauth_client") or ""
        self.drive_folder_id = self.settings.get("drive_folder_id") or ""
        self.drive_token_path = str(_APP_DIR / "drive_token.json")
        self.allowed_emails = self.settings.get("allowed_emails") or []   # Online allow-list
        self.online_public = self.settings.get("online_public", True)     # anyone-with-file can decrypt
        # recipient-key (public-key) mode: encrypt to contacts' public keys so a
        # recipient decrypts with their own private key and types NO password.
        self.contacts = self.settings.get("contacts") or []   # [{"name","pk"}]
        self.send_mode = self.settings.get("send_mode") or "password"  # "password" | "recipient"
        self._drive_client = None            # cached Drive client

        # Make Ctrl+A/C/V/X work in every entry regardless of keyboard layout
        # (with a Thai layout, Ctrl+V sends a Thai keysym and the default paste
        # binding never fires — so we match on the physical key's keycode).
        self.bind_all("<Control-KeyPress>", self._clipboard_keys)

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)
        self.show_login()

    @staticmethod
    def _clipboard_keys(event):
        if not (event.state & 0x0004):        # Control must be held
            return None
        # If the keysym is already the Latin letter, the DEFAULT binding handles
        # it — doing it again here would paste/copy twice. Only step in when the
        # keysym is not the Latin letter (e.g. a Thai layout), matched by keycode.
        if (event.keysym or "").lower() in ("a", "c", "v", "x"):
            return None
        key = {65: "all", 67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>"}.get(
            event.keycode)                    # A / C / V / X physical keys
        if key is None:
            return None
        w = event.widget
        try:
            if key == "all":
                w.select_range(0, "end"); w.icursor("end")
            else:
                w.event_generate(key)
            return "break"
        except Exception:
            return None

    # ---- settings -----------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            return json.loads(SETTINGS_PATH.read_text("utf-8"))
        except Exception:
            return {}

    def _save_settings(self) -> None:
        try:
            SETTINGS_PATH.write_text(
                json.dumps(self.settings, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    # ---- helpers ------------------------------------------------------
    def _clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def _has_any_slot(self) -> bool:
        cfg = self.store._read_config()
        return bool(cfg.get("slots"))

    def _run_bg(self, work, done, poll_ms: int = 80):
        """Run work() on a worker thread, then call done(result, error) on the
        MAIN thread. The worker NEVER touches tkinter; completion is detected by
        a main-thread poller, which is the only safe way to use after().
        """
        holder = {}

        def worker():
            try:
                holder["result"] = work()
            except Exception as exc:          # captured, surfaced on main thread
                holder["error"] = exc
            holder["done"] = True

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if holder.get("done"):
                done(holder.get("result"), holder.get("error"))
            else:
                self.after(poll_ms, poll)     # scheduled from the main thread

        self.after(poll_ms, poll)

    def _show_success(self, title: str, message: str):
        """A success dialog with a green check and green frame."""
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.resizable(False, False)
        win.configure(fg_color="#e8f6ec")

        frame = ctk.CTkFrame(win, fg_color="#ffffff", border_color="#2e9e4f",
                             border_width=3, corner_radius=14)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(frame, text="✓",
                     font=ctk.CTkFont(size=58, weight="bold"),
                     text_color="#2e9e4f").pack(pady=(18, 0))
        ctk.CTkLabel(frame, text=title,
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#1f6b3b").pack(pady=(2, 4))
        ctk.CTkLabel(frame, text=message, text_color="#2b3a2e",
                     wraplength=380, justify="center").pack(padx=16, pady=(0, 12))
        ctk.CTkButton(frame, text="OK", width=130, fg_color="#2e9e4f",
                      hover_color="#24823c", command=win.destroy).pack(pady=(0, 16))

        win.update_idletasks()
        w, h = max(420, win.winfo_reqwidth()), win.winfo_reqheight()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        pw, ph = self.winfo_width(), self.winfo_height()
        win.geometry(f"{w}x{h}+{px + (pw - w)//2}+{py + (ph - h)//2}")
        try:
            win.transient(self)
            win.grab_set()
            win.lift()
            self.wait_window(win)
        except Exception:
            pass

    # ---- login screen -------------------------------------------------
    def show_login(self):
        self._clear()
        self.config(menu=tk.Menu(self))   # no menu bar on the login screen
        self.ov = None
        self.password = None
        self.pending_files = []
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(frame, text="Document Organizer",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 20))

        self.pw_entry = ctk.CTkEntry(frame, show="•", width=280,
                                     placeholder_text="Password")
        self.pw_entry.pack(pady=6)
        self.pw_entry.bind("<Return>", lambda _e: self._do_login())
        self.pw_entry.focus()

        btn_text = "Login" if self._has_any_slot() else "Create vault"
        self.login_btn = ctk.CTkButton(frame, text=btn_text, width=280,
                                       command=self._do_login)
        self.login_btn.pack(pady=(10, 4))

        self.status = ctk.CTkLabel(frame, text="", text_color="#e06c75")
        self.status.pack(pady=4)

        # Hidden recovery entry point (for a forgotten/lost password).
        # Kept as a discreet shortcut rather than a visible button.
        self.bind_all("<Control-Shift-R>", lambda _e: self.show_recovery())
        self.bind_all("<Control-Shift-Alt-R>", lambda _e: self.show_recovery())
        # A faint, easy-to-miss hint so you can still find it when you need it.
        hint = ctk.CTkLabel(frame, text="forgot password?  press Ctrl+Shift+R",
                            text_color="gray40", font=ctk.CTkFont(size=11))
        hint.pack(pady=(14, 0))

    def _do_login(self):
        pw = self.pw_entry.get()
        if not pw:
            return
        self.login_btn.configure(state="disabled", text="Working…")
        self.status.configure(text="")
        first_time = not self._has_any_slot()

        def work():
            return self.store.create_vault(pw) if first_time else self.store.unlock(pw)

        def done(ov, err):
            if err is not None:
                self._login_failed(str(err))
            else:
                self._login_done(ov, first_time, pw)

        self._run_bg(work, done)

    def _login_failed(self, msg: str):
        self.login_btn.configure(state="normal", text="Login")
        self.status.configure(text="Error")

    def _login_done(self, ov, first_time, pw):
        if ov is None:
            # generic failure — no hint about slots/decoys
            self.login_btn.configure(state="normal", text="Login")
            self.status.configure(text="Incorrect password")
            self.pw_entry.delete(0, "end")
            return
        self.ov = ov
        self.password = pw        # needed for file encrypt/decrypt menu
        self.show_dashboard()

    # ---- dashboard ----------------------------------------------------
    def _build_menubar(self):
        menubar = tk.Menu(self)

        # Only a Settings menu, holding the encrypted-output folder options.
        setmenu = tk.Menu(menubar, tearoff=0)
        setmenu.add_command(label="กำหนดโฟลเดอร์ปลายทาง…   (Set output folder)",
                            command=self._menu_set_outdir)
        setmenu.add_command(label="เปิดโฟลเดอร์ปลายทาง   (Open output folder)",
                            command=self._menu_show_outdir)
        setmenu.add_separator()
        setmenu.add_command(label="ตั้งค่า Google Drive — บัญชีส่วนตัว (OAuth) ⭐   [แนะนำ]",
                            command=self._menu_set_drive_oauth)
        setmenu.add_command(label="ตั้งค่า Google Drive — Service Account (Shared Drive)…",
                            command=self._menu_set_drive)
        setmenu.add_command(label="ทดสอบการเชื่อมต่อ Google Drive   (Test connection)",
                            command=self._menu_test_drive)
        setmenu.add_command(label="ออกจากระบบ / สลับบัญชี Google Drive   (Sign out)",
                            command=self._menu_disconnect_drive)
        setmenu.add_command(label="อีเมลที่อนุญาตถอดรหัส Online…   (Allowed emails)",
                            command=self._menu_allowed_emails)
        setmenu.add_separator()
        setmenu.add_command(label="กุญแจสาธารณะของฉัน — ส่งให้ผู้อื่น   (My public key)",
                            command=self._menu_my_public_key)
        setmenu.add_command(label="รายชื่อผู้รับ (public key) สำหรับ recipient-key…   (Contacts)",
                            command=self._menu_contacts)
        setmenu.add_separator()
        setmenu.add_command(label="สร้างชุดแจกจ่ายสำหรับเครื่องอื่น…   (Export portable copy)",
                            command=self._menu_export_portable)
        menubar.add_cascade(label="ตั้งค่า / Settings", menu=setmenu)

        self.config(menu=menubar)

    def show_dashboard(self):
        self._clear()
        self._build_menubar()

        top = ctk.CTkFrame(self.container)
        top.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(top, text="Files", font=ctk.CTkFont(size=16, weight="bold")
                     ).pack(side="left", padx=8)
        ctk.CTkButton(top, text="Lock", width=80, fg_color="gray30",
                      command=self.show_login).pack(side="right", padx=4)
        ctk.CTkButton(top, text="Backup key…", width=110, fg_color="gray30",
                      command=self._export_shares).pack(side="right", padx=4)
        ctk.CTkButton(top, text="Add files…", width=110,
                      command=self._add_files).pack(side="right", padx=4)

        # Output format selector for encryption (PDF or JPG).
        fmt_row = ctk.CTkFrame(self.container, fg_color="transparent")
        fmt_row.pack(fill="x", padx=16, pady=(6, 0))
        ctk.CTkLabel(fmt_row, text="รูปแบบไฟล์ที่เข้ารหัส / Output:"
                     ).pack(side="left", padx=(2, 8))
        self.fmt_selector = ctk.CTkSegmentedButton(
            fmt_row, values=["PDF", "JPG"], command=self._set_out_format)
        self.fmt_selector.set(self.out_format)
        self.fmt_selector.pack(side="left")

        ctk.CTkLabel(fmt_row, text="   โหมด / Mode:").pack(side="left", padx=(16, 8))
        self.net_selector = ctk.CTkSegmentedButton(
            fmt_row, values=["Offline", "Online"], command=self._set_net_mode)
        self.net_selector.set(self.net_mode)
        self.net_selector.pack(side="left")

        # How the data key is protected: a shared password, or sealed to a
        # recipient's public key (recipient decrypts with no password).
        sec_row = ctk.CTkFrame(self.container, fg_color="transparent")
        sec_row.pack(fill="x", padx=16, pady=(4, 0))
        ctk.CTkLabel(sec_row, text="วิธีเข้ารหัส / Encrypt with:").pack(side="left", padx=(2, 8))
        self.send_selector = ctk.CTkSegmentedButton(
            sec_row, values=["รหัสผ่าน (password)", "ถึงผู้รับ (recipient-key)"],
            command=self._set_send_mode)
        self.send_selector.set("ถึงผู้รับ (recipient-key)" if self.send_mode == "recipient"
                               else "รหัสผ่าน (password)")
        self.send_selector.pack(side="left")

        # Primary action buttons: encrypt / decrypt files to/from a folder.
        actions = ctk.CTkFrame(self.container, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(4, 2))
        ctk.CTkButton(actions, text="🔒  เข้ารหัสไฟล์ / Encrypt files",
                      height=40, command=self._menu_encrypt
                      ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(actions, text="🔓  ถอดรหัสไฟล์ / Decrypt files",
                      height=40, fg_color="#2d7d46", hover_color="#236138",
                      command=self._menu_decrypt
                      ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        # drop area
        drop = ctk.CTkFrame(self.container, height=70, fg_color="gray20")
        drop.pack(fill="x", padx=16, pady=4)
        drop.pack_propagate(False)
        self._default_drop_text = (
            "ลากไฟล์มาวางที่นี่ แล้วกด 'เข้ารหัสไฟล์' (→ PDF ข้อพระคัมภีร์)  หรือ  'ถอดรหัสไฟล์' (คืนไฟล์เดิม)"
            if self.dnd_ok
            else "ใช้ปุ่ม 'เข้ารหัสไฟล์' / 'ถอดรหัสไฟล์' เพื่อเลือกไฟล์ (ติดตั้ง tkinterdnd2 เพื่อใช้ลากวาง)")
        self.drop_label = ctk.CTkLabel(drop, text=self._default_drop_text,
                                       text_color="gray70", wraplength=680)
        self.drop_label.pack(expand=True)
        if self.dnd_ok:
            drop.drop_target_register(DND_FILES)
            drop.dnd_bind("<<Drop>>", self._on_drop)
        self._update_drop_label()   # reflect any files already queued

        # file table
        table_frame = ctk.CTkFrame(self.container)
        table_frame.pack(fill="both", expand=True, padx=16, pady=8)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background="#1f1f1f",
                        foreground="white")
        style.map("Treeview", background=[("selected", "#1f6aa5")])

        self.tree = ttk.Treeview(table_frame,
                                 columns=("name", "size", "id"),
                                 show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("size", text="Size")
        self.tree.heading("id", text="File ID")
        self.tree.column("name", width=320)
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("id", width=260)
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(table_frame, orient="vertical",
                           command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        bottom = ctk.CTkFrame(self.container, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(bottom, text="Extract selected",
                      command=self._extract_selected).pack(side="left", padx=4)
        ctk.CTkButton(bottom, text="Remove selected", fg_color="#a3332f",
                      hover_color="#7d2420",
                      command=self._remove_selected).pack(side="left", padx=4)

        self.dash_status = ctk.CTkLabel(bottom, text="", text_color="#4caf69")
        self.dash_status.pack(side="right", padx=8)

        self._refresh_table()

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for f in sorted(self.ov.list_files(), key=lambda x: x["name"].lower()):
            self.tree.insert("", "end",
                             values=(f["name"], human_size(f["size"]), f["id"]))

    def _add_paths(self, paths):
        added_sources = []
        skipped = []
        for p in paths:
            p = Path(p)
            if p.is_file():
                try:
                    self.ov.add_file(p)
                    added_sources.append(p)
                except Exception as exc:
                    messagebox.showerror("Add failed", f"{p.name}: {exc}")
            else:
                skipped.append(str(p))

        if not added_sources:
            if skipped:
                messagebox.showwarning(
                    "Nothing added",
                    "These items are not files (folders are not supported yet):\n\n"
                    + "\n".join(skipped))
            return

        self._refresh_table()
        n = len(added_sources)
        self.dash_status.configure(
            text=f"✓ encrypted & stored {n} file(s) in the vault")
        # Originals are kept — the vault holds an encrypted copy. To decrypt a
        # file back out, select it and use "Extract selected".

    def _add_files(self):
        paths = filedialog.askopenfilenames(title="Add files to vault")
        if paths:
            self._add_paths(paths)

    def _on_drop(self, event):
        # tkinterdnd2 returns a brace/space-delimited list. Dropped files are
        # queued for encryption; the user then clicks "Encrypt files".
        paths = [p for p in self.tk.splitlist(event.data) if Path(p).is_file()]
        if not paths:
            return
        # add to the queue, avoiding duplicates, keeping order
        for p in paths:
            if p not in self.pending_files:
                self.pending_files.append(p)
        self._update_drop_label()
        self.dash_status.configure(
            text=f"วางไฟล์แล้ว {len(self.pending_files)} ไฟล์ — กด 'เข้ารหัสไฟล์' หรือ 'ถอดรหัสไฟล์'")

    def _update_drop_label(self):
        if not getattr(self, "drop_label", None):
            return
        if self.pending_files:
            names = ", ".join(Path(p).name for p in self.pending_files[:4])
            more = ("" if len(self.pending_files) <= 4
                    else f"  …(+{len(self.pending_files) - 4})")
            self.drop_label.configure(
                text=f"มีไฟล์ในคิว {len(self.pending_files)} ไฟล์:  {names}{more}"
                     f"\n(กด 'เข้ารหัสไฟล์' หรือ 'ถอดรหัสไฟล์')",
                text_color="#4caf69")
        else:
            self.drop_label.configure(text=self._default_drop_text,
                                      text_color="gray70")

    def _clear_pending(self):
        self.pending_files = []
        self._update_drop_label()

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0])["values"][2]

    def _extract_selected(self):
        fid = self._selected_id()
        if not fid:
            return
        out_dir = filedialog.askdirectory(title="Extract to…")
        if not out_dir:
            return
        try:
            out = self.ov.extract_file(str(fid), out_dir)
            messagebox.showinfo("Extracted", f"Saved to:\n{out}")
        except Exception as exc:
            messagebox.showerror("Extract failed", str(exc))

    def _remove_selected(self):
        fid = self._selected_id()
        if not fid:
            return
        if messagebox.askyesno("Remove", "Remove this file from the vault?"):
            self.ov.remove_file(str(fid))
            self._refresh_table()

    # ---- recovery: export shares (do this BEFORE you forget) ----------
    # Fixed scheme: always create 3 recovery keys; any 2 of the 3 recover.
    SHARE_K = 2
    SHARE_N = 3

    def _export_shares(self):
        if self.ov is None:
            return

        out_dir = filedialog.askdirectory(
            title="เลือกโฟลเดอร์สำหรับเก็บกุญแจกู้คืน / Save recovery keys to a folder")
        if not out_dir:
            return
        out_dir = Path(out_dir)
        try:
            shares = self.ov.export_recovery_shares(self.SHARE_K, self.SHARE_N)
            paths = []
            for idx, data in shares:
                p = out_dir / f"recovery_key_{idx}.json"
                write_share_file(p, self.ov.vault_id, idx, data)
                paths.append(p)
        except Exception as exc:
            messagebox.showerror("Backup key", str(exc))
            return

        messagebox.showinfo(
            "สร้างกุญแจกู้คืนแล้ว / Recovery keys created",
            f"สร้างกุญแจกู้คืน {self.SHARE_N} ดอก — ใช้ {self.SHARE_K} ใน {self.SHARE_N} ดอก "
            f"ก็กู้ตู้นี้ได้ แม้ลืมรหัสผ่าน\n\n"
            f"⚠️ แยกเก็บแต่ละดอกไว้คนละที่ (เช่น USB คนละอัน / สถานที่ต่างกัน)\n"
            f"อย่าเก็บครบ {self.SHARE_K} ดอกไว้ที่เดียวกัน\n\n"
            + "\n".join(str(p) for p in paths))

    # ---- recovery screen (forgotten / lost password) ------------------
    def show_recovery(self):
        self._clear()
        self._recovery_shares = []   # list[(index, bytes)]
        self._recovery_vault_id = None

        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(frame, text="Recover access",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(0, 6))
        ctk.CTkLabel(frame, text="Load your recovery shares, then set a new password.",
                     text_color="gray70").pack(pady=(0, 14))

        ctk.CTkButton(frame, text="Select recovery share files…", width=300,
                      command=self._load_recovery_shares).pack(pady=4)
        self.rec_info = ctk.CTkLabel(frame, text="No shares loaded.",
                                     text_color="gray70")
        self.rec_info.pack(pady=4)

        self.rec_pw = ctk.CTkEntry(frame, show="•", width=300,
                                   placeholder_text="New password")
        self.rec_pw.pack(pady=(14, 4))
        self.rec_pw2 = ctk.CTkEntry(frame, show="•", width=300,
                                    placeholder_text="Confirm new password")
        self.rec_pw2.pack(pady=4)

        self.rec_btn = ctk.CTkButton(frame, text="Recover & set new password",
                                     width=300, command=self._do_recovery)
        self.rec_btn.pack(pady=(12, 4))
        self.rec_status = ctk.CTkLabel(frame, text="", text_color="#e06c75")
        self.rec_status.pack(pady=2)

        ctk.CTkButton(frame, text="Back", width=120, fg_color="gray30",
                      command=self.show_login).pack(pady=(8, 0))

    def _load_recovery_shares(self):
        paths = filedialog.askopenfilenames(
            title="Select recovery share files",
            filetypes=[("Share files", "*.json *.hex *.txt"), ("All files", "*.*")])
        if not paths:
            return
        shares, vault_ids = [], set()
        try:
            for p in paths:
                vid, idx, data = read_share_file(Path(p))
                shares.append((idx, data))
                if vid:
                    vault_ids.add(vid)
        except Exception as exc:
            self.rec_info.configure(text=f"Could not read a share: {exc}")
            return

        # de-duplicate by index
        seen, uniq = set(), []
        for idx, data in shares:
            if idx not in seen:
                seen.add(idx)
                uniq.append((idx, data))
        self._recovery_shares = uniq

        if len(vault_ids) == 1:
            self._recovery_vault_id = next(iter(vault_ids))
            vtxt = f"vault {self._recovery_vault_id[:8]}…"
        elif len(vault_ids) > 1:
            self.rec_info.configure(text="Shares are from different vaults — load matching ones.")
            self._recovery_shares = []
            return
        else:
            self._recovery_vault_id = None
            vtxt = "vault id not in files"
        self.rec_info.configure(
            text=f"Loaded {len(uniq)} share(s)  ({vtxt})")

    def _do_recovery(self):
        if len(self._recovery_shares) < 2:
            self.rec_status.configure(text="Load at least your k shares first.")
            return
        pw = self.rec_pw.get()
        if not pw:
            self.rec_status.configure(text="Enter a new password.")
            return
        if pw != self.rec_pw2.get():
            self.rec_status.configure(text="Passwords do not match.")
            return

        vault_id = self._recovery_vault_id
        if vault_id is None:
            # legacy shares without an embedded id: ask for it
            dlg = ctk.CTkInputDialog(title="Vault id",
                                     text="Enter the vault id shown when you created the shares:")
            vault_id = (dlg.get_input() or "").strip()
            if not vault_id:
                self.rec_status.configure(text="Vault id required for these shares.")
                return

        self.rec_btn.configure(state="disabled", text="Working…")
        self.rec_status.configure(text="")
        shares = list(self._recovery_shares)

        def work():
            ov = self.store.unlock_with_shares(vault_id, shares)  # rebuild DK
            self.store.add_password(ov, pw)                       # wrap under new pw
            return ov

        def done(ov, err):
            if err is not None:
                self._recovery_failed(err)
            else:
                self._recovery_done(ov, pw)

        self._run_bg(work, done)

    def _recovery_failed(self, exc):
        self.rec_btn.configure(state="normal", text="Recover & set new password")
        msg = ("Wrong shares for this vault, or too few to meet the threshold."
               if "tag" in str(exc).lower() or isinstance(exc, (ValueError,))
               else str(exc))
        self.rec_status.configure(text=msg)

    def _recovery_done(self, ov, pw):
        self.ov = ov
        self.password = pw
        messagebox.showinfo("Recovered",
                            "Access recovered and a new password has been set.\n"
                            "You can now log in with the new password.")
        self.show_dashboard()

    def _set_out_format(self, value):
        self.out_format = value              # "PDF" or "JPG"
        self.settings["out_format"] = value
        self._save_settings()

    def _set_net_mode(self, value):
        self.net_mode = value                # "Online" or "Offline"
        self.settings["net_mode"] = value
        self._save_settings()

    def _set_send_mode(self, value):
        self.send_mode = "recipient" if "recipient" in value else "password"
        self.settings["send_mode"] = self.send_mode
        self._save_settings()
        if self.send_mode == "recipient" and not self.contacts:
            messagebox.showinfo(
                "โหมดถึงผู้รับ (recipient-key)",
                "โหมดนี้เข้ารหัส 'ถึงผู้รับเจาะจง' โดยผู้รับไม่ต้องพิมพ์รหัสผ่าน\n\n"
                "ขั้นตอน:\n"
                "1) ขอ public key ของผู้รับ (เขากดเมนู 'กุญแจสาธารณะของฉัน' แล้วส่งให้คุณ — "
                "ส่งผ่าน LINE ได้ ไม่ลับ)\n"
                "2) เพิ่มที่เมนู ตั้งค่า > รายชื่อผู้รับ (Contacts)\n"
                "3) เข้ารหัสได้เลย ผู้รับเปิดไฟล์แล้วกดถอดรหัส ระบบใช้ private key ของเขาเอง")

    def _menu_allowed_emails(self):
        """Manage (add / remove) the Gmail allow-list for Online decryption."""
        win = ctk.CTkToplevel(self)
        win.title("อีเมลที่อนุญาตถอดรหัส Online")
        win.geometry("480x440")
        win.configure(fg_color="#141414")          # dark background

        ctk.CTkLabel(win, text="อีเมล Gmail ที่อนุญาตให้ถอดรหัสไฟล์ Online",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#f2f4f7").pack(pady=(14, 2))
        ctk.CTkLabel(win, text="เว้นว่าง = เฉพาะบัญชีของคุณเองเท่านั้น",
                     text_color="#aab2bd").pack(pady=(0, 6))

        # Public toggle — easiest for sending to another machine (no setup there)
        pub_var = ctk.StringVar(value="on" if self.online_public else "off")

        def toggle_public():
            self.online_public = (pub_var.get() == "on")
            self.settings["online_public"] = self.online_public
            self._save_settings()
            listframe.configure(fg_color="#171717" if self.online_public else "#1e1e1e")

        ctk.CTkSwitch(
            win, text="เปิดสาธารณะ: ใครมีไฟล์ + รหัสผ่าน ก็ถอดได้ (ไม่ต้องตั้งค่าเครื่องปลายทาง)",
            variable=pub_var, onvalue="on", offvalue="off",
            command=toggle_public, text_color="#e6b800").pack(pady=(0, 8), padx=14)
        ctk.CTkLabel(win, text="ปิดสวิตช์ = จำกัดเฉพาะอีเมลด้านล่าง (ผู้รับต้องตั้งค่า Google Drive เอง)",
                     text_color="#8a9099", font=ctk.CTkFont(size=11)).pack(pady=(0, 6))

        listframe = ctk.CTkScrollableFrame(
            win, height=180, fg_color="#171717" if self.online_public else "#1e1e1e")
        listframe.pack(fill="both", expand=True, padx=14, pady=4)

        def save():
            self.settings["allowed_emails"] = self.allowed_emails
            self._save_settings()

        def refresh():
            for w in listframe.winfo_children():
                w.destroy()
            if not self.allowed_emails:
                ctk.CTkLabel(listframe, text="(ยังไม่มีอีเมล)",
                             text_color="#aab2bd").pack(pady=12)
                return
            for em in list(self.allowed_emails):
                row = ctk.CTkFrame(listframe, fg_color="#2b2d31", corner_radius=8)
                row.pack(fill="x", pady=3, padx=2)
                ctk.CTkLabel(row, text=em, anchor="w", text_color="#f2f4f7").pack(
                    side="left", fill="x", expand=True, padx=(10, 8), pady=4)
                ctk.CTkButton(row, text="ลบ", width=56, fg_color="#a3332f",
                              hover_color="#7d2420",
                              command=lambda e=em: remove(e)).pack(side="right",
                                                                   padx=6, pady=4)

        def remove(em):
            if em in self.allowed_emails:
                self.allowed_emails.remove(em)
                save()
                refresh()

        def add():
            em = entry.get().strip()
            if not em:
                return
            if "@" not in em or "." not in em.split("@")[-1]:
                messagebox.showwarning("อีเมลไม่ถูกต้อง",
                                       "กรุณาใส่อีเมลให้ถูกต้อง เช่น name@gmail.com",
                                       parent=win)
                return
            if em not in self.allowed_emails:
                self.allowed_emails.append(em)
                save()
                refresh()
            entry.delete(0, "end")

        addrow = ctk.CTkFrame(win, fg_color="transparent")
        addrow.pack(fill="x", padx=14, pady=(4, 6))
        entry = ctk.CTkEntry(addrow, placeholder_text="name@gmail.com")
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", lambda _e: add())
        ctk.CTkButton(addrow, text="เพิ่ม", width=74, command=add).pack(side="right")

        ctk.CTkButton(win, text="เสร็จสิ้น", width=120,
                      command=win.destroy).pack(pady=(0, 12))

        refresh()
        try:
            win.transient(self)
            win.grab_set()
            win.lift()
            entry.focus()
        except Exception:
            pass

    # ---- recipient-key: my key + contacts ----------------------------
    def _menu_my_public_key(self):
        """Show this account's public key so the user can send it to a sender.
        Public keys are NOT secret — safe to share over LINE/chat."""
        if self.ov is None:
            messagebox.showwarning("Locked", "กรุณา login ก่อน")
            return
        try:
            pub = self.ov.my_public_key()
        except Exception as exc:
            messagebox.showerror("Public key", f"อ่านกุญแจไม่ได้: {exc}")
            return
        text = recipient_crypto.encode_public(pub)
        fp = recipient_crypto.fingerprint(pub)

        win = ctk.CTkToplevel(self)
        win.title("กุญแจสาธารณะของฉัน (My public key)")
        win.geometry("560x320")
        win.configure(fg_color="#141414")
        ctk.CTkLabel(win, text="กุญแจสาธารณะของฉัน (ส่งให้ผู้ส่งได้เลย — ไม่ลับ)",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#f2f4f7").pack(pady=(14, 2))
        ctk.CTkLabel(win, text=f"ลายนิ้วมือ (fingerprint) เพื่อตรวจสอบด้วยตา: {fp}",
                     text_color="#e6b800").pack(pady=(0, 6))
        box = ctk.CTkTextbox(win, height=120, wrap="word", fg_color="#1e1e1e",
                             text_color="#f2f4f7")
        box.pack(fill="both", expand=True, padx=14, pady=6)
        box.insert("1.0", text)
        box.configure(state="normal")

        def copy():
            try:
                self.clipboard_clear(); self.clipboard_append(text)
                btn.configure(text="คัดลอกแล้ว ✓")
            except Exception:
                pass

        ctk.CTkLabel(win, text="วิธีใช้: ส่งข้อความนี้ให้ผู้ที่จะเข้ารหัสไฟล์ถึงคุณ "
                               "เขาจะเพิ่มคุณในรายชื่อผู้รับ แล้วส่งไฟล์มาให้คุณถอดได้โดยไม่ต้องใช้รหัส",
                     text_color="#8a9099", wraplength=520,
                     font=ctk.CTkFont(size=11)).pack(padx=14, pady=(0, 4))
        btn = ctk.CTkButton(win, text="คัดลอกกุญแจ (Copy)", width=180, command=copy)
        btn.pack(pady=(0, 12))
        try:
            win.transient(self); win.grab_set(); win.lift()
        except Exception:
            pass

    def _menu_contacts(self):
        """Manage recipients' public keys for recipient-key encryption."""
        win = ctk.CTkToplevel(self)
        win.title("รายชื่อผู้รับ (Contacts)")
        win.geometry("560x520")
        win.configure(fg_color="#141414")

        ctk.CTkLabel(win, text="รายชื่อผู้รับสำหรับโหมด recipient-key",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#f2f4f7").pack(pady=(14, 2))
        ctk.CTkLabel(win, text="เพิ่ม public key ของผู้รับ แล้วเลือกเข้ารหัสถึงเขาได้โดยไม่ต้องใช้รหัสผ่าน",
                     text_color="#aab2bd", wraplength=520).pack(pady=(0, 6))

        listframe = ctk.CTkScrollableFrame(win, height=220, fg_color="#171717")
        listframe.pack(fill="both", expand=True, padx=14, pady=4)

        def save():
            self.settings["contacts"] = self.contacts
            self._save_settings()

        def remove(c):
            if c in self.contacts:
                self.contacts.remove(c)
                save(); refresh()

        def refresh():
            for w in listframe.winfo_children():
                w.destroy()
            if not self.contacts:
                ctk.CTkLabel(listframe, text="(ยังไม่มีผู้รับ)",
                             text_color="#aab2bd").pack(pady=12)
                return
            for c in list(self.contacts):
                try:
                    fp = recipient_crypto.fingerprint(recipient_crypto.decode_public(c["pk"]))
                except Exception:
                    fp = "??"
                row = ctk.CTkFrame(listframe, fg_color="#2b2d31", corner_radius=8)
                row.pack(fill="x", pady=3, padx=2)
                ctk.CTkLabel(row, text=f"{c.get('name','(ไม่มีชื่อ)')}   [{fp}]",
                             anchor="w", text_color="#f2f4f7").pack(
                    side="left", fill="x", expand=True, padx=(10, 8), pady=4)
                ctk.CTkButton(row, text="ลบ", width=56, fg_color="#a3332f",
                              hover_color="#7d2420",
                              command=lambda x=c: remove(x)).pack(side="right",
                                                                  padx=6, pady=4)

        def add():
            name = name_entry.get().strip()
            pk = pk_entry.get("1.0", "end").strip()
            if not pk:
                return
            try:
                pub = recipient_crypto.decode_public(pk)
            except ValueError as e:
                messagebox.showwarning("Public key ไม่ถูกต้อง", str(e), parent=win)
                return
            canon = recipient_crypto.encode_public(pub)   # normalize
            fp = recipient_crypto.fingerprint(pub)
            if any(x.get("pk") == canon for x in self.contacts):
                messagebox.showinfo("ซ้ำ", "มีผู้รับคนนี้อยู่แล้ว", parent=win)
                return
            self.contacts.append({"name": name or f"ผู้รับ {fp}", "pk": canon})
            save(); refresh()
            name_entry.delete(0, "end"); pk_entry.delete("1.0", "end")

        form = ctk.CTkFrame(win, fg_color="transparent")
        form.pack(fill="x", padx=14, pady=(4, 6))
        name_entry = ctk.CTkEntry(form, placeholder_text="ชื่อผู้รับ (เช่น คุณเอ)")
        name_entry.pack(fill="x", pady=(0, 4))
        pk_entry = ctk.CTkTextbox(form, height=70, wrap="word")
        pk_entry.pack(fill="x")
        ctk.CTkLabel(form, text="วาง public key ที่ขึ้นต้นด้วย DOCORGPK1: ที่ผู้รับส่งมา",
                     text_color="#8a9099", font=ctk.CTkFont(size=11)).pack(
            anchor="w", pady=(2, 0))
        ctk.CTkButton(win, text="เพิ่มผู้รับ (Add)", width=160, command=add).pack(pady=(4, 6))
        ctk.CTkButton(win, text="เสร็จสิ้น", width=120,
                      command=win.destroy).pack(pady=(0, 12))

        refresh()
        try:
            win.transient(self); win.grab_set(); win.lift(); name_entry.focus()
        except Exception:
            pass

    # ---- Google Drive ------------------------------------------------
    def _drive_lib_ok(self) -> bool:
        if not _HAS_DRIVE_LIB:
            messagebox.showerror(
                "Google Drive",
                "ยังไม่มีไลบรารี Google API\nติดตั้งด้วย:\n"
                "pip install google-api-python-client google-auth google-auth-oauthlib")
            return False
        return True

    @staticmethod
    def _clean_folder_id(raw):
        """Accept a pasted Folder ID or a full Drive URL; return just the ID."""
        raw = (raw or "").strip()
        if "/folders/" in raw:
            raw = raw.split("/folders/", 1)[1]
        return raw.split("?", 1)[0].split("/", 1)[0].strip()

    def _build_setup(self):
        """Bundle the OAuth client + allow-list so a recipient self-configures and
        becomes a full sender/receiver. Returns None if not applicable."""
        if self.drive_method != "oauth" or not self.drive_oauth_client:
            return None
        try:
            with open(self.drive_oauth_client, encoding="utf-8") as f:
                cs = json.load(f)
        except Exception:
            return None
        return {"client_secret": cs,
                "allowed_emails": list(self.allowed_emails),
                "public": self.online_public}

    def _install_setup(self, setup):
        """Auto-apply a bundled setup from a received file: write the OAuth client
        locally (if this machine has none) and inherit the allow-list / mode."""
        try:
            cs = setup.get("client_secret")
            if cs and not self._drive_configured():
                path = str(_APP_DIR / "drive_client_secret.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cs, f)
                self.drive_method = "oauth"
                self.drive_oauth_client = path
                self.settings["drive_method"] = "oauth"
                self.settings["drive_oauth_client"] = path
                # a copied token (if any) belongs to the sender — drop it so this
                # machine signs in as ITS OWN Google account
                self._forget_drive_login()
            em = setup.get("allowed_emails")
            if em is not None:
                merged = list(dict.fromkeys(list(self.allowed_emails) + list(em)))
                self.allowed_emails = merged
                self.settings["allowed_emails"] = merged
            if "public" in setup:
                self.online_public = bool(setup["public"])
                self.settings["online_public"] = self.online_public
            self._save_settings()
        except Exception:
            pass

    def _menu_set_drive_oauth(self):
        """Recommended: OAuth — uploads to the user's own Drive (has quota)."""
        if not self._drive_lib_ok():
            return
        f = filedialog.askopenfilename(
            title="เลือกไฟล์ OAuth Client (client_secret….json) / Choose OAuth client JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not f:
            return
        dlg = ctk.CTkInputDialog(
            title="Google Drive folder",
            text="วาง Folder ID ในไดรฟ์ของคุณ (เว้นว่างได้ = เก็บที่ My Drive):")
        folder = self._clean_folder_id(dlg.get_input())

        self.drive_method = "oauth"
        self.drive_oauth_client = f
        self.drive_folder_id = folder
        self.settings["drive_method"] = "oauth"
        self.settings["drive_oauth_client"] = f
        self.settings["drive_folder_id"] = folder
        self._save_settings()
        # a new client means a new account — drop any cached login so it asks again
        self._forget_drive_login()
        messagebox.showinfo(
            "Google Drive (OAuth)",
            "ครั้งแรกจะเปิดหน้าเว็บให้คุณ 'อนุญาต' การเข้าถึง Google Drive\n"
            "เลือก 'บัญชีของเครื่องนี้' → กด Continue/อนุญาต จนเสร็จ แล้วกลับมาที่โปรแกรม")
        self._menu_test_drive()      # triggers the browser consent once

    def _forget_drive_login(self):
        """Delete the cached OAuth token so the next connection asks to sign in
        again (used when switching Google account / client)."""
        self._drive_client = None
        try:
            if os.path.exists(self.drive_token_path):
                os.remove(self.drive_token_path)
        except Exception:
            pass

    def _menu_disconnect_drive(self):
        """Sign out of Google Drive on this machine (switch account)."""
        if messagebox.askyesno(
                "ออกจากระบบ Google Drive",
                "ต้องการออกจากบัญชี Google Drive บนเครื่องนี้ไหม?\n"
                "ครั้งต่อไปที่ใช้ Online จะให้ล็อกอินใหม่ (เลือกบัญชีอื่นได้)"):
            self._forget_drive_login()
            messagebox.showinfo("Google Drive",
                                "ออกจากระบบแล้ว — ครั้งต่อไปจะให้ล็อกอินใหม่")

    def _menu_set_drive(self):
        """Service Account — only works with a Shared Drive (Workspace)."""
        if not self._drive_lib_ok():
            return
        f = filedialog.askopenfilename(
            title="เลือกไฟล์กุญแจ Service Account (.json)",
            filetypes=[("JSON key", "*.json"), ("All files", "*.*")])
        if not f:
            return
        dlg = ctk.CTkInputDialog(
            title="Shared Drive folder",
            text="วาง Folder ID ใน Shared Drive (Service Account ต้องเป็นสมาชิก):")
        folder = self._clean_folder_id(dlg.get_input())

        self.drive_method = "sa"
        self.drive_sa_json = f
        self.drive_folder_id = folder
        self.settings["drive_method"] = "sa"
        self.settings["drive_sa_json"] = f
        self.settings["drive_folder_id"] = folder
        self._save_settings()
        self._drive_client = None
        messagebox.showwarning(
            "Service Account",
            "โหมดนี้ใช้ได้เฉพาะ Shared Drive เท่านั้น\n"
            "ถ้าใช้ Gmail ส่วนตัว (My Drive) จะขึ้น storageQuotaExceeded\n"
            "แนะนำใช้ 'บัญชีส่วนตัว (OAuth)' แทน")
        self._menu_test_drive()

    def _drive_configured(self) -> bool:
        if self.drive_method == "oauth":
            return bool(self.drive_oauth_client and Path(self.drive_oauth_client).is_file())
        return bool(self.drive_sa_json and Path(self.drive_sa_json).is_file())

    def _build_drive(self):
        """Construct a Drive client (may open a browser once for OAuth)."""
        if self.drive_method == "oauth":
            return drive_client.DriveClientOAuth(
                self.drive_oauth_client, self.drive_token_path, self.drive_folder_id)
        return drive_client.DriveClient(self.drive_sa_json, self.drive_folder_id)

    def _get_drive(self):
        """Return a cached Drive client, or None if not configured. May build
        (and trigger OAuth consent) — call from a worker thread when possible."""
        if not _HAS_DRIVE_LIB or not self._drive_configured():
            return None
        if self._drive_client is None:
            self._drive_client = self._build_drive()
        return self._drive_client

    def _menu_test_drive(self):
        if not self._drive_lib_ok():
            return
        if not self._drive_configured():
            messagebox.showwarning(
                "Google Drive",
                "ยังไม่ได้ผูกบัญชี\nไปที่ ตั้งค่า > ตั้งค่า Google Drive — บัญชีส่วนตัว (OAuth)")
            return
        self.dash_status.configure(text="กำลังทดสอบการเชื่อมต่อ Google Drive…")

        def work():
            self._drive_client = None
            return self._get_drive().check()

        def done(email, err):
            if err is not None:
                self._drive_client = None
                self.dash_status.configure(text="เชื่อมต่อ Google Drive ไม่สำเร็จ")
                messagebox.showerror(
                    "เชื่อมต่อ Google Drive ไม่ได้",
                    "ส่งข้อมูลไป Google Drive ไม่ได้ กรุณาผูกบัญชีใหม่\n"
                    "(ตั้งค่า > ตั้งค่า Google Drive — บัญชีส่วนตัว (OAuth))\n\n"
                    f"รายละเอียด: {err}")
            else:
                self.dash_status.configure(text="✓ เชื่อมต่อ Google Drive สำเร็จ")
                messagebox.showinfo("Google Drive",
                                    f"เชื่อมต่อสำเร็จ ✔\nบัญชี: {email}")

        self._run_bg(work, done)

    # ---- menu: output folder ------------------------------------------
    def _menu_set_outdir(self):
        d = filedialog.askdirectory(
            title="เลือกโฟลเดอร์สำหรับเก็บไฟล์ที่เข้ารหัส / Choose encrypted-output folder")
        if not d:
            return
        self.enc_out_dir = d
        self.settings["enc_out_dir"] = d
        self._save_settings()
        messagebox.showinfo("Output folder set",
                            f"ไฟล์ที่เข้ารหัสจะถูกบันทึกไว้ที่:\n{d}")

    def _menu_show_outdir(self):
        """Open the encrypted-output folder in File Explorer."""
        if not self.enc_out_dir:
            if messagebox.askyesno(
                    "Output folder",
                    "ยังไม่ได้กำหนดโฟลเดอร์ปลายทาง\nต้องการกำหนดตอนนี้ไหม?"):
                self._menu_set_outdir()
            return
        path = Path(self.enc_out_dir)
        if not path.is_dir():
            if messagebox.askyesno(
                    "Output folder",
                    f"ไม่พบโฟลเดอร์ปลายทางเดิม:\n{self.enc_out_dir}\n\n"
                    f"โฟลเดอร์อาจถูกย้ายหรือลบ — ต้องการกำหนดโฟลเดอร์ใหม่ตอนนี้ไหม?"):
                self._menu_set_outdir()
            return
        self._open_in_explorer(path)

    @staticmethod
    def _open_in_explorer(path: Path) -> None:
        """Open a folder in the system file manager."""
        try:
            os.startfile(str(path))            # Windows
        except AttributeError:                 # non-Windows fallback
            import subprocess, sys
            subprocess.Popen(
                (["open", str(path)] if sys.platform == "darwin"
                 else ["xdg-open", str(path)]))
        except Exception as exc:
            messagebox.showerror("Open folder", f"เปิดโฟลเดอร์ไม่ได้:\n{exc}")

    def _menu_export_portable(self):
        """Build a clean, shareable copy of the program (no vault / token /
        settings) so it can be given to another machine, independent of this one."""
        parent = filedialog.askdirectory(
            title="จะบันทึกชุดแจกจ่ายไว้ที่ไหน / Save the portable copy to…",
            initialdir=str(_APP_DIR.parent))
        if not parent:
            return
        self.dash_status.configure(text="กำลังสร้างชุดแจกจ่าย…")

        def work():
            return make_portable.build_portable(
                src_dir=str(_APP_DIR), out_parent=parent, make_zip=True)

        def after(info, err):
            if err is not None:
                self.dash_status.configure(text="สร้างชุดแจกจ่ายไม่สำเร็จ")
                messagebox.showerror("Export portable", str(err))
                return
            self.dash_status.configure(text="✓ สร้างชุดแจกจ่ายแล้ว")
            n = len(info["copied"])
            warn = ("\n\n⚠️ ตรวจพบและลบไฟล์ลับที่หลุดเข้ามา: "
                    + ", ".join(info["leaked"])) if info["leaked"] else ""
            self._show_success(
                "สร้างชุดแจกจ่ายสำเร็จ",
                f"คัดลอกโปรแกรม {n} รายการ (ไม่รวม vault/บัญชี/การตั้งค่าของคุณ)\n\n"
                f"โฟลเดอร์:\n{info['folder']}\n\n"
                f"ไฟล์ zip สำหรับส่ง:\n{info['zip']}\n\n"
                f"เครื่องปลายทางจะสร้าง vault และกุญแจของตัวเองใหม่ตอน login ครั้งแรก"
                f"{warn}")
            try:
                self._open_in_explorer(Path(info["folder"]).parent)
            except Exception:
                pass

        self._run_bg(work, after)

    def _ensure_out_dir(self) -> str | None:
        """Return the configured output folder, asking once if unset."""
        if self.enc_out_dir and Path(self.enc_out_dir).is_dir():
            return self.enc_out_dir
        d = filedialog.askdirectory(
            title="เลือกโฟลเดอร์สำหรับเก็บไฟล์ที่เข้ารหัส / Choose output folder")
        if not d:
            return None
        self.enc_out_dir = d
        self.settings["enc_out_dir"] = d
        self._save_settings()
        return d

    # ---- menu: encrypt files to a folder (originals kept) -------------
    def _pick_recipients(self):
        """Modal checkbox dialog to choose which contacts to seal to.
        Returns a list of public-key bytes, or None if cancelled."""
        win = ctk.CTkToplevel(self)
        win.title("เลือกผู้รับ (Select recipients)")
        win.geometry("460x440")
        win.configure(fg_color="#141414")
        ctk.CTkLabel(win, text="เข้ารหัสไฟล์นี้ถึงใคร (ผู้รับถอดได้โดยไม่ต้องใช้รหัส)",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#f2f4f7").pack(pady=(14, 6))
        listframe = ctk.CTkScrollableFrame(win, height=260, fg_color="#171717")
        listframe.pack(fill="both", expand=True, padx=14, pady=4)
        vars_ = []
        for c in self.contacts:
            v = ctk.StringVar(value="on")
            try:
                fp = recipient_crypto.fingerprint(recipient_crypto.decode_public(c["pk"]))
            except Exception:
                fp = "??"
            ctk.CTkCheckBox(listframe, text=f"{c.get('name','(ไม่มีชื่อ)')}   [{fp}]",
                            variable=v, onvalue="on", offvalue="off",
                            text_color="#f2f4f7").pack(anchor="w", pady=4, padx=6)
            vars_.append((v, c))

        result = {"pubs": None}

        def confirm():
            pubs = []
            for v, c in vars_:
                if v.get() == "on":
                    try:
                        pubs.append(recipient_crypto.decode_public(c["pk"]))
                    except Exception:
                        pass
            result["pubs"] = pubs
            win.destroy()

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(4, 12))
        ctk.CTkButton(btns, text="ยกเลิก", width=120, fg_color="gray30",
                      command=win.destroy).pack(side="left")
        ctk.CTkButton(btns, text="เข้ารหัส", width=160,
                      command=confirm).pack(side="right")
        try:
            win.transient(self); win.grab_set(); win.lift()
            self.wait_window(win)
        except Exception:
            pass
        return result["pubs"]

    def _menu_encrypt(self):
        if not self.password:
            messagebox.showwarning("Locked", "Please log in first.")
            return
        # Prefer files dropped into the Drag & drop area; otherwise ask.
        if self.pending_files:
            srcs = list(self.pending_files)
        else:
            srcs = filedialog.askopenfilenames(
                title="เลือกไฟล์ที่จะเข้ารหัส / Select files to encrypt")
            if not srcs:
                return
            srcs = list(srcs)
        out_dir = self._ensure_out_dir()
        if not out_dir:
            return

        online = (self.net_mode == "Online")
        if online and not self._drive_configured():
            messagebox.showwarning(
                "Online mode",
                "โหมด Online ต้องตั้งค่า Google Drive ก่อน\n"
                "ไปที่ ตั้งค่า > ตั้งค่า Google Drive — บัญชีส่วนตัว (OAuth) (หรือเลือก Offline)")
            return

        # recipient-key mode: pick which contacts to seal to (no password needed
        # by the recipient). Done on the main thread BEFORE the worker starts.
        recipients = None
        if self.send_mode == "recipient":
            if not self.contacts:
                messagebox.showwarning(
                    "ยังไม่มีผู้รับ",
                    "โหมด 'ถึงผู้รับ (recipient-key)' ต้องเพิ่ม public key ของผู้รับก่อน\n"
                    "ไปที่ ตั้งค่า > รายชื่อผู้รับ (Contacts) — หรือสลับกลับเป็นโหมดรหัสผ่าน")
                return
            recipients = self._pick_recipients()
            if recipients is None:        # cancelled
                return
            if not recipients:
                messagebox.showwarning("เลือกผู้รับ", "กรุณาเลือกผู้รับอย่างน้อย 1 คน")
                return

        self.dash_status.configure(
            text=("กำลังอัปโหลดขึ้น Google Drive…" if online else "กำลังเข้ารหัส…"))
        pw = self.password
        fmt = self.out_format
        emails = list(self.allowed_emails)
        public = self.online_public
        setup = self._build_setup() if online else None
        encrypt = (pdf_disguise.encrypt_file_to_jpg if fmt == "JPG"
                   else pdf_disguise.encrypt_file_to_pdf)

        def work():
            drive = None
            if online:
                drive = self._get_drive()   # built here (may open browser once)
                drive.check()               # verify reachable before sending
            done, failed = [], []
            for s in srcs:
                try:
                    done.append(encrypt(s, out_dir, pw, online=online, drive=drive,
                                        allowed_emails=emails, public=public,
                                        setup=setup, recipients=recipients))
                except Exception as exc:
                    failed.append(f"{Path(s).name}: {exc}")
            return done, failed

        def after(res, err):
            if err is not None:
                if online:
                    self.dash_status.configure(text="ส่ง Google Drive ไม่ได้")
                    messagebox.showerror(
                        "เชื่อมต่อ Google Drive ไม่ได้",
                        "ส่งข้อมูลไป Google Drive ไม่ได้ กรุณาผูก API ใหม่\n"
                        "(ตั้งค่า > ตั้งค่า Google Drive API…) หรือสลับเป็นโหมด Offline\n\n"
                        f"รายละเอียด: {err}")
                else:
                    self.dash_status.configure(text="เข้ารหัสล้มเหลว")
                    messagebox.showerror("Encrypt failed", str(err))
                return
            self._encrypt_done(res[0], res[1], out_dir)

        self._run_bg(work, after)

    def _encrypt_done(self, done, failed, out_dir):
        self._clear_pending()     # dropped files have been handled
        fmt = self.out_format
        online = (self.net_mode == "Online")
        mode_txt = ("Online — ข้อมูลถูกอัปโหลดขึ้น Google Drive, ไฟล์ "
                    f"{fmt} นี้มีเพียงลิงก์ที่ซ่อนไว้ (เล็ก)") if online else \
                   f"Offline — ข้อมูลฝังอยู่ในไฟล์ {fmt} (ขนาดจริง)"
        self.dash_status.configure(
            text=f"✓ เข้ารหัสแล้ว {len(done)} ไฟล์ [{self.net_mode}]")
        msg = (f"เข้ารหัส {len(done)} ไฟล์ เป็นไฟล์ {fmt} (ดูเหมือนข้อพระคัมภีร์)\n"
               f"โหมด: {mode_txt}\n\nบันทึกไว้ที่:\n{out_dir}\n\n"
               f"ไฟล์ต้นฉบับไม่ถูกลบ ยังใช้งานได้ตามปกติ\n"
               f"นำไฟล์ {fmt} เหล่านี้กลับมากด 'ถอดรหัสไฟล์' เพื่อได้ไฟล์เดิมคืน")
        if failed:
            msg += "\n\nทำไม่สำเร็จ:\n" + "\n".join(failed)
            messagebox.showwarning(f"Encrypted to {fmt}", msg)
        else:
            self._show_success("เข้ารหัสสำเร็จ", msg)

    # ---- menu: decrypt files back to usable originals -----------------
    def _menu_decrypt(self):
        if not self.password:
            messagebox.showwarning("Locked", "Please log in first.")
            return
        # Prefer files dropped into the Drag & drop area; otherwise ask.
        if self.pending_files:
            encs = list(self.pending_files)
        else:
            encs = filedialog.askopenfilenames(
                title="เลือกไฟล์ PDF / JPG / .enc ที่จะถอดรหัส / Select files to decrypt",
                filetypes=[("PDF / JPG / encrypted", "*.pdf *.jpg *.jpeg *.enc"),
                           ("PDF files", "*.pdf"),
                           ("JPG images", "*.jpg *.jpeg"),
                           ("Encrypted files", "*.enc"),
                           ("All files", "*.*")])
            if not encs:
                return
        out_dir = filedialog.askdirectory(
            title="บันทึกไฟล์ที่ถอดรหัสไว้ที่ไหน / Restore decrypted files to…")
        if not out_dir:
            return

        self.dash_status.configure(text="กำลังถอดรหัส… / decrypting…")
        pw, encs = self.password, list(encs)
        # our private key unlocks recipient-key files sent TO us (no password).
        try:
            priv = self.ov.identity()[0]
        except Exception:
            priv = None

        def work():
            # auto-configure from any bundled setup so this machine can receive
            # (and later send) without manual Google Drive setup
            for e in encs:
                s = pdf_disguise.peek_setup(e)
                if s:
                    self._install_setup(s)
                    break
            # built lazily; only needed if a file turns out to be an online pointer
            drive = self._get_drive()
            done, failed = [], []
            for e in encs:
                try:
                    low = str(e).lower()
                    # detect by content/extension: disguise JPG, disguise PDF, else .enc
                    if low.endswith((".jpg", ".jpeg")) or pdf_disguise.is_disguise_jpg(e):
                        done.append(pdf_disguise.decrypt_jpg_to_folder(
                            e, out_dir, pw, drive=drive, private_key=priv))
                    elif low.endswith(".pdf") or pdf_disguise.is_disguise_pdf(e):
                        done.append(pdf_disguise.decrypt_pdf_to_folder(
                            e, out_dir, pw, drive=drive, private_key=priv))
                    else:
                        done.append(file_crypto.decrypt_file_to_folder(e, out_dir, pw))
                except Exception as exc:
                    reason = ("รหัสผ่านไม่ตรงกับไฟล์นี้ หรือไฟล์เสียหาย"
                              if type(exc).__name__ == "InvalidTag"
                              else str(exc))
                    failed.append(f"{Path(e).name}: {reason}")
            return done, failed

        def after(res, err):
            if err is not None:
                self.dash_status.configure(text="ถอดรหัสล้มเหลว")
                messagebox.showerror("Decrypt failed", str(err))
                return
            self._decrypt_done(res[0], res[1], out_dir)

        self._run_bg(work, after)

    def _decrypt_done(self, done, failed, out_dir):
        self._clear_pending()     # dropped files have been handled
        self.dash_status.configure(text=f"✓ ถอดรหัสแล้ว {len(done)} ไฟล์")
        if failed:
            msg = (f"ถอดรหัสสำเร็จ {len(done)} ไฟล์ ไว้ที่:\n{out_dir}"
                   if done else "ไม่มีไฟล์ที่ถอดรหัสสำเร็จ")
            msg += "\n\nทำไม่สำเร็จ:\n" + "\n".join(failed)
            messagebox.showwarning("Decrypted", msg)
        else:
            self._show_success("ถอดรหัสสำเร็จ",
                               f"ถอดรหัสคืนสภาพ {len(done)} ไฟล์ ไว้ที่:\n{out_dir}")


def main():
    app = VaultApp()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # If launched by double-click there is no console to read; log the
        # traceback to a file and show it, so the error is never lost.
        import traceback
        tb = traceback.format_exc()
        try:
            Path("error.log").write_text(tb, "utf-8")
        except Exception:
            pass
        try:
            from tkinter import Tk, messagebox
            r = Tk(); r.withdraw()
            messagebox.showerror("Document Organizer failed to start", tb)
            r.destroy()
        except Exception:
            try:
                print(tb)      # may be a no-op under pythonw (no console)
            except Exception:
                pass
        raise
