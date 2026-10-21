"""
health_gate.py — an innocent "Health & Wellness" tracker that doubles as a
side-channel launcher for the real vault (gui.VaultApp).

It looks and works like an ordinary habit tracker (water intake, an intermittent-
fasting timer, a routine checklist, settings). A hidden path opens the vault:

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
import time
from datetime import datetime, timedelta

import customtkinter as ctk

import app_paths

# --- configure these two secrets --------------------------------------------
SECRET_TRIGGER = "7749"          # type this as the water amount to arm the prompt
UNLOCK_PASSWORD = "open-sesame"  # entered in the confirmation dialog to open vault
# ----------------------------------------------------------------------------

DATA_PATH = app_paths.state_dir() / "health_data.json"
EAT_START, EAT_END = 7, 14        # eating window 07:00–14:00 (IF 17:7)

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
def is_trigger(text: str) -> bool:
    return (text or "").strip() == SECRET_TRIGGER


def check_unlock(password: str) -> bool:
    return (password or "") == UNLOCK_PASSWORD


# ---- storage ---------------------------------------------------------------
def _load() -> dict:
    try:
        d = json.loads(DATA_PATH.read_text("utf-8"))
    except Exception:
        d = {}
    d.setdefault("water_ml", 0)
    d.setdefault("water_goal", 2000)
    d.setdefault("fast_day", "")
    d.setdefault("checklist", {k: False for k in DEFAULT_CHECKLIST})
    d.setdefault("sound", True)
    return d


def _save(d: dict) -> None:
    try:
        DATA_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


class HealthApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Health & Wellness")
        self.geometry("460x640")
        self.minsize(420, 560)
        self.data = _load()
        self._open_vault = False       # set True to launch the vault on close

        self.tabs = ctk.CTkTabview(self, width=440)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        for name in ("หน้าหลัก", "ดื่มน้ำ", "อดอาหาร (IF)", "เช็คลิสต์", "ตั้งค่า"):
            self.tabs.add(name)

        self._build_dashboard(self.tabs.tab("หน้าหลัก"))
        self._build_water(self.tabs.tab("ดื่มน้ำ"))
        self._build_fasting(self.tabs.tab("อดอาหาร (IF)"))
        self._build_checklist(self.tabs.tab("เช็คลิสต์"))
        self._build_settings(self.tabs.tab("ตั้งค่า"))

        self._tick()                   # start the fasting clock

    # ---- Dashboard --------------------------------------------------
    def _build_dashboard(self, tab):
        ctk.CTkLabel(tab, text="ภาพรวมวันนี้",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(14, 6))
        self.ring = ctk.CTkCanvas(tab, width=180, height=180, highlightthickness=0,
                                  bg="#242424")
        self.ring.pack(pady=6)
        self.dash_pct = ctk.CTkLabel(tab, text="", font=ctk.CTkFont(size=14))
        self.dash_pct.pack()
        self.dash_rows = ctk.CTkFrame(tab, fg_color="transparent")
        self.dash_rows.pack(fill="x", padx=18, pady=10)
        self._refresh_dashboard()

    def _refresh_dashboard(self):
        goal = max(1, int(self.data["water_goal"]))
        pct = min(1.0, self.data["water_ml"] / goal)
        self.ring.delete("all")
        self.ring.create_oval(20, 20, 160, 160, outline="#3a3a3a", width=16)
        if pct > 0:
            self.ring.create_arc(20, 20, 160, 160, start=90, extent=-359.9 * pct,
                                 style="arc", outline="#4a8bd4", width=16)
        self.ring.create_text(90, 90, text=f"{int(pct*100)}%",
                              fill="#e8eef5", font=("Arial", 26, "bold"))
        self.dash_pct.configure(text=f"ดื่มน้ำ {self.data['water_ml']} / {goal} ml")
        for w in self.dash_rows.winfo_children():
            w.destroy()
        done = sum(1 for v in self.data["checklist"].values() if v)
        total = len(self.data["checklist"])
        state = "ช่วงอดอาหาร" if self._is_fasting() else "ช่วงทานอาหารได้"
        for label, val in [("กิจวัตรสำเร็จ", f"{done}/{total}"),
                           ("สถานะ IF", state)]:
            row = ctk.CTkFrame(self.dash_rows, fg_color="#2b2b2b", corner_radius=8)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label).pack(side="left", padx=12, pady=8)
            ctk.CTkLabel(row, text=val,
                         font=ctk.CTkFont(weight="bold")).pack(side="right", padx=12)

    # ---- Water Tracker (holds the hidden channel) -------------------
    def _build_water(self, tab):
        self.water_goal_lbl = ctk.CTkLabel(
            tab, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.water_goal_lbl.pack(pady=(16, 2))
        # double-clicking the goal number is a second way to arm the prompt
        self.water_goal_lbl.bind("<Double-Button-1>", lambda _e: self._armed_dialog())

        self.water_bar = ctk.CTkProgressBar(tab, width=320)
        self.water_bar.pack(pady=8)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(pady=10)
        self.water_entry = ctk.CTkEntry(row, width=120, placeholder_text="ml เช่น 250")
        self.water_entry.pack(side="left", padx=(0, 8))
        self.water_entry.bind("<Return>", lambda _e: self._log_water())
        ctk.CTkButton(row, text="+ บันทึก", width=90,
                      command=self._log_water).pack(side="left")

        for amt in (150, 250, 500):
            ctk.CTkButton(tab, text=f"+{amt} ml", width=90, fg_color="gray30",
                          command=lambda a=amt: self._add_water(a)).pack(pady=3)

        self.water_status = ctk.CTkLabel(tab, text="", text_color="#4caf69")
        self.water_status.pack(pady=6)
        self._refresh_water()

    def _refresh_water(self):
        goal = max(1, int(self.data["water_goal"]))
        self.water_goal_lbl.configure(text=f"เป้าหมายวันนี้: {goal} ml")
        self.water_bar.set(min(1.0, self.data["water_ml"] / goal))

    def _add_water(self, ml: int):
        self.data["water_ml"] = max(0, self.data["water_ml"] + int(ml))
        _save(self.data)
        self._refresh_water()
        self._refresh_dashboard()
        self.water_status.configure(text=f"บันทึก {ml} ml แล้ว")

    def _log_water(self):
        text = self.water_entry.get().strip()
        self.water_entry.delete(0, "end")
        if is_trigger(text):               # hidden channel armed
            self._armed_dialog()
            return
        try:
            self._add_water(int(float(text)))
        except Exception:
            self.water_status.configure(text="กรุณาใส่ตัวเลข ml ให้ถูกต้อง")

    def _armed_dialog(self):
        """Innocent-looking confirmation that hides a password field. Correct
        password -> open the vault; anything else -> behave as a normal app."""
        win = ctk.CTkToplevel(self)
        win.title("ยืนยันการบันทึก")
        win.geometry("380x250")
        win.configure(fg_color="#1e1e1e")
        ctk.CTkLabel(win, text="⚠️ ตรวจพบความผิดปกติ",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#e6b800").pack(pady=(16, 4))
        ctk.CTkLabel(win, text="ปริมาณการดื่มน้ำสูงผิดปกติ หรือรูปแบบไม่ถูกต้อง\n"
                               "ต้องการยืนยันการบันทึกหรือไม่?",
                     text_color="#d7dbe0", justify="center").pack(pady=(0, 8), padx=14)
        pw = ctk.CTkEntry(win, width=220, show="•",
                          placeholder_text="รหัสยืนยัน (ถ้ามี)")
        pw.pack(pady=4)
        pw.focus()

        def confirm():
            val = pw.get()
            win.destroy()
            if check_unlock(val):
                self._launch_vault()
            else:
                # deniable: just acknowledge like a normal validation prompt
                self.water_status.configure(text="ยกเลิกการบันทึกรายการนี้")

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=14)
        ctk.CTkButton(btns, text="ยกเลิก", width=100, fg_color="gray30",
                      command=win.destroy).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="ยืนยัน", width=120,
                      command=confirm).pack(side="left", padx=6)
        pw.bind("<Return>", lambda _e: confirm())
        try:
            win.transient(self); win.grab_set(); win.lift()
        except Exception:
            pass

    def _launch_vault(self):
        # end this app's loop, then main() opens the real vault
        self._open_vault = True
        self.destroy()

    # ---- Fasting timer ---------------------------------------------
    def _build_fasting(self, tab):
        ctk.CTkLabel(tab, text="ตัวจับเวลา Intermittent Fasting (17:7)",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 2))
        ctk.CTkLabel(tab, text=f"ช่วงทานอาหาร {EAT_START:02d}:00 – {EAT_END:02d}:00 น.",
                     text_color="#aab2bd").pack(pady=(0, 10))
        self.fast_state = ctk.CTkLabel(tab, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.fast_state.pack(pady=4)
        self.fast_count = ctk.CTkLabel(tab, text="", font=ctk.CTkFont(size=34, weight="bold"))
        self.fast_count.pack(pady=6)
        self.fast_hint = ctk.CTkLabel(tab, text="", text_color="#8a9099")
        self.fast_hint.pack()

    def _is_fasting(self) -> bool:
        h = datetime.now().hour
        return not (EAT_START <= h < EAT_END)

    def _tick(self):
        now = datetime.now()
        if self._is_fasting():
            nxt = now.replace(hour=EAT_START, minute=0, second=0, microsecond=0)
            if now.hour >= EAT_END:
                nxt += timedelta(days=1)
            state, color, hint = "กำลังอดอาหาร", "#e6b800", "เหลือเวลาถึงช่วงทานอาหาร"
        else:
            nxt = now.replace(hour=EAT_END, minute=0, second=0, microsecond=0)
            state, color, hint = "ทานอาหารได้", "#4caf69", "เหลือเวลาในช่วงทานอาหาร"
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
        ctk.CTkLabel(tab, text="กิจวัตรสุขภาพประจำวัน",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 8))
        self._chk_vars = {}
        for item in self.data["checklist"]:
            v = ctk.StringVar(value="on" if self.data["checklist"][item] else "off")
            self._chk_vars[item] = v
            ctk.CTkCheckBox(tab, text=item, variable=v, onvalue="on", offvalue="off",
                            command=lambda i=item: self._toggle_chk(i)).pack(
                anchor="w", padx=26, pady=6)

    def _toggle_chk(self, item):
        self.data["checklist"][item] = (self._chk_vars[item].get() == "on")
        _save(self.data)
        self._refresh_dashboard()

    # ---- Settings (holds the safe panic reset) ---------------------
    def _build_settings(self, tab):
        ctk.CTkLabel(tab, text="การตั้งค่า",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 10))
        snd = ctk.StringVar(value="on" if self.data["sound"] else "off")

        def toggle_sound():
            self.data["sound"] = (snd.get() == "on")
            _save(self.data)
        ctk.CTkSwitch(tab, text="เสียงแจ้งเตือน", variable=snd, onvalue="on",
                      offvalue="off", command=toggle_sound).pack(anchor="w", padx=26, pady=8)

        def set_theme(v):
            ctk.set_appearance_mode("light" if v == "สว่าง" else "dark")
        ctk.CTkLabel(tab, text="ธีม").pack(anchor="w", padx=26, pady=(8, 0))
        ctk.CTkSegmentedButton(tab, values=["มืด", "สว่าง"],
                               command=set_theme).pack(anchor="w", padx=26, pady=4)

        ctk.CTkButton(tab, text="ล้างข้อมูล (Reset Data)", fg_color="#a3332f",
                      hover_color="#7d2420", command=self._reset_data).pack(
            side="bottom", pady=18)

    def _reset_data(self):
        """Face value: wipe the health tracker data. Hidden safety: also sign out
        of Google Drive (drop the cached token) so the vault's online access is
        cut immediately. It deliberately does NOT touch or destroy the vault
        itself — the data stays encrypted and recoverable with your password."""
        self.data = {"water_ml": 0, "water_goal": self.data.get("water_goal", 2000),
                     "fast_day": "", "checklist": {k: False for k in DEFAULT_CHECKLIST},
                     "sound": self.data.get("sound", True)}
        _save(self.data)
        # panic: remove any cached Drive login so a snoop can't reach online data
        try:
            tok = app_paths.state_dir() / "drive_token.json"
            if tok.exists():
                tok.unlink()
        except Exception:
            pass
        self._refresh_water(); self._refresh_dashboard()
        for item, v in getattr(self, "_chk_vars", {}).items():
            v.set("off")


def main():
    app = HealthApp()
    app.mainloop()
    if getattr(app, "_open_vault", False):
        import gui                     # load the real vault only after unlock
        gui.VaultApp().mainloop()


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        # reuse the vault's asset self-test so a built .exe can be verified
        import gui
        sys.exit(gui._selftest())
    main()
