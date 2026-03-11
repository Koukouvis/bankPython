import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import random
import string
import sys, os
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler

client = MongoClient("mongodb://localhost:27017/")
db = client["neobank"]
users_col = db["users"]
requests_col = db["income_requests"]

if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

# ── Palette ──────────────────────────────────────────────────────────────────
BG        = "#0D0F14"
CARD      = "#161B25"
CARD2     = "#1C2333"
ACCENT    = "#4F8EF7"
ACCENT2   = "#7B61FF"
GREEN     = "#2ECC8A"
RED       = "#FF5C6A"
TEXT      = "#E8EBF2"
SUBTEXT   = "#7A85A0"
BORDER    = "#242C3D"
FONT_MAIN = ("Segoe UI", 10)
FONT_BIG  = ("Segoe UI", 22, "bold")
FONT_MED  = ("Segoe UI", 13, "bold")
FONT_SM   = ("Segoe UI", 9)

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

THEME = {"mode": "dark"}

THEMES = {
    "dark":  {"BG": "#0D0F14", "CARD": "#161B25", "CARD2": "#1C2333", "TEXT": "#E8EBF2", "SUBTEXT": "#7A85A0", "BORDER": "#242C3D"},
    "light": {"BG": "#F0F2F8", "CARD": "#FFFFFF", "CARD2": "#E8EBF2", "TEXT": "#0D0F14", "SUBTEXT": "#5A6070", "BORDER": "#D0D4E0"},
}

def apply_theme(mode):
    global BG, CARD, CARD2, TEXT, SUBTEXT, BORDER
    t = THEMES[mode]
    BG, CARD, CARD2, TEXT, SUBTEXT, BORDER = t["BG"], t["CARD"], t["CARD2"], t["TEXT"], t["SUBTEXT"], t["BORDER"]
    THEME["mode"] = mode

# ── Data layer ────────────────────────────────────────────────────────────────
class Bank:
    def __init__(self):
        self.accounts: dict[str, dict] = {}
        self.current: str | None = None
        self._create("demo", "123", "Alex Johnson")
        self.accounts["demo"]["balance"] = 4_250.00
        self.accounts["demo"]["transactions"] = [
            {"date": "2025-03-01", "desc": "Opening Deposit",  "amount":  5000.00, "type": "credit"},
            {"date": "2025-03-05", "desc": "Netflix",          "amount":   -18.99, "type": "debit"},
            {"date": "2025-03-08", "desc": "Salary",           "amount":  2100.00, "type": "credit"},
            {"date": "2025-03-10", "desc": "Grocery Store",    "amount":   -87.45, "type": "debit"},
            {"date": "2025-03-12", "desc": "Electric Bill",    "amount":   -65.00, "type": "debit"},
            {"date": "2025-03-15", "desc": "Transfer In",      "amount":   500.00, "type": "credit"},
            {"date": "2025-03-18", "desc": "Restaurant",       "amount":   -43.60, "type": "debit"},
            {"date": "2025-03-20", "desc": "Online Shopping",  "amount":  -134.99, "type": "debit"},
        ]
        for user in users_col.find():
            u = user["username"]
            if u not in self.accounts:
                self.accounts[u] = {
                    "password": user["password"],
                    "name": user["name"],
                    "account_no": user.get("account_no", self._gen_acc_no()),
                    "balance": user.get("balance", 0.0),
                    "transactions": user.get("transactions", []),
                    "income": user.get("income", 0.0),
                    "last_income_date": user.get("last_income_date", None),
                }

    def _gen_acc_no(self):
        return "".join(random.choices(string.digits, k=12))

    def _create(self, username, password, full_name):
        self.accounts[username] = {
            "password": password,
            "name": full_name,
            "account_no": self._gen_acc_no(),
            "balance": 0.0,
            "transactions": [],
            "income": 0.0,
            "last_income_date": None,
        }
        users_col.update_one(
            {"username": username},
            {"$set": {
                "username": username,
                "password": password,
                "name": full_name,
                "account_no": self.accounts[username]["account_no"],
                "balance": 0.0,
                "transactions": [],
                "income": 0.0,
                "last_income_date": None,
            }},
            upsert=True
        )

    def register(self, username, password, full_name):
        if username in self.accounts:
            return False, "Username already taken."
        if len(password) < 6:
            return False, "Password must be at least 6 characters."
        if not full_name.strip():
            return False, "Full name required."
        self._create(username, password, full_name)
        return True, "Account created!"

    def login(self, username, password):
        acc = self.accounts.get(username)
        if not acc or acc["password"] != password:
            return False, "Invalid credentials."
        self.current = username
        return True, "OK"

    def logout(self):
        self.current = None

    @property
    def acc(self):
        return self.accounts[self.current]

    def withdraw(self, amount):
        if amount <= 0:
            return False, "Amount must be positive."
        if amount > self.acc["balance"]:
            return False, "Insufficient funds."
        self.acc["balance"] -= amount
        self._log("Withdrawal", -amount, "debit")
        self._sync(self.current)
        return True, f"Withdrew ${amount:,.2f}"

    def transfer(self, to_user, amount, description):
        if to_user not in self.accounts:
            return False, "Recipient account not found."
        if to_user == self.current:
            return False, "Cannot transfer to yourself."
        if amount <= 0:
            return False, "Amount must be positive."
        if amount > self.acc["balance"]:
            return False, "Insufficient funds."
        if not description.strip():
            return False, "Transfer description is required."
        self.acc["balance"] -= amount
        self.acc["transactions"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "desc": f"Transfer to {to_user}: {description}",
            "amount": -amount,
            "type": "debit",
        })
        self.accounts[to_user]["balance"] += amount
        self.accounts[to_user]["transactions"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "desc": f"Transfer from {self.current}: {description}",
            "amount": amount,
            "type": "credit",
        })
        self._sync(self.current)
        self._sync(to_user)
        return True, f"Transferred ${amount:,.2f} to {to_user}"

    def _log(self, desc, amount, kind):
        self.acc["transactions"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "desc": desc, "amount": amount, "type": kind,
        })

    def _sync(self, username):
        acc = self.accounts[username]
        users_col.update_one(
            {"username": username},
            {"$set": {
                "balance": acc["balance"],
                "transactions": acc["transactions"],
                "income": acc.get("income", 0.0),
                "last_income_date": acc.get("last_income_date", None),
            }}
        )


# ── Widget helpers ────────────────────────────────────────────────────────────
def make_frame(parent, bg=CARD, **kw):
    return tk.Frame(parent, bg=bg, **kw)

def label(parent, text, font=FONT_MAIN, fg=TEXT, bg=CARD, **kw):
    return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kw)

def entry(parent, show=None, width=28):
    e = tk.Entry(parent, font=FONT_MAIN, bg=CARD2, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=1, highlightcolor=ACCENT,
                 highlightbackground=BORDER, width=width, show=show or "")
    e.configure(bd=0)
    return e

def btn(parent, text, command, color=ACCENT, fg=TEXT, width=18, font=FONT_MAIN):
    b = tk.Button(parent, text=text, command=command,
                  bg=color, fg=fg, font=font, relief="flat",
                  activebackground=ACCENT2, activeforeground=TEXT,
                  cursor="hand2", width=width, bd=0,
                  padx=10, pady=6)
    return b

def sep(parent, bg=BORDER):
    return tk.Frame(parent, bg=bg, height=1)


# ── App ───────────────────────────────────────────────────────────────────────
class BankingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.bank = Bank()
        self.title("NeoBank")
        self.configure(bg=BG)
        self.geometry("900x620")
        self.minsize(860, 580)
        self.resizable(True, True)

        self.sidebar = None
        self.content = None

        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self._check_monthly_income, "interval", minutes=1)
        self.scheduler.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._show_login()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()
        self.sidebar = None
        self.content = None

    def _show_login(self):
        self._clear()
        LoginPage(self)

    def _show_admin(self):
        self._clear()
        AdminPage(self)

    def _show_options(self):
        self._build_shell()
        OptionsPage(self.content, self.bank, self)

    def _show_register(self):
        self._clear()
        RegisterPage(self)

    def _show_dashboard(self):
        self._clear()
        self._build_shell()
        DashboardPage(self.content, self.bank, self)

    def _show_withdraw(self):
        self._build_shell()
        WithdrawPage(self.content, self.bank, self)

    def _show_transfer(self):
        self._build_shell()
        TransferPage(self.content, self.bank, self)

    def _show_history(self):
        self._build_shell()
        HistoryPage(self.content, self.bank, self)

    def _show_income(self):
        self._build_shell()
        IncomePage(self.content, self.bank, self)

    def _check_monthly_income(self):
        now = datetime.now()
        for username, acc in self.bank.accounts.items():
            income = acc.get("income", 0.0)
            if income <= 0:
                continue
            last = acc.get("last_income_date")
            last_dt = datetime.strptime(last, "%Y-%m-%d") if last else None
            should_pay = (
                last_dt is None or
                (now.year > last_dt.year) or
                (now.year == last_dt.year and now.month > last_dt.month)
            )
            if should_pay:
                acc["balance"] += income
                acc["last_income_date"] = now.strftime("%Y-%m-%d")
                acc["transactions"].append({
                    "date": now.strftime("%Y-%m-%d"),
                    "desc": "Monthly Income",
                    "amount": income,
                    "type": "credit",
                })
                self.bank._sync(username)

    def _on_close(self):
        self.scheduler.shutdown()
        self.destroy()

    def _build_shell(self):
        if self.sidebar:
            for w in self.content.winfo_children():
                w.destroy()
            return
        self.sidebar = make_frame(self, bg="#0A0C12", width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_f = make_frame(self.sidebar, bg="#0A0C12")
        logo_f.pack(fill="x", padx=20, pady=(28, 10))
        tk.Label(logo_f, text="◈", font=("Segoe UI", 22), fg=ACCENT, bg="#0A0C12").pack(side="left")
        tk.Label(logo_f, text=" NeoBank", font=("Segoe UI", 16, "bold"), fg=TEXT, bg="#0A0C12").pack(side="left")

        sep(self.sidebar, bg=BORDER).pack(fill="x", padx=16, pady=8)

        nav_items = [
            ("⌂  Dashboard",  self._show_dashboard),
            ("↑  Withdraw",    self._show_withdraw),
            ("⇄  Transfer",    self._show_transfer),
            ("≡  History",     self._show_history),
            ("$  Income",      self._show_income),
            ("⚙  Options",     self._show_options),
        ]
        for text, cmd in nav_items:
            self._nav_btn(text, cmd)

        bottom = make_frame(self.sidebar, bg="#0A0C12")
        bottom.pack(side="bottom", fill="x", padx=16, pady=16)
        sep(self.sidebar, bg=BORDER).pack(side="bottom", fill="x", padx=16, pady=(0, 4))
        name = self.bank.acc["name"]
        self.sidebar_name_lbl = tk.Label(bottom, text=name, font=("Segoe UI", 9, "bold"), fg=TEXT, bg="#0A0C12", anchor="w")
        self.sidebar_name_lbl.pack(fill="x")
        tk.Label(bottom, text="Personal Account", font=FONT_SM,
                 fg=SUBTEXT, bg="#0A0C12", anchor="w").pack(fill="x")
        btn(bottom, "  ⏻  Logout", self._logout,
            color="#1C2333", fg=RED, width=16).pack(fill="x", pady=(8, 0))

        self.content = make_frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    def _nav_btn(self, text, cmd):
        b = tk.Button(self.sidebar, text=text, command=cmd,
                      bg="#0A0C12", fg=SUBTEXT, font=("Segoe UI", 10),
                      relief="flat", anchor="w", padx=20, pady=9,
                      activebackground=CARD, activeforeground=TEXT,
                      cursor="hand2", bd=0)
        b.pack(fill="x")
        b.bind("<Enter>", lambda e: b.configure(fg=TEXT, bg=CARD))
        b.bind("<Leave>", lambda e: b.configure(fg=SUBTEXT, bg="#0A0C12"))

    def _logout(self):
        self.bank.logout()
        self._show_login()


# ── Pages ─────────────────────────────────────────────────────────────────────
class LoginPage(tk.Frame):
    def __init__(self, app: BankingApp):
        super().__init__(app, bg=BG)
        self.app = app
        self.pack(fill="both", expand=True)
        self._build()

    def _build(self):
        outer = make_frame(self, bg=BG)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        card = make_frame(outer, bg=CARD)
        card.pack(padx=4, pady=4)
        inner = make_frame(card, bg=CARD)
        inner.pack(padx=44, pady=44)

        tk.Label(inner, text="◈", font=("Segoe UI", 34), fg=ACCENT, bg=CARD).pack()
        label(inner, "Welcome back", font=("Segoe UI", 20, "bold"), bg=CARD).pack(pady=(4, 2))
        label(inner, "Sign in to your NeoBank account", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(pady=(0, 22))

        label(inner, "Username", bg=CARD, font=FONT_SM, fg=SUBTEXT).pack(anchor="w")
        self.usr = entry(inner)
        self.usr.pack(fill="x", ipady=7, pady=(2, 12))

        label(inner, "Password", bg=CARD, font=FONT_SM, fg=SUBTEXT).pack(anchor="w")
        self.pwd = entry(inner, show="●")
        self.pwd.pack(fill="x", ipady=7, pady=(2, 20))

        btn(inner, "Sign In", self._login, width=30).pack(fill="x", ipady=4)
        tk.Label(inner, text="Don't have an account?  Create one →",
                 font=FONT_SM, fg=ACCENT, bg=CARD, cursor="hand2").pack(pady=(12, 0))
        inner.winfo_children()[-1].bind("<Button-1>", lambda e: self.app._show_register())

        label(inner, "( Demo: Username = demo  Password = 123 )",
              font=("Segoe UI", 8), fg=SUBTEXT, bg=CARD).pack(pady=(10, 0))

        self.usr.focus()
        self.bind_all("<Return>", lambda e: self._login())

    def _login(self):
        usr = self.usr.get().strip()
        pwd = self.pwd.get()
        if usr == ADMIN_USER and pwd == ADMIN_PASS:
            self.unbind_all("<Return>")
            self.app._show_admin()
            return
        ok, msg = self.app.bank.login(usr, pwd)
        if ok:
            self.unbind_all("<Return>")
            self.app._show_dashboard()
        else:
            messagebox.showerror("Login Failed", msg)


class RegisterPage(tk.Frame):
    def __init__(self, app: BankingApp):
        super().__init__(app, bg=BG)
        self.app = app
        self.pack(fill="both", expand=True)
        self._build()

    def _build(self):
        outer = make_frame(self, bg=BG)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        card = make_frame(outer, bg=CARD)
        card.pack(padx=4, pady=4)
        inner = make_frame(card, bg=CARD)
        inner.pack(padx=44, pady=44)

        label(inner, "Create Account", font=("Segoe UI", 20, "bold"), bg=CARD).pack()
        label(inner, "Join NeoBank today", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(pady=(2, 22))

        for lbl, attr, sh in [
            ("Full Name", "name_e", None),
            ("Username",  "usr_e",  None),
            ("Password",  "pwd_e",  "●"),
            ("Confirm Password", "pwd2_e", "●"),
        ]:
            label(inner, lbl, bg=CARD, font=FONT_SM, fg=SUBTEXT).pack(anchor="w")
            e = entry(inner, show=sh)
            e.pack(fill="x", ipady=7, pady=(2, 12))
            setattr(self, attr, e)

        btn(inner, "Create Account", self._register, color=GREEN, fg="#0D0F14", width=30).pack(fill="x", ipady=4)
        tk.Label(inner, text="← Back to Sign In",
                 font=FONT_SM, fg=ACCENT, bg=CARD, cursor="hand2").pack(pady=(12, 0))
        inner.winfo_children()[-1].bind("<Button-1>", lambda e: self.app._show_login())

    def _register(self):
        if self.pwd_e.get() != self.pwd2_e.get():
            messagebox.showerror("Error", "Passwords do not match.")
            return
        ok, msg = self.app.bank.register(
            self.usr_e.get().strip(),
            self.pwd_e.get(),
            self.name_e.get().strip(),
        )
        if ok:
            messagebox.showinfo("Success", msg + "\nYou can now log in.")
            self.app._show_login()
        else:
            messagebox.showerror("Error", msg)


class DashboardPage(tk.Frame):
    def __init__(self, parent, bank: Bank, app: BankingApp):
        super().__init__(parent, bg=BG)
        self.pack(fill="both", expand=True, padx=32, pady=28)
        acc = bank.acc

        label(self, f"Good day, {acc['name'].split()[0]} 👋",
              font=("Segoe UI", 18, "bold"), bg=BG).pack(anchor="w")
        label(self, "Here's your financial overview",
              font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", pady=(2, 20))

        bal_card = make_frame(self, bg=ACCENT)
        bal_card.pack(fill="x", pady=(0, 18))
        inner = make_frame(bal_card, bg=ACCENT)
        inner.pack(padx=28, pady=22)
        label(inner, "Total Balance", font=FONT_SM, fg="#BDD4FF", bg=ACCENT).pack(anchor="w")
        label(inner, f"${acc['balance']:,.2f}", font=("Segoe UI", 32, "bold"),
              fg="white", bg=ACCENT).pack(anchor="w", pady=(4, 4))
        label(inner, f"Account  ···· {acc['account_no'][-4:]}",
              font=FONT_SM, fg="#BDD4FF", bg=ACCENT).pack(anchor="w")

        label(self, "Quick Actions", font=FONT_MED, bg=BG).pack(anchor="w", pady=(0, 10))
        row = make_frame(self, bg=BG)
        row.pack(fill="x", pady=(0, 20))
        for text, cmd, color in [
            ("↑  Withdraw",  app._show_withdraw, RED),
            ("⇄  Transfer",  app._show_transfer, ACCENT2),
            ("≡  History",   app._show_history,  ACCENT),
            ("$  Income",    app._show_income,   GREEN),
        ]:
            b = tk.Button(row, text=text, command=cmd,
                          bg=CARD, fg=color, font=("Segoe UI", 10, "bold"),
                          relief="flat", padx=18, pady=14,
                          activebackground=CARD2, activeforeground=color,
                          cursor="hand2", bd=0)
            b.pack(side="left", expand=True, fill="x", padx=(0, 8))

        label(self, "Recent Transactions", font=FONT_MED, bg=BG).pack(anchor="w", pady=(0, 10))
        txs = list(reversed(acc["transactions"]))[:5]
        if not txs:
            label(self, "No transactions yet.", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w")
        for tx in txs:
            self._tx_row(tx)

    def _tx_row(self, tx):
        row = make_frame(self, bg=CARD)
        row.pack(fill="x", pady=2)
        inner = make_frame(row, bg=CARD)
        inner.pack(fill="x", padx=16, pady=10)
        color = GREEN if tx["type"] == "credit" else RED
        sign  = "+" if tx["type"] == "credit" else ""
        label(inner, tx["desc"],  font=("Segoe UI", 9, "bold"), bg=CARD).pack(side="left")
        label(inner, tx["date"],  font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(side="left", padx=12)
        label(inner, f"{sign}${abs(tx['amount']):,.2f}",
              font=("Segoe UI", 9, "bold"), fg=color, bg=CARD).pack(side="right")


class _OpPage(tk.Frame):
    TITLE    = ""
    SUBTITLE = ""
    BTN_COLOR = ACCENT

    def __init__(self, parent, bank: Bank, app: BankingApp):
        super().__init__(parent, bg=BG)
        self.bank = bank
        self.app  = app
        self.pack(fill="both", expand=True, padx=32, pady=28)
        label(self, self.TITLE,    font=("Segoe UI", 18, "bold"), bg=BG).pack(anchor="w")
        label(self, self.SUBTITLE, font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", pady=(2, 24))
        self._fields()

    def _field(self, lbl):
        label(self, lbl, font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w")
        e = entry(self, width=34)
        e.pack(anchor="w", ipady=8, pady=(2, 14))
        return e

    def _fields(self): ...

    def _result(self, ok, msg):
        if ok:
            messagebox.showinfo("✓ Success", msg)
            self.app._show_dashboard()
        else:
            messagebox.showerror("Error", msg)


class WithdrawPage(_OpPage):
    TITLE    = "Withdraw Funds"
    SUBTITLE = "Take cash from your account"

    def _fields(self):
        self.amt = self._field("Amount ($)")
        btn(self, "Withdraw", self._go, color=RED, width=20).pack(anchor="w", ipady=4)

    def _go(self):
        try: amt = float(self.amt.get())
        except ValueError: messagebox.showerror("Error", "Enter a valid number."); return
        self._result(*self.bank.withdraw(amt))


class TransferPage(_OpPage):
    TITLE    = "Transfer Money"
    SUBTITLE = "Send funds to another NeoBank account"

    def _fields(self):
        self.to   = self._field("Recipient Username")
        self.amt  = self._field("Amount ($)")
        self.desc = self._field("Description (required)")
        btn(self, "Send Transfer", self._go, color=ACCENT2, width=20).pack(anchor="w", ipady=4)

    def _go(self):
        try: amt = float(self.amt.get())
        except ValueError: messagebox.showerror("Error", "Enter a valid number."); return
        self._result(*self.bank.transfer(self.to.get().strip(), amt, self.desc.get().strip()))


# ── Income Page ───────────────────────────────────────────────────────────────
class IncomePage(tk.Frame):
    def __init__(self, parent, bank: Bank, app: BankingApp):
        super().__init__(parent, bg=BG)
        self.bank = bank
        self.app  = app
        self.pack(fill="both", expand=True, padx=32, pady=28)
        self._build()

    def _build(self):
        label(self, "Income", font=("Segoe UI", 18, "bold"), bg=BG).pack(anchor="w")
        label(self, "Your monthly income and pending requests", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", pady=(2, 24))

        # current income card
        acc = self.bank.acc
        income = acc.get("income", 0.0)
        info_card = make_frame(self, bg=CARD)
        info_card.pack(fill="x", pady=(0, 20))
        inf = make_frame(info_card, bg=CARD)
        inf.pack(fill="x", padx=24, pady=18)
        label(inf, "Current Monthly Income", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(inf, f"${income:,.2f} / month", font=("Segoe UI", 20, "bold"), fg=GREEN, bg=CARD).pack(anchor="w", pady=(6, 4))
        last = acc.get("last_income_date")
        label(inf, f"Last paid: {last if last else 'Never'}", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")

        # request card
        req_card = make_frame(self, bg=CARD)
        req_card.pack(fill="x", pady=(0, 20))
        rq = make_frame(req_card, bg=CARD)
        rq.pack(fill="x", padx=24, pady=18)
        label(rq, "Request Income Change", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(rq, "Submit a request to the admin to update your monthly income.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))

        label(rq, "Requested Amount ($)", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.req_amt = entry(rq, width=34)
        self.req_amt.pack(anchor="w", ipady=8, pady=(2, 12))

        label(rq, "Income Source / Description", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.req_desc = entry(rq, width=34)
        self.req_desc.pack(anchor="w", ipady=8, pady=(2, 16))

        btn(rq, "Submit Request", self._submit_request, color=ACCENT, width=20).pack(anchor="w", ipady=4)

        # pending requests
        label(self, "Your Pending Requests", font=FONT_MED, bg=BG).pack(anchor="w", pady=(0, 10))
        pending = list(requests_col.find({"username": self.bank.current, "status": "pending"}))
        if not pending:
            label(self, "No pending requests.", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w")
        for req in pending:
            row = make_frame(self, bg=CARD)
            row.pack(fill="x", pady=2)
            ri = make_frame(row, bg=CARD)
            ri.pack(fill="x", padx=16, pady=10)
            label(ri, req.get("description", ""), font=("Segoe UI", 9, "bold"), bg=CARD).pack(side="left")
            label(ri, f"${req.get('amount', 0):,.2f}/mo", font=FONT_SM, fg=GREEN, bg=CARD).pack(side="left", padx=12)
            label(ri, "⏳ Pending", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(side="right")

    def _submit_request(self):
        try:
            amt = float(self.req_amt.get())
        except ValueError:
            messagebox.showerror("Error", "Enter a valid amount.")
            return
        if amt < 0:
            messagebox.showerror("Error", "Amount cannot be negative.")
            return
        desc = self.req_desc.get().strip()
        if not desc:
            messagebox.showerror("Error", "Description is required.")
            return
        requests_col.insert_one({
            "username": self.bank.current,
            "amount": amt,
            "description": desc,
            "status": "pending",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        messagebox.showinfo("✓ Submitted", "Your income request has been sent to the admin.")
        self.req_amt.delete(0, "end")
        self.req_desc.delete(0, "end")
        self.app._show_income()


class HistoryPage(tk.Frame):
    def __init__(self, parent, bank: Bank, app: BankingApp):
        super().__init__(parent, bg=BG)
        self.pack(fill="both", expand=True, padx=32, pady=28)

        label(self, "Transaction History", font=("Segoe UI", 18, "bold"), bg=BG).pack(anchor="w")
        label(self, "All your account activity", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", pady=(2, 20))

        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scroll_frame = make_frame(canvas, bg=BG)

        scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Vertical.TScrollbar", background=CARD2, troughcolor=BG,
                         bordercolor=BG, arrowcolor=SUBTEXT)

        txs = list(reversed(bank.acc["transactions"]))
        if not txs:
            label(scroll_frame, "No transactions yet.", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w")
            return

        hdr = make_frame(scroll_frame, bg=BG)
        hdr.pack(fill="x", pady=(0, 6))
        for col, w in [("Date", 12), ("Description", 36), ("Type", 10), ("Amount", 12)]:
            label(hdr, col, font=("Segoe UI", 9, "bold"), fg=SUBTEXT, bg=BG, width=w,
                  anchor="w").pack(side="left")

        for tx in txs:
            row = make_frame(scroll_frame, bg=CARD)
            row.pack(fill="x", pady=2)
            inner = make_frame(row, bg=CARD)
            inner.pack(fill="x", padx=12, pady=10)
            color = GREEN if tx["type"] == "credit" else RED
            sign  = "+" if tx["type"] == "credit" else ""
            for val, w, fg in [
                (tx["date"],  12, SUBTEXT),
                (tx["desc"],  36, TEXT),
                (tx["type"].capitalize(), 10, color),
            ]:
                label(inner, val, font=FONT_SM, fg=fg, bg=CARD, width=w, anchor="w").pack(side="left")
            label(inner, f"{sign}${abs(tx['amount']):,.2f}",
                  font=("Segoe UI", 9, "bold"), fg=color, bg=CARD,
                  width=12, anchor="e").pack(side="right")

        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))


class OptionsPage(tk.Frame):
    def __init__(self, parent, bank: Bank, app: BankingApp):
        super().__init__(parent, bg=BG)
        self.bank = bank
        self.app  = app
        self.pack(fill="both", expand=True)

        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scroll_frame = make_frame(canvas, bg=BG)

        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build()

    def _build(self):
        f = self.scroll_frame
        label(f, "Options", font=("Segoe UI", 18, "bold"), bg=BG).pack(anchor="w", padx=32, pady=(28, 0))
        label(f, "Manage your account settings", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", padx=32, pady=(2, 28))

        # ── Display Name ──
        card1 = make_frame(f, bg=CARD)
        card1.pack(fill="x", padx=32, pady=(0, 12))
        inner1 = make_frame(card1, bg=CARD)
        inner1.pack(fill="x", padx=24, pady=22)
        label(inner1, "Display Name", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(inner1, "Update the name shown on your account and sidebar.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))
        label(inner1, "Current name", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.current_lbl = label(inner1, self.bank.acc["name"],
                                 font=("Segoe UI", 10, "bold"), bg=CARD, fg=ACCENT)
        self.current_lbl.pack(anchor="w", pady=(2, 14))
        label(inner1, "New name", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.name_e = entry(inner1, width=34)
        self.name_e.pack(anchor="w", ipady=8, pady=(2, 16))
        self.name_e.insert(0, self.bank.acc["name"])
        btn(inner1, "Save Name", self._save_name, color=ACCENT, width=18).pack(anchor="w", ipady=4)

        # ── Username ──
        card2 = make_frame(f, bg=CARD)
        card2.pack(fill="x", padx=32, pady=(0, 12))
        inner2 = make_frame(card2, bg=CARD)
        inner2.pack(fill="x", padx=24, pady=22)
        label(inner2, "Username", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(inner2, "Change your login username.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))
        label(inner2, "Current username", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.current_usr_lbl = label(inner2, self.bank.current,
                                     font=("Segoe UI", 10, "bold"), bg=CARD, fg=ACCENT)
        self.current_usr_lbl.pack(anchor="w", pady=(2, 14))
        label(inner2, "New username", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.usr_e = entry(inner2, width=34)
        self.usr_e.pack(anchor="w", ipady=8, pady=(2, 16))
        self.usr_e.insert(0, self.bank.current)
        btn(inner2, "Save Username", self._save_username, color=ACCENT, width=18).pack(anchor="w", ipady=4)

        # ── Password ──
        card3 = make_frame(f, bg=CARD)
        card3.pack(fill="x", padx=32, pady=(0, 12))
        inner3 = make_frame(card3, bg=CARD)
        inner3.pack(fill="x", padx=24, pady=22)
        label(inner3, "Password", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(inner3, "Choose a new password (min. 6 characters).",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))
        label(inner3, "Current password", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.cur_pwd_e = entry(inner3, show="●", width=34)
        self.cur_pwd_e.pack(anchor="w", ipady=8, pady=(2, 12))
        label(inner3, "New password", font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
        self.new_pwd_e = entry(inner3, show="●", width=34)
        self.new_pwd_e.pack(anchor="w", ipady=8, pady=(2, 16))
        btn(inner3, "Save Password", self._save_password, color=ACCENT, width=18).pack(anchor="w", ipady=4)

        # ── Theme ──
        card4 = make_frame(f, bg=CARD)
        card4.pack(fill="x", padx=32, pady=(0, 12))
        inner4 = make_frame(card4, bg=CARD)
        inner4.pack(fill="x", padx=24, pady=22)
        label(inner4, "Theme", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(inner4, "Switch between dark and light mode.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))
        other_mode = "light" if THEME["mode"] == "dark" else "dark"
        btn(inner4, f"Switch to {other_mode.capitalize()} Mode",
            self._toggle_theme, color=ACCENT2, width=24).pack(anchor="w", ipady=4)

        # ── Delete Account ──
        card5 = make_frame(f, bg=CARD)
        card5.pack(fill="x", padx=32, pady=(0, 32))
        inner5 = make_frame(card5, bg=CARD)
        inner5.pack(fill="x", padx=24, pady=22)
        label(inner5, "Delete Account", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(inner5, "Permanently delete your account. This cannot be undone.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))
        btn(inner5, "Delete My Account", self._delete_account, color=RED, width=22).pack(anchor="w", ipady=4)

    def _toggle_theme(self):
        new_mode = "light" if THEME["mode"] == "dark" else "dark"
        apply_theme(new_mode)
        self.app._show_dashboard()

    def _delete_account(self):
        if not messagebox.askyesno("Delete Account",
                f"Are you sure you want to delete '{self.bank.current}'?\nThis cannot be undone."):
            return
        username = self.bank.current
        self.bank.logout()
        del self.bank.accounts[username]
        users_col.delete_one({"username": username})
        requests_col.delete_many({"username": username})
        messagebox.showinfo("Deleted", "Your account has been deleted.")
        self.app._show_login()

    def _save_name(self):
        new_name = self.name_e.get().strip()
        if not new_name:
            messagebox.showerror("Error", "Name cannot be empty.")
            return
        self.bank.acc["name"] = new_name
        users_col.update_one({"username": self.bank.current}, {"$set": {"name": new_name}})
        self.current_lbl.configure(text=new_name)
        if hasattr(self.app, "sidebar_name_lbl") and self.app.sidebar_name_lbl.winfo_exists():
            self.app.sidebar_name_lbl.configure(text=new_name)
        messagebox.showinfo("✓ Saved", f"Name updated to \"{new_name}\".")

    def _save_username(self):
        new_usr = self.usr_e.get().strip()
        if not new_usr:
            messagebox.showerror("Error", "Username cannot be empty.")
            return
        if new_usr == self.bank.current:
            messagebox.showerror("Error", "That's already your username.")
            return
        if new_usr in self.bank.accounts:
            messagebox.showerror("Error", "Username already taken.")
            return
        old = self.bank.current
        self.bank.accounts[new_usr] = self.bank.accounts.pop(old)
        self.bank.current = new_usr
        users_col.update_one({"username": old}, {"$set": {"username": new_usr}})
        requests_col.update_many({"username": old}, {"$set": {"username": new_usr}})
        self.current_usr_lbl.configure(text=new_usr)
        messagebox.showinfo("✓ Saved", f"Username changed to \"{new_usr}\".")

    def _save_password(self):
        cur = self.cur_pwd_e.get()
        new = self.new_pwd_e.get()
        if cur != self.bank.acc["password"]:
            messagebox.showerror("Error", "Current password is incorrect.")
            return
        if len(new) < 6:
            messagebox.showerror("Error", "New password must be at least 6 characters.")
            return
        self.bank.acc["password"] = new
        users_col.update_one({"username": self.bank.current}, {"$set": {"password": new}})
        self.cur_pwd_e.delete(0, "end")
        self.new_pwd_e.delete(0, "end")
        messagebox.showinfo("✓ Saved", "Password updated successfully.")


# ── Admin Page ────────────────────────────────────────────────────────────────
class AdminPage(tk.Frame):
    def __init__(self, app: BankingApp):
        super().__init__(app, bg=BG)
        self.app = app
        self.pack(fill="both", expand=True)
        self._build()

    def _build(self):
        topbar = make_frame(self, bg="#0A0C12")
        topbar.pack(fill="x")
        inner_top = make_frame(topbar, bg="#0A0C12")
        inner_top.pack(fill="x", padx=24, pady=14)
        tk.Label(inner_top, text="◈  NeoBank Admin", font=("Segoe UI", 14, "bold"),
                 fg=ACCENT, bg="#0A0C12").pack(side="left")

        # tab buttons
        self.tab_var = tk.StringVar(value="accounts")
        tab_frame = make_frame(inner_top, bg="#0A0C12")
        tab_frame.pack(side="left", padx=24)
        for label_text, val in [("Accounts", "accounts"), ("Income Requests", "requests")]:
            tb = tk.Button(tab_frame, text=label_text,
                           command=lambda v=val: self._switch_tab(v),
                           bg="#0A0C12", fg=SUBTEXT, font=("Segoe UI", 9),
                           relief="flat", padx=12, pady=4,
                           activebackground=CARD, activeforeground=TEXT,
                           cursor="hand2", bd=0)
            tb.pack(side="left", padx=4)

        btn(inner_top, "⏻  Exit Admin", self._exit,
            color="#1C2333", fg=RED, width=14).pack(side="right")

        sep(self, bg=BORDER).pack(fill="x")

        self.main = make_frame(self, bg=BG)
        self.main.pack(fill="both", expand=True)

        self._show_accounts_tab()

    def _switch_tab(self, tab):
        for w in self.main.winfo_children():
            w.destroy()
        if tab == "accounts":
            self._show_accounts_tab()
        else:
            self._show_requests_tab()

    # ── Accounts tab ──
    def _show_accounts_tab(self):
        left = make_frame(self.main, bg=CARD, width=220)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        label(left, "Accounts", font=FONT_MED, bg=CARD).pack(anchor="w", padx=16, pady=(16, 8))
        sep(left, bg=BORDER).pack(fill="x", padx=8)

        self.user_list_frame = make_frame(left, bg=CARD)
        self.user_list_frame.pack(fill="both", expand=True, pady=8)

        btn(left, "+ New Account", self._new_account_dialog,
            color=GREEN, fg="#0D0F14", width=18).pack(fill="x", padx=12, pady=12)

        self.right = make_frame(self.main, bg=BG)
        self.right.pack(side="left", fill="both", expand=True)

        self._refresh_user_list()
        label(self.right, "Select an account from the left.",
              font=FONT_SM, fg=SUBTEXT, bg=BG).pack(expand=True)

    def _refresh_user_list(self, select=None):
        for w in self.user_list_frame.winfo_children():
            w.destroy()
        for username in self.app.bank.accounts:
            u = username
            b = tk.Button(self.user_list_frame, text=f"  {u}",
                          font=("Segoe UI", 9), bg=CARD, fg=TEXT,
                          relief="flat", anchor="w", padx=8, pady=7,
                          activebackground=CARD2, activeforeground=ACCENT,
                          cursor="hand2", bd=0,
                          command=lambda x=u: self._select_user(x))
            b.pack(fill="x", padx=4)
            b.bind("<Enter>", lambda e, b=b: b.configure(bg=CARD2))
            b.bind("<Leave>", lambda e, b=b: b.configure(bg=CARD))
        if select:
            self._select_user(select)

    def _select_user(self, username):
        for w in self.right.winfo_children():
            w.destroy()

        acc = self.app.bank.accounts[username]

        hdr = make_frame(self.right, bg=BG)
        hdr.pack(fill="x", padx=32, pady=(24, 0))
        label(hdr, f"Editing: {username}", font=("Segoe UI", 16, "bold"), bg=BG).pack(side="left", anchor="w")
        btn(hdr, "🗑  Delete Account", lambda: self._delete_user(username),
            color=RED, fg=TEXT, width=18).pack(side="right")

        sep(self.right, bg=BORDER).pack(fill="x", padx=32, pady=12)

        canvas = tk.Canvas(self.right, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.right, orient="vertical", command=canvas.yview)
        sf = make_frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        def field(parent, lbl, default, show=None):
            label(parent, lbl, font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w")
            e = entry(parent, show=show, width=36)
            e.pack(anchor="w", ipady=8, pady=(2, 14))
            e.insert(0, default)
            return e

        f = sf

        # Name
        card1 = make_frame(f, bg=CARD)
        card1.pack(fill="x", padx=32, pady=(0, 12))
        i1 = make_frame(card1, bg=CARD)
        i1.pack(fill="x", padx=24, pady=18)
        label(i1, "Display Name", font=FONT_MED, bg=CARD).pack(anchor="w")
        name_e = field(i1, "Name", acc["name"])
        def save_name():
            v = name_e.get().strip()
            if not v: messagebox.showerror("Error", "Name cannot be empty."); return
            self.app.bank.accounts[username]["name"] = v
            users_col.update_one({"username": username}, {"$set": {"name": v}})
            messagebox.showinfo("✓ Saved", "Name updated.")
        btn(i1, "Save Name", save_name, color=ACCENT, width=16).pack(anchor="w", ipady=4)

        # Username
        card2 = make_frame(f, bg=CARD)
        card2.pack(fill="x", padx=32, pady=(0, 12))
        i2 = make_frame(card2, bg=CARD)
        i2.pack(fill="x", padx=24, pady=18)
        label(i2, "Username", font=FONT_MED, bg=CARD).pack(anchor="w")
        usr_e = field(i2, "Username", username)
        def save_username():
            new = usr_e.get().strip()
            if not new: messagebox.showerror("Error", "Username cannot be empty."); return
            if new == username: messagebox.showerror("Error", "Same as current username."); return
            if new in self.app.bank.accounts: messagebox.showerror("Error", "Username taken."); return
            self.app.bank.accounts[new] = self.app.bank.accounts.pop(username)
            users_col.update_one({"username": username}, {"$set": {"username": new}})
            messagebox.showinfo("✓ Saved", f"Username changed to \"{new}\".")
            self._refresh_user_list(select=new)
        btn(i2, "Save Username", save_username, color=ACCENT, width=16).pack(anchor="w", ipady=4)

        # Password
        card3 = make_frame(f, bg=CARD)
        card3.pack(fill="x", padx=32, pady=(0, 12))
        i3 = make_frame(card3, bg=CARD)
        i3.pack(fill="x", padx=24, pady=18)
        label(i3, "Password", font=FONT_MED, bg=CARD).pack(anchor="w")
        pwd_e = field(i3, "New password", "", show="●")
        def save_password():
            new = pwd_e.get()
            if len(new) < 6: messagebox.showerror("Error", "Min. 6 characters."); return
            self.app.bank.accounts[username]["password"] = new
            users_col.update_one({"username": username}, {"$set": {"password": new}})
            pwd_e.delete(0, "end")
            messagebox.showinfo("✓ Saved", "Password updated.")
        btn(i3, "Save Password", save_password, color=ACCENT, width=16).pack(anchor="w", ipady=4)

        # Balance
        card4 = make_frame(f, bg=CARD)
        card4.pack(fill="x", padx=32, pady=(0, 12))
        i4 = make_frame(card4, bg=CARD)
        i4.pack(fill="x", padx=24, pady=18)
        label(i4, "Balance", font=FONT_MED, bg=CARD).pack(anchor="w")
        bal_e = field(i4, "Balance ($)", str(acc["balance"]))
        def save_balance():
            try: v = float(bal_e.get())
            except ValueError: messagebox.showerror("Error", "Enter a valid number."); return
            self.app.bank.accounts[username]["balance"] = v
            users_col.update_one({"username": username}, {"$set": {"balance": v}})
            messagebox.showinfo("✓ Saved", f"Balance set to ${v:,.2f}.")
        btn(i4, "Save Balance", save_balance, color=ACCENT, width=16).pack(anchor="w", ipady=4)

        # Income
        card4b = make_frame(f, bg=CARD)
        card4b.pack(fill="x", padx=32, pady=(0, 12))
        i4b = make_frame(card4b, bg=CARD)
        i4b.pack(fill="x", padx=24, pady=18)
        label(i4b, "Monthly Income", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(i4b, "Amount automatically added at the start of each month.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(2, 14))
        inc_e = field(i4b, "Monthly Income ($)", str(acc.get("income", 0.0)))
        def save_income():
            try: v = float(inc_e.get())
            except ValueError: messagebox.showerror("Error", "Enter a valid number."); return
            if v < 0: messagebox.showerror("Error", "Income cannot be negative."); return
            self.app.bank.accounts[username]["income"] = v
            users_col.update_one({"username": username}, {"$set": {"income": v}})
            messagebox.showinfo("✓ Saved", f"Monthly income set to ${v:,.2f}.")
        btn(i4b, "Save Income", save_income, color=ACCENT, width=16).pack(anchor="w", ipady=4)

        # Transactions
        card5 = make_frame(f, bg=CARD)
        card5.pack(fill="x", padx=32, pady=(0, 32))
        i5 = make_frame(card5, bg=CARD)
        i5.pack(fill="x", padx=24, pady=18)
        label(i5, "Transactions", font=FONT_MED, bg=CARD).pack(anchor="w")
        label(i5, f"{len(acc['transactions'])} transaction(s) on record.",
              font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w", pady=(4, 12))
        def clear_transactions():
            if not messagebox.askyesno("Confirm", "Clear all transactions for this user?"): return
            self.app.bank.accounts[username]["transactions"] = []
            users_col.update_one({"username": username}, {"$set": {"transactions": []}})
            messagebox.showinfo("✓ Done", "Transactions cleared.")
            self._select_user(username)
        btn(i5, "Clear Transactions", clear_transactions, color=RED, width=20).pack(anchor="w", ipady=4)

    def _delete_user(self, username):
        if not messagebox.askyesno("Delete", f"Delete account '{username}'? This cannot be undone."):
            return
        del self.app.bank.accounts[username]
        users_col.delete_one({"username": username})
        requests_col.delete_many({"username": username})
        for w in self.right.winfo_children():
            w.destroy()
        label(self.right, "Select an account from the left.",
              font=FONT_SM, fg=SUBTEXT, bg=BG).pack(expand=True)
        self._refresh_user_list()
        messagebox.showinfo("Deleted", f"Account '{username}' deleted.")

    def _new_account_dialog(self):
        win = tk.Toplevel(self.app)
        win.title("New Account")
        win.configure(bg=CARD)
        win.geometry("340x380")
        win.resizable(False, False)

        f = make_frame(win, bg=CARD)
        f.pack(padx=32, pady=32, fill="both", expand=True)

        label(f, "Create Account", font=FONT_MED, bg=CARD).pack(anchor="w", pady=(0, 16))

        fields = {}
        for lbl, key, sh in [
            ("Full Name", "name", None),
            ("Username",  "usr",  None),
            ("Password",  "pwd",  "●"),
        ]:
            label(f, lbl, font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(anchor="w")
            e = entry(f, show=sh, width=30)
            e.pack(fill="x", ipady=7, pady=(2, 10))
            fields[key] = e

        def create():
            ok, msg = self.app.bank.register(
                fields["usr"].get().strip(),
                fields["pwd"].get(),
                fields["name"].get().strip(),
            )
            if ok:
                new_usr = fields["usr"].get().strip()
                win.destroy()
                messagebox.showinfo("✓ Created", msg)
                self._refresh_user_list()
                self._select_user(new_usr)
            else:
                messagebox.showerror("Error", msg)

        btn(f, "Create Account", create, color=GREEN, fg="#0D0F14", width=24).pack(fill="x", ipady=4, pady=(8, 0))

    # ── Requests tab ──
    def _show_requests_tab(self):
        wrapper = make_frame(self.main, bg=BG)
        wrapper.pack(fill="both", expand=True)

        label(wrapper, "Income Requests", font=("Segoe UI", 16, "bold"), bg=BG).pack(anchor="w", padx=32, pady=(24, 4))
        label(wrapper, "Review and approve or reject user income change requests.",
              font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", padx=32, pady=(0, 16))

        canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=canvas.yview)
        sf = make_frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        pending = list(requests_col.find({"status": "pending"}))
        if not pending:
            label(sf, "No pending requests.", font=FONT_SM, fg=SUBTEXT, bg=BG).pack(anchor="w", padx=32, pady=16)
            return

        for req in pending:
            card = make_frame(sf, bg=CARD)
            card.pack(fill="x", padx=32, pady=(0, 10))
            inner = make_frame(card, bg=CARD)
            inner.pack(fill="x", padx=24, pady=16)

            top_row = make_frame(inner, bg=CARD)
            top_row.pack(fill="x")
            label(top_row, req["username"], font=("Segoe UI", 10, "bold"), bg=CARD, fg=ACCENT).pack(side="left")
            label(top_row, req.get("date", ""), font=FONT_SM, fg=SUBTEXT, bg=CARD).pack(side="right")

            label(inner, f"Requested income: ${req.get('amount', 0):,.2f} / month",
                  font=("Segoe UI", 10, "bold"), fg=GREEN, bg=CARD).pack(anchor="w", pady=(6, 2))
            label(inner, f"Source: {req.get('description', '')}",
                  font=FONT_SM, fg=TEXT, bg=CARD).pack(anchor="w", pady=(0, 12))

            btn_row = make_frame(inner, bg=CARD)
            btn_row.pack(anchor="w")

            rid = req["_id"]
            uname = req["username"]
            amt = req.get("amount", 0)

            def approve(r=rid, u=uname, a=amt):
                if u not in self.app.bank.accounts:
                    messagebox.showerror("Error", "User no longer exists.")
                    requests_col.update_one({"_id": r}, {"$set": {"status": "rejected"}})
                    self._switch_tab("requests")
                    return
                self.app.bank.accounts[u]["income"] = a
                users_col.update_one({"username": u}, {"$set": {"income": a}})
                requests_col.update_one({"_id": r}, {"$set": {"status": "approved"}})
                messagebox.showinfo("✓ Approved", f"Income for {u} set to ${a:,.2f}/mo.")
                self._switch_tab("requests")

            def reject(r=rid):
                requests_col.update_one({"_id": r}, {"$set": {"status": "rejected"}})
                self._switch_tab("requests")

            btn(btn_row, "✓ Approve", approve, color=GREEN, fg="#0D0F14", width=12).pack(side="left", ipady=4)
            btn(btn_row, "✗ Reject", reject, color=RED, width=12).pack(side="left", padx=(8, 0), ipady=4)

    def _exit(self):
        self.app._show_login()


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BankingApp()
    app.mainloop()