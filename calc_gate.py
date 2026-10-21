"""
calc_gate.py — a plain calculator that doubles as a side-channel unlock.

It works as an ordinary calculator. A hidden prompt only appears if a specific
secret value is on the display and "=" is pressed; the correct PIN there launches
the real vault (gui.VaultApp). Any other input just keeps calculating — there is
no sign that a hidden system exists (plausible deniability / duress-resistant).

This disguise is deliberately NOT a payment form: it impersonates no one and
collects no payment or login credentials. Use it as the entry point in place of
gui.py (e.g. point _launch.bat / the .vbs at calc_gate.py).

Dependencies: customtkinter
"""

from __future__ import annotations

import customtkinter as ctk

# --- configure these two secrets ---------------------------------------------
SECRET_TRIGGER = "735711"     # type this, then press "=", to reveal the prompt
UNLOCK_PIN = "2468"           # the real PIN entered in the hidden prompt
# -----------------------------------------------------------------------------

ctk.set_appearance_mode("dark")


class Calculator(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Calculator")
        self.geometry("300x430")
        self.minsize(260, 380)
        self.expr = ""
        self.unlocked = False          # set True when the right PIN is entered

        self.display = ctk.CTkEntry(self, justify="right",
                                    font=ctk.CTkFont(size=26), height=60)
        self.display.pack(fill="x", padx=12, pady=12)

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        layout = [["C", "(", ")", "/"],
                  ["7", "8", "9", "*"],
                  ["4", "5", "6", "-"],
                  ["1", "2", "3", "+"],
                  ["0", ".", "="]]
        for r, row in enumerate(layout):
            for c, label in enumerate(row):
                span = 2 if label == "0" else 1
                op = label in "+-*/()"
                ctk.CTkButton(
                    grid, text=label, height=52,
                    fg_color=("#2d7d46" if label == "=" else
                              ("gray30" if op or label == "C" else None)),
                    command=lambda l=label: self.press(l)
                ).grid(row=r, column=c, columnspan=span,
                       sticky="nsew", padx=3, pady=3)
        for i in range(4):
            grid.columnconfigure(i, weight=1)
        for i in range(5):
            grid.rowconfigure(i, weight=1)

    # ---- display helpers ---------------------------------------------
    def _show(self, s: str):
        self.expr = s
        self.display.delete(0, "end")
        self.display.insert(0, s)

    # ---- button logic ------------------------------------------------
    def press(self, label: str):
        if label == "C":
            self._show("")
            return
        if label == "=":
            if self.expr == SECRET_TRIGGER:          # <-- side-channel trigger
                self._show("")
                self._hidden_prompt()
                return
            try:
                # safe: no builtins, and input comes only from the buttons
                self._show(str(eval(self.expr, {"__builtins__": {}}, {})))
            except Exception:
                self._show("Error")
            return
        if self.expr == "Error":
            self.expr = ""
        self._show(self.expr + label)

    # ---- hidden unlock ------------------------------------------------
    def _hidden_prompt(self):
        # looks like a calculator "memory" entry, not a bank OTP
        dlg = ctk.CTkInputDialog(title="M", text="Value:")
        try:
            value = dlg.get_input()
        except Exception:
            value = None
        if value == UNLOCK_PIN:
            self.unlocked = True
            self.destroy()                 # end the calculator loop -> launch vault
        # wrong / cancelled: do nothing (deniable) — the calculator continues


def main():
    app = Calculator()
    app.mainloop()
    if getattr(app, "unlocked", False):
        # launch the real vault only after a correct side-channel unlock
        import gui
        gui.VaultApp().mainloop()


if __name__ == "__main__":
    main()
