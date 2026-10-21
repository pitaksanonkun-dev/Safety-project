"""
health_gate.py — an innocent "Health & Wellness" tracker that doubles as a
side-channel launcher for the real vault (gui.VaultApp).

It looks and works like an ordinary habit tracker (water intake with a full
day/time log, an intermittent-fasting timer, a routine checklist, settings).
A hidden path opens the vault:

  In the Water Tracker, type the SECRET_TRIGGER value as the amount and press
  "บันทึก". Instead of logging, a perfectly ordinary-looking confirmation appears
  ("ปริมาณสูงผิดปกติ / รูปแบบไม่ถูกต้อง — ยืนยันหรือไม่?") with a small password
  field. The correct UNLOCK_PASSWORD there opens the vault. Any other value just
  logs water normally, so nothing hints that a hidden system exists (plausible
  deniability / duress-resistant).

This disguise impersonates no one and collects no credentials under false
pretenses — it only guards the user's OWN data. Point the launcher at this file
(e.g. _launch.bat / the .vbs / the .exe build) to use it as the front door.

Dependencies: customtkinter
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import customtkinter as ctk

import app_paths
import hidden_config

# --- configure these two secrets --------------------------------------------
SECRET_TRIGGER = "7749"          # type this as the water amount to arm the prompt
UNLOCK_PASSWORD = "open-sesame"  # entered in the confirmation dialog to open vault
# ----------------------------------------------------------------------------

DATA_PATH = app_paths.state_dir() / "health_data.json"
EAT_START, EAT_END = 7, 14        # eating window 07:00–14:00 (IF 17:7)

# --- modern dark palette ----------------------------------------------------
BG, CARD, ROW = "#0f1115", "#191c23", "#20242d"
STROKE = "#2a2f3a"
TEXT, MUTED = "#e6eaf0", "#8a93a3"
ACCENT, ACCENT_D = "#38bdf8", "#0ea5e9"      # water blue
TEAL, GREEN, AMBER, RED = "#2dd4bf", "#34d399", "#fbbf24", "#f05252"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DEFAULT_CHECKLIST = [
    "วิ่ง Zone 2 ~30 นาที",
    "เวย์โปรตีน + อัลมอนด์",
    "มาสก์หน้า (จันทร์ / พฤหัส)",
    "ดื่มน้ำครบเป้าหมาย",
    "นอนก่อน 23:00 น.",
]


# ---- pure logic (unit-testable without a GUI) ------------------------------
# If the secret channel was configured from the vault menu (stored as hashes),
# use that; otherwise fall back to the constants above.
def is_trigger(text: str) -> bool:
    r = hidden_config.verify_trigger(text)
    if r is None:
        return (text or "").strip() == SECRET_TRIGGER
    return r


def check_unlock(password: str) -> bool:
    r = hidden_config.verify_unlock(password)
    if r is None:
        return (password or "") == UNLOCK_PASSWORD
    return r


# ---- storage ---------------------------------------------------------------
def _load() -> dict:
    try:
        d = json.loads(DATA_PATH.read_text("utf-8"))
    except Exception:
        d = {}
    d.setdefault("water_goal", 2000)
    d.setdefault("water_log", [])           # [{"ts": "YYYY-MM-DD HH:MM", "ml": int}]
    d.setdefault("fast_day", "")
    d.setdefault("checklist", {k: False for k in DEFAULT_CHECKLIST})
    d.setdefault("sound", True)
    # migrate an old single-total field into one log entry for today
    if d.get("water_ml") and not d["water_log"]:
        d["water_log"].append(
            {"ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "ml": int(d["water_ml"])})
    d.pop("water_ml", None)
    return d


def _save(d: dict) -> None:
    try:
        DATA_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _font(size=14, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


class HealthApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Health & Wellness")
        self.geometry("480x720")
        self.minsize(440, 620)
        self.configure(fg_color=BG)
        self.data = _load()
        self._open_vault = False       # set True to launch the vault on close

        # header band
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 2))
        ctk.CTkLabel(head, text="🌿  Health & Wellness",
                     font=_font(20, "bold"), text_color=TEXT).pack(side="left")
        self.today_pill = ctk.CTkLabel(
            head, text=datetime.now().strftime("%d %b %Y"), font=_font(12),
            text_color=MUTED)
        self.today_pill.pack(side="right", pady=4)

        self.tabs = ctk.CTkTabview(
            self, fg_color=BG, segmented_button_fg_color=CARD,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_D,
            segmented_button_unselected_color=CARD, text_color=TEXT)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=8)
        for name in ("หน้าหลัก", "ดื่มน้ำ", "อดอาหาร", "เช็คลิสต์", "ตั้งค่า"):
            self.tabs.add(name)

        self._build_dashboard(self.tabs.tab("หน้าหลัก"))
        self._build_water(self.tabs.tab("ดื่มน้ำ"))
        self._build_fasting(self.tabs.tab("อดอาหาร"))
        self._build_checklist(self.tabs.tab("เช็คลิสต์"))
        self._build_settings(self.tabs.tab("ตั้งค่า"))

        self._tick()                   # start the fasting clock

    # ---- small UI helpers -------------------------------------------
    def _card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16,
                            border_width=1, border_color=STROKE, **kw)

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    # ---- Dashboard --------------------------------------------------
    def _build_dashboard(self, tab):
        tab.configure(fg_color=BG)
        ctk.CTkLabel(tab, text="ภาพรวมวันนี้", font=_font(17, "bold"),
                     text_color=TEXT).pack(pady=(14, 8), anchor="w", padx=6)

        ring_card = self._card(tab)
        ring_card.pack(fill="x", padx=4, pady=6)
        self.ring = ctk.CTkCanvas(ring_card, width=190, height=190,
                                  highlightthickness=0, bg=CARD)
        self.ring.pack(pady=(16, 4))
        self.dash_pct = ctk.CTkLabel(ring_card, text="", font=_font(14),
                                     text_color=MUTED)
        self.dash_pct.pack(pady=(0, 16))

        self.dash_rows = ctk.CTkFrame(tab, fg_color="transparent")
        self.dash_rows.pack(fill="x", padx=4, pady=6)
        self._refresh_dashboard()

    def _refresh_dashboard(self):
        goal = max(1, int(self.data["water_goal"]))
        total = self._wtotal(self._today())
        pct = min(1.0, total / goal)
        self.ring.delete("all")
        self.ring.create_oval(22, 22, 168, 168, outline="#2a2f3a", width=16)
        if pct > 0:
            self.ring.create_arc(22, 22, 168, 168, start=90, extent=-359.9 * pct,
                                 style="arc", outline=ACCENT, width=16)
        self.ring.create_text(95, 88, text=f"{int(pct*100)}%", fill=TEXT,
                              font=("Segoe UI", 30, "bold"))
        self.ring.create_text(95, 118, text="ของเป้าหมาย", fill=MUTED,
                              font=("Segoe UI", 10))
        self.dash_pct.configure(text=f"💧 {total} / {goal} ml")

        for w in self.dash_rows.winfo_children():
            w.destroy()
        done = sum(1 for v in self.data["checklist"].values() if v)
        total_chk = len(self.data["checklist"])
        state = "ช่วงอดอาหาร" if self._is_fasting() else "ช่วงทานอาหารได้"
        cards = [("✅", "กิจวัตรสำเร็จ", f"{done}/{total_chk}", GREEN),
                 ("⏱", "สถานะ IF", state, AMBER if self._is_fasting() else TEAL)]
        for icon, label, val, col in cards:
            c = self._card(self.dash_rows)
            c.pack(fill="x", pady=5)
            ctk.CTkLabel(c, text=icon, font=_font(20)).pack(side="left", padx=(14, 6), pady=12)
            ctk.CTkLabel(c, text=label, font=_font(13), text_color=MUTED).pack(
                side="left", pady=12)
            ctk.CTkLabel(c, text=val, font=_font(14, "bold"), text_color=col).pack(
                side="right", padx=14)

    # ---- Water Tracker (holds the hidden channel) -------------------
    def _build_water(self, tab):
        tab.configure(fg_color=BG)
        self.view_date = ctk.StringVar(value=self._today())

        title = ctk.CTkFrame(tab, fg_color="transparent")
        title.pack(fill="x", padx=4, pady=(12, 6))
        glass = ctk.CTkLabel(title, text="💧 บันทึกการดื่มน้ำ", font=_font(17, "bold"),
                             text_color=TEXT)
        glass.pack(side="left")

        # date navigator ------------------------------------------------
        nav = self._card(tab)
        nav.pack(fill="x", padx=4, pady=6)
        ctk.CTkButton(nav, text="◀", width=38, fg_color=ROW, hover_color=STROKE,
                      command=lambda: self._shift_day(-1)).pack(side="left", padx=(10, 6), pady=10)
        self.date_entry = ctk.CTkEntry(nav, textvariable=self.view_date, width=130,
                                       justify="center", fg_color=ROW, border_color=STROKE)
        self.date_entry.pack(side="left", padx=4, pady=10)
        self.date_entry.bind("<Return>", lambda _e: self._refresh_water())
        ctk.CTkButton(nav, text="▶", width=38, fg_color=ROW, hover_color=STROKE,
                      command=lambda: self._shift_day(1)).pack(side="left", padx=6, pady=10)
        ctk.CTkButton(nav, text="วันนี้", width=60, fg_color=ROW, hover_color=STROKE,
                      command=self._set_today).pack(side="right", padx=10, pady=10)

        # total + progress (double-click here opens the hidden prompt) ---
        prog = self._card(tab)
        prog.pack(fill="x", padx=4, pady=6)
        self.water_total_lbl = ctk.CTkLabel(prog, text="", font=_font(22, "bold"),
                                            text_color=ACCENT)
        self.water_total_lbl.pack(pady=(14, 2))
        self.water_total_lbl.bind("<Double-Button-1>", lambda _e: self._armed_dialog())
        self.water_goal_lbl = ctk.CTkLabel(prog, text="", font=_font(12), text_color=MUTED)
        self.water_goal_lbl.pack()
        self.water_goal_lbl.bind("<Double-Button-1>", lambda _e: self._armed_dialog())
        self.water_bar = ctk.CTkProgressBar(prog, width=360, progress_color=ACCENT)
        self.water_bar.pack(pady=(10, 16))

        # add entry: time + amount -------------------------------------
        add = self._card(tab)
        add.pack(fill="x", padx=4, pady=6)
        rowf = ctk.CTkFrame(add, fg_color="transparent")
        rowf.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(rowf, text="เวลา", font=_font(12), text_color=MUTED).pack(side="left")
        self.time_entry = ctk.CTkEntry(rowf, width=70, justify="center", fg_color=ROW,
                                       border_color=STROKE)
        self.time_entry.insert(0, datetime.now().strftime("%H:%M"))
        self.time_entry.pack(side="left", padx=6)
        self.water_entry = ctk.CTkEntry(rowf, width=90, placeholder_text="ml",
                                        fg_color=ROW, border_color=STROKE)
        self.water_entry.pack(side="left", padx=6)
        self.water_entry.bind("<Return>", lambda _e: self._log_water())
        ctk.CTkButton(rowf, text="+ บันทึก", width=84, fg_color=ACCENT,
                      hover_color=ACCENT_D, command=self._log_water).pack(side="right")
        chips = ctk.CTkFrame(add, fg_color="transparent")
        chips.pack(fill="x", padx=12, pady=(2, 12))
        for amt in (150, 250, 500):
            ctk.CTkButton(chips, text=f"+{amt}", width=70, height=28, fg_color=ROW,
                          hover_color=STROKE, text_color=TEXT,
                          command=lambda a=amt: self._quick_add(a)).pack(side="left", padx=4)

        # history list (per-entry delete) ------------------------------
        ctk.CTkLabel(tab, text="ประวัติวันนี้", font=_font(13, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=10, pady=(6, 0))
        self.hist = ctk.CTkScrollableFrame(tab, fg_color=CARD, corner_radius=14,
                                           height=150)
        self.hist.pack(fill="both", expand=True, padx=4, pady=(4, 2))
        self.water_status = ctk.CTkLabel(tab, text="", text_color=GREEN, font=_font(12))
        self.water_status.pack(pady=(0, 6))
        self._refresh_water()

    # ---- water helpers ----------------------------------------------
    def _wtotal(self, date_str: str) -> int:
        return sum(int(e.get("ml", 0)) for e in self.data["water_log"]
                   if str(e.get("ts", "")).startswith(date_str))

    def _entries_for(self, date_str: str):
        items = [e for e in self.data["water_log"]
                 if str(e.get("ts", "")).startswith(date_str)]
        items.sort(key=lambda e: e.get("ts", ""))
        return items

    def _shift_day(self, delta: int):
        try:
            d = datetime.strptime(self.view_date.get().strip(), "%Y-%m-%d")
        except Exception:
            d = datetime.now()
        self.view_date.set((d + timedelta(days=delta)).strftime("%Y-%m-%d"))
        self._refresh_water()

    def _set_today(self):
        self.view_date.set(self._today())
        self._refresh_water()

    def _refresh_water(self):
        date_str = self.view_date.get().strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            self.water_status.configure(text="รูปแบบวันที่ควรเป็น YYYY-MM-DD", text_color=AMBER)
            return
        goal = max(1, int(self.data["water_goal"]))
        total = self._wtotal(date_str)
        self.water_total_lbl.configure(text=f"{total} ml")
        self.water_goal_lbl.configure(text=f"เป้าหมาย {goal} ml  •  {int(min(1.0,total/goal)*100)}%")
        self.water_bar.set(min(1.0, total / goal))
        for w in self.hist.winfo_children():
            w.destroy()
        entries = self._entries_for(date_str)
        if not entries:
            ctk.CTkLabel(self.hist, text="(ยังไม่มีรายการในวันนี้)",
                         text_color=MUTED).pack(pady=14)
        for e in entries:
            t = str(e.get("ts", ""))[11:16] or "--:--"
            row = ctk.CTkFrame(self.hist, fg_color=ROW, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            ctk.CTkLabel(row, text=f"⏱ {t}", font=_font(12), text_color=MUTED).pack(
                side="left", padx=(12, 8), pady=8)
            ctk.CTkLabel(row, text=f"{int(e.get('ml',0))} ml", font=_font(13, "bold"),
                         text_color=TEXT).pack(side="left")
            ctk.CTkButton(row, text="ลบ", width=46, height=26, fg_color="#3a2326",
                          hover_color=RED, text_color="#f3b4b4",
                          command=lambda x=e: self._delete_entry(x)).pack(
                side="right", padx=8, pady=6)

    def _add_entry(self, date_str: str, time_str: str, ml: int):
        ts = f"{date_str} {time_str}"
        self.data["water_log"].append({"ts": ts, "ml": int(ml)})
        _save(self.data)
        self._refresh_water()
        self._refresh_dashboard()
        self.water_status.configure(text=f"บันทึก {ml} ml เวลา {time_str}", text_color=GREEN)

    def _quick_add(self, ml: int):
        now = datetime.now()
        self._add_entry(self.view_date.get().strip() or self._today(),
                        now.strftime("%H:%M"), ml)

    def _log_water(self):
        text = self.water_entry.get().strip()
        self.water_entry.delete(0, "end")
        if is_trigger(text):               # hidden channel armed
            self._armed_dialog()
            return
        date_str = self.view_date.get().strip()
        time_str = self.time_entry.get().strip() or datetime.now().strftime("%H:%M")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            datetime.strptime(time_str, "%H:%M")
            ml = int(float(text))
            if ml <= 0:
                raise ValueError
        except Exception:
            self.water_status.configure(
                text="ตรวจสอบ วันที่ (YYYY-MM-DD), เวลา (HH:MM) และจำนวน ml", text_color=AMBER)
            return
        self._add_entry(date_str, time_str, ml)

    def _delete_entry(self, entry):
        self.data["water_log"] = [e for e in self.data["water_log"] if e is not entry]
        _save(self.data)
        self._refresh_water()
        self._refresh_dashboard()
        self.water_status.configure(text="ลบรายการแล้ว", text_color=MUTED)

    def _armed_dialog(self):
        """Innocent-looking confirmation that hides a password field. Correct
        password -> open the vault; anything else -> behave as a normal app."""
        win = ctk.CTkToplevel(self)
        win.title("ยืนยันการบันทึก")
        win.geometry("390x260")
        win.configure(fg_color=CARD)
        ctk.CTkLabel(win, text="⚠️ ตรวจพบความผิดปกติ", font=_font(15, "bold"),
                     text_color=AMBER).pack(pady=(18, 4))
        ctk.CTkLabel(win, text="ปริมาณการดื่มน้ำสูงผิดปกติ หรือรูปแบบไม่ถูกต้อง\n"
                               "ต้องการยืนยันการบันทึกหรือไม่?",
                     text_color=TEXT, justify="center").pack(pady=(0, 10), padx=14)
        pw = ctk.CTkEntry(win, width=240, show="•", fg_color=ROW, border_color=STROKE,
                          placeholder_text="รหัสยืนยัน (ถ้ามี)")
        pw.pack(pady=4)
        pw.focus()

        def confirm():
            val = pw.get()
            win.destroy()
            if check_unlock(val):
                self._launch_vault()
            else:
                self.water_status.configure(text="ยกเลิกการบันทึกรายการนี้", text_color=MUTED)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=16)
        ctk.CTkButton(btns, text="ยกเลิก", width=100, fg_color=ROW, hover_color=STROKE,
                      command=win.destroy).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="ยืนยัน", width=120, fg_color=ACCENT,
                      hover_color=ACCENT_D, command=confirm).pack(side="left", padx=6)
        pw.bind("<Return>", lambda _e: confirm())
        try:
            win.transient(self); win.grab_set(); win.lift()
        except Exception:
            pass

    def _launch_vault(self):
        self._open_vault = True        # main() opens the real vault after close
        self.destroy()

    # ---- Fasting timer ---------------------------------------------
    def _build_fasting(self, tab):
        tab.configure(fg_color=BG)
        ctk.CTkLabel(tab, text="⏱ Intermittent Fasting (17:7)", font=_font(17, "bold"),
                     text_color=TEXT).pack(pady=(14, 2), anchor="w", padx=6)
        card = self._card(tab)
        card.pack(fill="x", padx=4, pady=10)
        ctk.CTkLabel(card, text=f"ช่วงทานอาหาร  {EAT_START:02d}:00 – {EAT_END:02d}:00 น.",
                     text_color=MUTED, font=_font(12)).pack(pady=(16, 6))
        self.fast_state = ctk.CTkLabel(card, text="", font=_font(16, "bold"))
        self.fast_state.pack()
        self.fast_count = ctk.CTkLabel(card, text="", font=_font(40, "bold"),
                                       text_color=TEXT)
        self.fast_count.pack(pady=8)
        self.fast_hint = ctk.CTkLabel(card, text="", text_color=MUTED, font=_font(12))
        self.fast_hint.pack(pady=(0, 18))

    def _is_fasting(self) -> bool:
        h = datetime.now().hour
        return not (EAT_START <= h < EAT_END)

    def _tick(self):
        now = datetime.now()
        if self._is_fasting():
            nxt = now.replace(hour=EAT_START, minute=0, second=0, microsecond=0)
            if now.hour >= EAT_END:
                nxt += timedelta(days=1)
            state, color, hint = "กำลังอดอาหาร", AMBER, "เหลือเวลาถึงช่วงทานอาหาร"
        else:
            nxt = now.replace(hour=EAT_END, minute=0, second=0, microsecond=0)
            state, color, hint = "ทานอาหารได้", GREEN, "เหลือเวลาในช่วงทานอาหาร"
        rem = nxt - now
        hh, r = divmod(int(rem.total_seconds()), 3600)
        mm, ss = divmod(r, 60)
        if hasattr(self, "fast_state"):
            self.fast_state.configure(text=state, text_color=color)
            self.fast_count.configure(text=f"{hh:02d}:{mm:02d}:{ss:02d}")
            self.fast_hint.configure(text=hint)
        try:
            self.after(1000, self._tick)
        except Exception:
            pass

    # ---- Checklist --------------------------------------------------
    def _build_checklist(self, tab):
        tab.configure(fg_color=BG)
        ctk.CTkLabel(tab, text="✅ กิจวัตรสุขภาพประจำวัน", font=_font(17, "bold"),
                     text_color=TEXT).pack(pady=(14, 8), anchor="w", padx=6)
        card = self._card(tab)
        card.pack(fill="both", expand=True, padx=4, pady=6)
        self._chk_vars = {}
        for item in self.data["checklist"]:
            v = ctk.StringVar(value="on" if self.data["checklist"][item] else "off")
            self._chk_vars[item] = v
            ctk.CTkCheckBox(card, text=item, variable=v, onvalue="on", offvalue="off",
                            fg_color=ACCENT, hover_color=ACCENT_D, text_color=TEXT,
                            command=lambda i=item: self._toggle_chk(i)).pack(
                anchor="w", padx=22, pady=10)

    def _toggle_chk(self, item):
        self.data["checklist"][item] = (self._chk_vars[item].get() == "on")
        _save(self.data)
        self._refresh_dashboard()

    # ---- Settings (holds the safe panic reset) ---------------------
    def _build_settings(self, tab):
        tab.configure(fg_color=BG)
        ctk.CTkLabel(tab, text="⚙ การตั้งค่า", font=_font(17, "bold"),
                     text_color=TEXT).pack(pady=(14, 8), anchor="w", padx=6)
        card = self._card(tab)
        card.pack(fill="x", padx=4, pady=6)
        snd = ctk.StringVar(value="on" if self.data["sound"] else "off")

        def toggle_sound():
            self.data["sound"] = (snd.get() == "on")
            _save(self.data)
        ctk.CTkSwitch(card, text="เสียงแจ้งเตือน", variable=snd, onvalue="on",
                      offvalue="off", progress_color=ACCENT, text_color=TEXT,
                      command=toggle_sound).pack(anchor="w", padx=20, pady=14)
        ctk.CTkLabel(card, text="ธีม", text_color=MUTED, font=_font(12)).pack(
            anchor="w", padx=20, pady=(2, 0))
        ctk.CTkSegmentedButton(card, values=["มืด", "สว่าง"],
                               selected_color=ACCENT,
                               command=lambda v: ctk.set_appearance_mode(
                                   "light" if v == "สว่าง" else "dark")).pack(
            anchor="w", padx=20, pady=(2, 16))

        ctk.CTkLabel(tab, text="เขตอันตราย", text_color=MUTED, font=_font(12)).pack(
            anchor="w", padx=10, pady=(10, 0))
        dz = self._card(tab)
        dz.pack(fill="x", padx=4, pady=6)
        ctk.CTkLabel(dz, text="ล้างข้อมูลสุขภาพทั้งหมดในเครื่องนี้",
                     text_color=MUTED, font=_font(12)).pack(side="left", padx=14, pady=14)
        ctk.CTkButton(dz, text="Reset Data", width=110, fg_color=RED,
                      hover_color="#c0392b", command=self._reset_data).pack(
            side="right", padx=12, pady=12)

    def _reset_data(self):
        """Face value: wipe the health tracker data. Hidden safety: also sign out
        of Google Drive (drop the cached token) so the vault's online access is
        cut immediately. It deliberately does NOT touch or destroy the vault
        itself — the data stays encrypted and recoverable with your password."""
        self.data = {"water_goal": self.data.get("water_goal", 2000),
                     "water_log": [], "fast_day": "",
                     "checklist": {k: False for k in DEFAULT_CHECKLIST},
                     "sound": self.data.get("sound", True)}
        _save(self.data)
        # panic: remove any cached Drive login so a snoop can't reach online data
        try:
            tok = app_paths.state_dir() / "drive_token.json"
            if tok.exists():
                tok.unlink()
        except Exception:
            pass
        self._set_today()
        self._refresh_dashboard()
        for _item, v in getattr(self, "_chk_vars", {}).items():
            v.set("off")


def main():
    # Loop so the vault's "← Health" button can return to the cover app, and the
    # cover's hidden channel can re-open the vault, without ever exiting.
    while True:
        app = HealthApp()
        app.mainloop()
        if not getattr(app, "_open_vault", False):
            break
        import gui                     # load the real vault only after unlock
        gui.FROM_HEALTH = True         # tell the vault it can offer "← Health"
        vault = gui.VaultApp()
        vault.mainloop()
        if not getattr(vault, "return_to_health", False):
            break                      # vault closed normally -> exit


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        # reuse the vault's asset self-test so a built .exe can be verified
        import gui
        sys.exit(gui._selftest())
    main()
