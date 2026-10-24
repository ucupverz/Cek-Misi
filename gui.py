#!/usr/bin/env python3
"""Hamba Ku - Aplikasi Desktop (GUI).

Jalankan dari source:   python gui.py
Bangun jadi .exe:       lihat build_exe.bat / README.md
"""

import asyncio
import builtins
import getpass
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# ---------------------------------------------------------------------
# Folder data: semua file (sesi, hasil, daftar akun) disimpan di sebelah
# aplikasi / .exe agar mudah ditemukan.
# ---------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# ---------------------------------------------------------------------
# Tangkap semua print() dari modul lama supaya tampil di panel log.
# HARUS dipasang sebelum modul lain di-import (colorama membungkus stdout).
# ---------------------------------------------------------------------
LOG_QUEUE: "queue.Queue" = queue.Queue()
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class LogStream:
    def __init__(self):
        self._buf = ""

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        self._buf += ANSI_RE.sub("", text)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            LOG_QUEUE.put(("log", line.rstrip("\r")))
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


sys.stdout = LogStream()
sys.stderr = sys.stdout

import customtkinter as ctk  # noqa: E402
from telethon.errors import FloodWaitError  # noqa: E402,F401

import cek_misi_termux  # noqa: E402
import daftar_akun_fresh as daf  # noqa: E402
import shopee_core  # noqa: E402
import voucher_claim  # noqa: E402

APP_NAME = "Hamba Ku"
APP_VERSION = "2.0"

# Palet warna
C_BG = "#0f1115"
C_SIDEBAR = "#14171d"
C_CARD = "#1b1f27"
C_CARD_ALT = "#232834"
C_BORDER = "#2a303c"
C_ACCENT = "#ee4d2d"
C_ACCENT_HOVER = "#d63f21"
C_TEXT = "#e8eaed"
C_MUTED = "#8b93a1"
C_OK = "#3ecf8e"
C_WARN = "#f5a623"
C_ERR = "#ff5d5d"
C_INFO = "#5aa9ff"

FEATURES = {
    "claim": {
        "nav": "Klaim Voucher",
        "title": "Klaim Voucher ShopeeFood",
        "desc": "Klaim voucher ShopeeFood (NEWFOODIES + ONGKIRGRATIS) otomatis lewat @shp_tools_bot, keduanya untuk setiap akun.",
        "delay": 4.0,
        "hint": "Satu akun per baris: email, username, atau ID.",
    },
    "misi": {
        "nav": "Cek Misi QRIS",
        "title": "Cek Misi Bayar QRIS",
        "desc": "Periksa progres koin check-in bayar QRIS tiap akun dan catat hasilnya ke CSV.",
        "delay": 2.5,
        "hint": "Satu username (atau raw cookie) per baris.",
    },
    "food": {
        "nav": "Cek Voucher Food",
        "title": "Cek Voucher Shopee Food",
        "desc": "Cek ketersediaan voucher Diskon 25RB & Ongkir 12RB. Akun lolos disimpan ke valid_food.txt.",
        "delay": 2.5,
        "hint": "Satu username (atau raw cookie) per baris.",
    },
    "both": {
        "nav": "Cek Keduanya",
        "title": "Cek Misi QRIS + Voucher Food",
        "desc": "Periksa Misi QRIS dan Voucher Food sekaligus, bergantian untuk setiap akun.",
        "delay": 2.5,
        "hint": "Satu username (atau raw cookie) per baris.",
    },
    "register": {
        "nav": "Daftar Akun",
        "title": "Daftar Akun",
        "desc": "Daftarkan akun ShopeeFood baru otomatis lewat @shp_tools_bot: nomor otomatis, OTP (diurus bot), pilih fingerprint, lalu simpan hasilnya. Gagal? Diulang otomatis dari /account.",
        "delay": 6.0,
        "hint": "",
    },
}

RESULT_FILES = [
    ("hasil_gabungan.csv", "Gabungan (Misi + Food)"),
    ("hasil_voucher_food.csv", "Voucher Food"),
    ("hasil_cek_misi.csv", "Misi QRIS"),
    ("valid_food.txt", "Akun lolos Food"),
    ("diskon_25rb.txt", "Akun diskon 25RB"),
    ("misi_selesai.txt", "Misi selesai"),
    ("bot_responses.txt", "Respons klaim voucher"),
    ("akun_fresh.txt", "Akun fresh hasil daftar"),
    ("akun_fresh_cookies.txt", "Cookie akun fresh"),
    ("akun_fresh_failed.txt", "Pendaftaran gagal"),
]


def open_path(path: Path) -> None:
    """Buka file / folder dengan aplikasi bawaan OS."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Tidak bisa membuka:\n{path}\n\n{exc}")


# =====================================================================
# Dialog input (pengganti input()/getpass untuk login Telegram, dll.)
# =====================================================================
class PromptDialog(ctk.CTkToplevel):
    def __init__(self, master, prompt: str, secret: bool, on_done):
        super().__init__(master)
        self._on_done = on_done
        self._finished = False
        text = prompt.strip().rstrip(":").strip() or "Input"
        self.title("Login Telegram" if "telepon" in text.lower() or "kode" in text.lower()
                   or "2fa" in text.lower() else APP_NAME)
        self.configure(fg_color=C_CARD)
        self.resizable(False, False)
        self.geometry("420x210")
        self.transient(master)

        ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C_TEXT, wraplength=370, justify="left").pack(
            anchor="w", padx=24, pady=(22, 8))
        hint = ""
        if "telepon" in text.lower():
            hint = "Format internasional, contoh: +6281234567890"
        elif "kode" in text.lower():
            hint = "Cek aplikasi Telegram Anda, kode dikirim lewat chat Telegram."
        elif "2fa" in text.lower():
            hint = "Kosongkan jika akun Telegram Anda tidak memakai password 2FA."
        if hint:
            ctk.CTkLabel(self, text=hint, text_color=C_MUTED, wraplength=370,
                         justify="left", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=24)

        self.entry = ctk.CTkEntry(self, width=372, height=38, show="•" if secret else "",
                                  fg_color=C_CARD_ALT, border_color=C_BORDER)
        self.entry.pack(padx=24, pady=(12, 14))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24)
        ctk.CTkButton(row, text="Batal", width=100, fg_color=C_CARD_ALT, hover_color=C_BORDER,
                      command=lambda: self._finish(None)).pack(side="right", padx=(8, 0))
        ctk.CTkButton(row, text="OK", width=100, fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                      command=lambda: self._finish(self.entry.get())).pack(side="right")
        self.entry.bind("<Return>", lambda _e: self._finish(self.entry.get()))
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))
        self.after(120, self._focus)

    def _focus(self):
        try:
            self.grab_set()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _finish(self, value):
        if self._finished:
            return
        self._finished = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self._on_done(value)


# =====================================================================
# Komponen UI kecil
# =====================================================================
def card(master, **kw):
    return ctk.CTkFrame(master, fg_color=C_CARD, corner_radius=14,
                        border_width=1, border_color=C_BORDER, **kw)


def label(master, text, size=13, weight="normal", color=C_TEXT, **kw):
    return ctk.CTkLabel(master, text=text, text_color=color,
                        font=ctk.CTkFont(size=size, weight=weight), **kw)


def primary_button(master, text, command, width=140, height=38, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=height,
                         fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER, corner_radius=10,
                         font=ctk.CTkFont(size=13, weight="bold"), **kw)


def ghost_button(master, text, command, width=120, height=34, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=height,
                         fg_color=C_CARD_ALT, hover_color=C_BORDER, text_color=C_TEXT,
                         corner_radius=10, **kw)


# =====================================================================
# Halaman: Beranda
# =====================================================================
class HomePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        label(self, "Selamat datang wahai hamba ku", 26, "bold").pack(anchor="w")
        label(self, "Silakan sembah saya. Pilih fitur yang ingin dijalankan, semua proses berjalan otomatis lewat Telegram.",
              13, color=C_MUTED).pack(anchor="w", pady=(2, 18))

        self.status = card(self)
        self.status.pack(fill="x", pady=(0, 18))
        inner = ctk.CTkFrame(self.status, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)
        self.status_title = label(inner, "", 14, "bold")
        self.status_title.pack(anchor="w")
        self.status_desc = label(inner, "", 12, color=C_MUTED)
        self.status_desc.pack(anchor="w", pady=(2, 0))
        self.status_btn = ghost_button(inner, "Buka Pengaturan", lambda: app.show("settings"), width=150)
        self.status_btn.place(relx=1.0, rely=0.5, anchor="e")

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="c")
        for i, (key, f) in enumerate(FEATURES.items()):
            c = card(grid)
            c.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 9, 9 if i % 2 == 0 else 0),
                   pady=(0 if i < 2 else 9, 9 if i < 2 else 0))
            label(c, f["title"], 16, "bold").pack(anchor="w", padx=20, pady=(18, 4))
            label(c, f["desc"], 12, color=C_MUTED, wraplength=360, justify="left").pack(
                anchor="w", padx=20)
            primary_button(c, "Buka", lambda k=key: app.show(k), width=100, height=34).pack(
                anchor="w", padx=20, pady=(14, 18))

        self.refresh()

    def refresh(self):
        api_id, api_hash = shopee_core.load_credentials()
        sessions = [p for p in Path(".").glob("*.session")]
        if api_id and api_hash:
            self.status_title.configure(text="API Telegram sudah dikonfigurasi", text_color=C_OK)
            ses = f"{len(sessions)} sesi login tersimpan" if sessions else "Belum login, Anda akan diminta nomor HP saat pertama kali menjalankan fitur."
            self.status_desc.configure(text=ses)
            self.status_btn.configure(text="Pengaturan")
        else:
            self.status_title.configure(text="API Telegram belum diisi", text_color=C_WARN)
            self.status_desc.configure(text="Isi API ID & API HASH dari my.telegram.org di menu Pengaturan sebelum mulai.")
            self.status_btn.configure(text="Isi Sekarang")


# =====================================================================
# Halaman: Fitur (dipakai ulang untuk klaim / misi / food / keduanya)
# =====================================================================
class TaskPage(ctk.CTkFrame):
    def __init__(self, master, app, mode: str):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.mode = mode
        self.cfg = FEATURES[mode]
        self.ok = self.warn = self.fail = 0

        label(self, self.cfg["title"], 24, "bold").pack(anchor="w")
        label(self, self.cfg["desc"], 12, color=C_MUTED, wraplength=820, justify="left").pack(
            anchor="w", pady=(2, 14))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=4, uniform="a", minsize=300)
        body.grid_columnconfigure(1, weight=6, uniform="a")
        body.grid_rowconfigure(0, weight=1)

        self._build_accounts(body)
        self._build_right(body)

    # ---------- kolom kiri: daftar akun ----------
    def _build_accounts(self, body):
        left = card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 4))
        label(head, "Daftar Akun", 15, "bold").pack(side="left")
        self.count_lbl = label(head, "0 akun", 12, color=C_MUTED)
        self.count_lbl.pack(side="right")
        label(left, self.cfg["hint"], 11, color=C_MUTED).pack(anchor="w", padx=16)

        self.textbox = ctk.CTkTextbox(left, fg_color=C_CARD_ALT, border_width=1, border_color=C_BORDER,
                                      corner_radius=10, font=ctk.CTkFont(family="Consolas", size=12),
                                      text_color=C_TEXT, wrap="none")
        self.textbox.pack(fill="both", expand=True, padx=16, pady=10)
        self.textbox.bind("<KeyRelease>", lambda _e: self._update_count())
        self.textbox.bind("<<Paste>>", lambda _e: self.after(50, self._update_count))

        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        ghost_button(row, "Buka File...", self.load_file, width=100).pack(side="left")
        ghost_button(row, "Simpan...", self.save_file, width=80).pack(side="left", padx=6)
        ghost_button(row, "Kosongkan", self.clear_accounts, width=84).pack(side="left")

        self._autoload_default_file()

    # ---------- kolom kanan: opsi + kontrol + log ----------
    def _build_right(self, body):
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Opsi
        opt = card(right)
        opt.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        opt.grid_columnconfigure(1, weight=1)
        r = 0
        if self.mode == "claim":
            label(opt, "Voucher", 12, color=C_MUTED).grid(row=r, column=0, sticky="w", padx=(16, 10), pady=(14, 6))
            vrow = ctk.CTkFrame(opt, fg_color="transparent")
            vrow.grid(row=r, column=1, sticky="w", pady=(14, 6))
            self.voucher_vars = {}
            for name in voucher_claim.DEFAULT_VOUCHERS:
                var = tk.BooleanVar(value=True)
                self.voucher_vars[name] = var
                ctk.CTkCheckBox(vrow, text=name, variable=var, fg_color=C_ACCENT,
                                hover_color=C_ACCENT_HOVER, text_color=C_TEXT).pack(side="left", padx=(0, 16))
            r += 1
            label(opt, "Tautan tambahan", 12, color=C_MUTED).grid(row=r, column=0, sticky="w", padx=(16, 10), pady=6)
            self.link_entry = ctk.CTkEntry(opt, height=34, fg_color=C_CARD_ALT, border_color=C_BORDER,
                                           placeholder_text="opsional: tautan voucher lain")
            self.link_entry.grid(row=r, column=1, sticky="ew", padx=(0, 16), pady=6)
            r += 1
        else:
            label(opt, "Metode akun", 12, color=C_MUTED).grid(row=r, column=0, sticky="w", padx=(16, 10), pady=(14, 6))
            self.method = ctk.CTkSegmentedButton(
                opt, values=["Otomatis", "Username", "Cookie"], selected_color=C_ACCENT,
                selected_hover_color=C_ACCENT_HOVER, unselected_color=C_CARD_ALT,
                unselected_hover_color=C_BORDER, fg_color=C_CARD_ALT)
            self.method.set("Otomatis")
            self.method.grid(row=r, column=1, sticky="w", pady=(14, 6))
            r += 1

        label(opt, "Jeda antar akun", 12, color=C_MUTED).grid(row=r, column=0, sticky="w", padx=(16, 10), pady=6)
        drow = ctk.CTkFrame(opt, fg_color="transparent")
        drow.grid(row=r, column=1, sticky="w", pady=6)
        self.delay_var = tk.DoubleVar(value=self.cfg["delay"])
        self.delay_slider = ctk.CTkSlider(drow, from_=1, to=10, number_of_steps=18, width=200,
                                          variable=self.delay_var, button_color=C_ACCENT,
                                          button_hover_color=C_ACCENT_HOVER, progress_color=C_ACCENT,
                                          command=lambda _v: self._update_delay_label())
        self.delay_slider.pack(side="left")
        self.delay_lbl = label(drow, "", 12, color=C_TEXT)
        self.delay_lbl.pack(side="left", padx=10)
        self._update_delay_label()
        r += 1

        if self.mode != "claim":
            self.resume_var = tk.BooleanVar(value=True)
            ctk.CTkSwitch(opt, text="Lewati akun yang sudah ada hasilnya (resume)", variable=self.resume_var,
                          progress_color=C_ACCENT, text_color=C_TEXT).grid(
                row=r, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 14))
        else:
            ctk.CTkFrame(opt, height=8, fg_color="transparent").grid(row=r, column=0)

        # Kontrol + progres
        ctl = card(right)
        ctl.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        top = ctk.CTkFrame(ctl, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        self.start_btn = primary_button(top, "Mulai", self.start, width=130, height=40)
        self.start_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(top, text="Berhenti", width=100, height=40, state="disabled",
                                      fg_color=C_CARD_ALT, hover_color=C_BORDER, corner_radius=10,
                                      command=self.stop)
        self.stop_btn.pack(side="left", padx=8)
        self.state_lbl = label(top, "Siap", 12, color=C_MUTED)
        self.state_lbl.pack(side="right")

        self.progress = ctk.CTkProgressBar(ctl, height=10, progress_color=C_ACCENT, fg_color=C_CARD_ALT)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(4, 6))
        stats = ctk.CTkFrame(ctl, fg_color="transparent")
        stats.pack(fill="x", padx=16, pady=(0, 14))
        self.prog_lbl = label(stats, "0 / 0", 12, color=C_MUTED)
        self.prog_lbl.pack(side="left")
        self.fail_lbl = label(stats, "Gagal 0", 12, color=C_ERR)
        self.fail_lbl.pack(side="right")
        self.warn_lbl = label(stats, "Perhatian 0", 12, color=C_WARN)
        self.warn_lbl.pack(side="right", padx=14)
        self.ok_lbl = label(stats, "Berhasil 0", 12, color=C_OK)
        self.ok_lbl.pack(side="right")

        # Log
        logc = card(right)
        logc.grid(row=2, column=0, sticky="nsew")
        lh = ctk.CTkFrame(logc, fg_color="transparent")
        lh.pack(fill="x", padx=16, pady=(12, 0))
        label(lh, "Log", 14, "bold").pack(side="left")
        ghost_button(lh, "Bersihkan", self.clear_log, width=80, height=26).pack(side="right")
        self.log = ctk.CTkTextbox(logc, fg_color=C_BG, border_width=0, corner_radius=10,
                                  font=ctk.CTkFont(family="Consolas", size=12), text_color=C_TEXT,
                                  wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=10)
        tb = self.log._textbox
        tb.tag_configure("ok", foreground=C_OK)
        tb.tag_configure("warn", foreground=C_WARN)
        tb.tag_configure("err", foreground=C_ERR)
        tb.tag_configure("info", foreground=C_INFO)
        tb.tag_configure("muted", foreground=C_MUTED)

    # ---------- util ----------
    def _update_delay_label(self):
        self.delay_lbl.configure(text=f"{self.delay_var.get():.1f} detik")

    def _autoload_default_file(self):
        default = {"claim": "accounts.txt", "misi": "daftar_username.txt",
                   "food": "food.txt", "both": "daftar_username.txt"}[self.mode]
        p = BASE_DIR / default
        if p.is_file():
            try:
                self.textbox.insert("1.0", p.read_text(encoding="utf-8-sig", errors="ignore"))
            except OSError:
                pass
        self._update_count()

    def _parse_accounts(self):
        text = self.textbox.get("1.0", "end")
        if self.mode == "claim":
            seen, out = set(), []
            for line in text.splitlines():
                s = line.strip()
                if not s or s.startswith("#") or s.casefold() in seen:
                    continue
                seen.add(s.casefold())
                out.append(s)
            return out
        return shopee_core.parse_raw_accounts(text, self._auth_method())

    def _auth_method(self):
        if self.mode == "claim":
            return "username"
        return {"Otomatis": "auto", "Username": "username", "Cookie": "cookie"}[self.method.get()]

    def _update_count(self):
        try:
            n = len(self._parse_accounts())
        except Exception:
            n = 0
        self.count_lbl.configure(text=f"{n} akun")

    def load_file(self):
        path = filedialog.askopenfilename(
            title="Pilih file daftar akun", initialdir=str(BASE_DIR),
            filetypes=[("File teks", "*.txt"), ("Semua file", "*.*")])
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Gagal membaca file:\n{exc}")
            return
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", content)
        self._update_count()

    def save_file(self):
        path = filedialog.asksaveasfilename(
            title="Simpan daftar akun", initialdir=str(BASE_DIR), defaultextension=".txt",
            filetypes=[("File teks", "*.txt")])
        if not path:
            return
        try:
            Path(path).write_text(self.textbox.get("1.0", "end").strip() + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Gagal menyimpan:\n{exc}")

    def clear_accounts(self):
        self.textbox.delete("1.0", "end")
        self._update_count()

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------- log & progres ----------
    PROG_RE = re.compile(r"^\[[█░]+\]\s*([\d.]+)%\s*\((\d+)/(\d+)\)\s*(.*)$")

    def handle_line(self, line: str):
        m = self.PROG_RE.match(line.strip())
        if m:
            cur, total = int(m.group(2)), int(m.group(3))
            self.progress.set(cur / total if total else 0)
            self.prog_lbl.configure(text=f"{cur} / {total}")
            self._append(f"[{cur}/{total}] {m.group(4)}", "info")
            return
        s = line.strip()
        tag = None
        if "└─" in s:
            if "❌" in s or "Error" in s or "GAGAL" in s.upper():
                tag = "err"
                self.fail += 1
            elif "⚠" in s or "❓" in s or "TIDAK" in s.upper() or "BELUM" in s.upper():
                tag = "warn"
                self.warn += 1
            else:
                tag = "ok"
                self.ok += 1
            self._refresh_stats()
        elif s.startswith("❌"):
            tag = "err"
        elif s.startswith(("⚠", "ℹ")):
            tag = "warn"
        elif s.startswith("✅"):
            tag = "ok"
        elif re.fullmatch(r"[=\-─━]{5,}", s):
            tag = "muted"
        self._append(line, tag)

    EMOJI_MAP = {"❌": "✗", "✅": "✓", "⚠️": "!", "⚠": "!", "ℹ️": "i", "ℹ": "i", "❓": "?",
                 "🎯": "", "🍔": "", "🎟️": "", "🎟": "", "🍪": "", "▶": "▸", "📂": "»",
                 "📋": "»", "🔗": "»", "👥": "", "🚀": "", "🎉": "", "👉": "»", "💡": "i", "⏹": "■"}

    def _append(self, text: str, tag=None):
        for k, v in self.EMOJI_MAP.items():
            text = text.replace(k, v)
        text = text.replace("\ufe0f", "")
        self.log.configure(state="normal")
        self.log._textbox.insert("end", text + "\n", tag if tag else ())
        self.log.configure(state="disabled")
        self.log.see("end")

    def _refresh_stats(self):
        self.ok_lbl.configure(text=f"Berhasil {self.ok}")
        self.warn_lbl.configure(text=f"Perhatian {self.warn}")
        self.fail_lbl.configure(text=f"Gagal {self.fail}")

    # ---------- eksekusi ----------
    def start(self):
        if self.app.busy:
            return
        api_id, api_hash = shopee_core.load_credentials()
        if not (api_id and api_hash):
            messagebox.showinfo(APP_NAME, "API ID & API HASH Telegram belum diisi.\nIsi dulu di menu Pengaturan.")
            self.app.show("settings")
            return

        accounts = self._parse_accounts()
        if not accounts:
            messagebox.showwarning(APP_NAME, "Daftar akun masih kosong.")
            return

        links = None
        if self.mode == "claim":
            links = [voucher_claim.DEFAULT_VOUCHERS[n] for n, v in self.voucher_vars.items() if v.get()]
            extra = self.link_entry.get().strip()
            if extra:
                links.append(extra)
            if not links:
                messagebox.showwarning(APP_NAME, "Pilih minimal satu voucher.")
                return
        else:
            if self.resume_var.get() and len(accounts) > 0:
                to_process, skipped = shopee_core.filter_unprocessed_usernames(accounts, self.mode)
                if skipped:
                    self._append(f"ℹ️ Resume aktif: {skipped} akun sudah pernah dicek dan dilewati.", "warn")
                accounts = to_process
                if not accounts:
                    self._append("✅ Semua akun sudah pernah dicek. Tidak ada antrean.", "ok")
                    return

        self.ok = self.warn = self.fail = 0
        self._refresh_stats()
        self.progress.set(0)
        self.prog_lbl.configure(text=f"0 / {len(accounts)}")
        delay = float(self.delay_var.get())
        method = self._auth_method()

        async def job():
            sessions = shopee_core.get_available_telegram_sessions()
            client = shopee_core.create_client(sessions[0] if sessions else None)
            try:
                await shopee_core.start_client(client)
                print("✅ Terhubung ke Telegram. Memulai antrean...")
                if self.mode == "misi":
                    await cek_misi_termux.run_misi_mode(client, accounts, auth_method=method, step_delay=delay)
                elif self.mode == "food":
                    await cek_misi_termux.run_food_mode(client, accounts, auth_method=method, step_delay=delay)
                elif self.mode == "both":
                    await cek_misi_termux.run_both_mode(client, accounts, auth_method=method, step_delay=delay)
                else:
                    await voucher_claim.run_voucher_claim_mode(
                        client=client, accounts=accounts, voucher_links=links, step_delay=delay)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        self.app.run_job(job, self)

    def stop(self):
        self.app.stop_job()

    def set_running(self, running: bool):
        self.start_btn.configure(state="disabled" if running else "normal",
                                 text="Berjalan..." if running else "Mulai")
        self.stop_btn.configure(state="normal" if running else "disabled",
                                fg_color=C_ERR if running else C_CARD_ALT,
                                hover_color="#e04848" if running else C_BORDER)
        self.state_lbl.configure(text="Sedang berjalan" if running else "Selesai",
                                 text_color=C_WARN if running else C_OK)


# =====================================================================
# Halaman: Daftar Akun Fresh
# =====================================================================
class RegisterPage(ctk.CTkFrame):
    PROG_RE = re.compile(r"^\[[█░]+\]\s*([\d.]+)%\s*\((\d+)/(\d+)\)")

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.mode = "register"
        self.cfg = FEATURES["register"]
        self.target = 0
        self.ok = self.fail = 0
        self.accounts = []

        label(self, self.cfg["title"], 24, "bold").pack(anchor="w")
        label(self, self.cfg["desc"], 12, color=C_MUTED, wraplength=820, justify="left").pack(
            anchor="w", pady=(2, 14))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=4, uniform="a", minsize=300)
        body.grid_columnconfigure(1, weight=6, uniform="a")
        body.grid_rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_right(body)

    # ---------- kiri: pengaturan + kontrol ----------
    def _build_left(self, body):
        left = card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))

        label(left, "1. Jumlah akun", 14, "bold").pack(anchor="w", padx=18, pady=(18, 0))
        label(left, "Berapa akun fresh yang ingin didapat.", 11, color=C_MUTED).pack(anchor="w", padx=18)
        self.target_entry = ctk.CTkEntry(left, height=38, width=120, fg_color=C_CARD_ALT, border_color=C_BORDER)
        self.target_entry.insert(0, "10")
        self.target_entry.pack(anchor="w", padx=18, pady=(8, 0))

        label(left, "2. Fingerprint", 14, "bold").pack(anchor="w", padx=18, pady=(18, 0))
        self.fp_hint = label(left, "", 11, color=C_MUTED, wraplength=300, justify="left")
        self.fp_hint.pack(anchor="w", padx=18)
        self.fp_seg = ctk.CTkSegmentedButton(
            left, values=["Custom", "Otomatis"], selected_color=C_ACCENT,
            selected_hover_color=C_ACCENT_HOVER, unselected_color=C_CARD_ALT,
            unselected_hover_color=C_BORDER, fg_color=C_CARD_ALT, command=lambda _v: self._fp_hint())
        self.fp_seg.set("Custom")
        self.fp_seg.pack(anchor="w", padx=18, pady=(8, 0))
        self._fp_hint()
        label(left, "OTP diurus otomatis oleh bot, Anda tidak perlu mengisi apa pun.", 11,
              color=C_MUTED, wraplength=300, justify="left").pack(anchor="w", padx=18, pady=(14, 0))

        label(left, "3. Jeda antar akun", 14, "bold").pack(anchor="w", padx=18, pady=(18, 0))
        drow = ctk.CTkFrame(left, fg_color="transparent")
        drow.pack(anchor="w", padx=18, pady=(6, 0))
        self.delay_var = tk.DoubleVar(value=self.cfg["delay"])
        slider = ctk.CTkSlider(drow, from_=1, to=20, number_of_steps=19, width=190, variable=self.delay_var,
                               button_color=C_ACCENT, button_hover_color=C_ACCENT_HOVER, progress_color=C_ACCENT,
                               command=lambda _v: self._delay_label())
        slider.set(self.cfg["delay"])
        slider.pack(side="left")
        self.delay_lbl = label(drow, "", 12)
        self.delay_lbl.pack(side="left", padx=10)
        self._delay_label()

        ctk.CTkFrame(left, fg_color="transparent").pack(fill="both", expand=True)

        self.start_btn = primary_button(left, "Mulai Daftar", self.start, width=200, height=44)
        self.start_btn.pack(fill="x", padx=18, pady=(0, 8))
        self.stop_btn = ctk.CTkButton(left, text="Berhenti", height=44, state="disabled", corner_radius=10,
                                      fg_color=C_CARD_ALT, hover_color=C_BORDER,
                                      font=ctk.CTkFont(size=13, weight="bold"), command=self.app.stop_job)
        self.stop_btn.pack(fill="x", padx=18, pady=(0, 18))

    # ---------- kanan: status + akun + log ----------
    def _build_right(self, body):
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        st = card(right)
        st.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top = ctk.CTkFrame(st, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 4))
        self.state_lbl = label(top, "Siap. Atur jumlah akun lalu klik Mulai Daftar.", 12, color=C_MUTED,
                               wraplength=420, justify="left")
        self.state_lbl.pack(side="left")
        self.progress = ctk.CTkProgressBar(st, height=10, progress_color=C_ACCENT, fg_color=C_CARD_ALT)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(4, 6))
        stats = ctk.CTkFrame(st, fg_color="transparent")
        stats.pack(fill="x", padx=16, pady=(0, 14))
        self.prog_lbl = label(stats, "0 / 0 akun", 12, color=C_MUTED)
        self.prog_lbl.pack(side="left")
        self.fail_lbl = label(stats, "Percobaan gagal 0", 12, color=C_ERR)
        self.fail_lbl.pack(side="right")
        self.ok_lbl = label(stats, "Berhasil 0", 12, color=C_OK)
        self.ok_lbl.pack(side="right", padx=14)

        ac = card(right)
        ac.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        ah = ctk.CTkFrame(ac, fg_color="transparent")
        ah.pack(fill="x", padx=16, pady=(12, 0))
        label(ah, "Akun berhasil", 14, "bold").pack(side="left")
        ghost_button(ah, "Salin semua", self.copy_all, width=90, height=26).pack(side="right")
        ghost_button(ah, "Buka folder", lambda: open_path(BASE_DIR), width=90, height=26).pack(side="right", padx=6)
        self.acc_box = ctk.CTkTextbox(ac, fg_color=C_CARD_ALT, border_width=0, corner_radius=10,
                                      font=ctk.CTkFont(family="Consolas", size=12), text_color=C_OK,
                                      wrap="none", state="disabled")
        self.acc_box.pack(fill="both", expand=True, padx=16, pady=(8, 4))
        label(ac, "Format: username|password|UID|nomor  •  tersimpan juga di akun_fresh.txt",
              11, color=C_MUTED).pack(anchor="w", padx=16, pady=(0, 12))

        lc = card(right)
        lc.grid(row=2, column=0, sticky="nsew")
        lh = ctk.CTkFrame(lc, fg_color="transparent")
        lh.pack(fill="x", padx=16, pady=(12, 0))
        label(lh, "Log", 14, "bold").pack(side="left")
        ghost_button(lh, "Bersihkan", self.clear_log, width=80, height=26).pack(side="right")
        self.log = ctk.CTkTextbox(lc, fg_color=C_BG, border_width=0, corner_radius=10,
                                  font=ctk.CTkFont(family="Consolas", size=12), text_color=C_TEXT,
                                  wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=16, pady=10)
        tb = self.log._textbox
        for name, col in (("ok", C_OK), ("warn", C_WARN), ("err", C_ERR), ("info", C_INFO), ("muted", C_MUTED)):
            tb.tag_configure(name, foreground=col)

    # ---------- util ----------
    def _delay_label(self):
        self.delay_lbl.configure(text=f"{self.delay_var.get():.0f} detik")

    def _fp_hint(self):
        self.fp_hint.configure(text={
            "Custom": "Tombol 'Fingerprint Custom' di bot diklik otomatis (fingerprint dari database bot).",
            "Otomatis": "Tombol 'Fingerprint Otomatis' di bot diklik otomatis.",
        }[self.fp_seg.get()])

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def copy_all(self):
        if not self.accounts:
            self.state_lbl.configure(text="Belum ada akun untuk disalin.", text_color=C_WARN)
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(f"{a.get('username')}|{a.get('password')}" for a in self.accounts))
        self.state_lbl.configure(text=f"{len(self.accounts)} akun disalin ke clipboard.", text_color=C_OK)

    def _append(self, text, tag=None):
        for k, v in TaskPage.EMOJI_MAP.items():
            text = text.replace(k, v)
        text = text.replace("\ufe0f", "")
        self.log.configure(state="normal")
        self.log._textbox.insert("end", text + "\n", tag if tag else ())
        self.log.configure(state="disabled")
        self.log.see("end")

    def _refresh_stats(self):
        self.ok_lbl.configure(text=f"Berhasil {self.ok}")
        self.fail_lbl.configure(text=f"Percobaan gagal {self.fail}")
        self.prog_lbl.configure(text=f"{self.ok} / {self.target} akun")
        self.progress.set(min(1.0, self.ok / self.target) if self.target else 0)

    # ---------- log & event ----------
    def handle_line(self, line: str):
        s = line.strip()
        if not s or self.PROG_RE.match(s):
            return
        tag = None
        if "✅" in s:
            tag = "ok"
        elif "⚠" in s or "↻" in s:
            tag = "warn"
        elif "❌" in s:
            tag = "err"
        elif "├─" in s:
            tag = "muted"
        elif re.fullmatch(r"[=\-─━]{5,}", s):
            tag = "muted"
        self._append(line, tag)

    def handle_event(self, e: dict):
        t = e.get("type")
        if t == "attempt":
            self.state_lbl.configure(text=f"Mendaftarkan akun {self.ok + 1} dari {self.target} ...",
                                     text_color=C_TEXT)
        elif t == "step":
            self.state_lbl.configure(text=e.get("text", ""), text_color=C_MUTED)
        elif t == "attempt_fail":
            self.fail += 1
            self.state_lbl.configure(text=f"Gagal: {e.get('reason')}. Mengulang otomatis ...", text_color=C_WARN)
            self._refresh_stats()
        elif t == "success":
            r = e.get("result", {})
            self.ok = e.get("success", self.ok)
            self.accounts.append(r)
            self.acc_box.configure(state="normal")
            self.acc_box.insert("end", f"{r.get('username') or '-'}|{r.get('password') or '-'}|"
                                       f"{r.get('user_id') or '-'}|{r.get('phone') or '-'}\n")
            self.acc_box.configure(state="disabled")
            self.acc_box.see("end")
            self.state_lbl.configure(text=f"Berhasil: {r.get('username')}", text_color=C_OK)
            self._refresh_stats()

    # ---------- eksekusi ----------
    def start(self):
        if self.app.busy:
            return
        api_id, api_hash = shopee_core.load_credentials()
        if not (api_id and api_hash):
            messagebox.showinfo(APP_NAME, "API ID & API HASH Telegram belum diisi.\nIsi dulu di menu Pengaturan.")
            self.app.show("settings")
            return
        raw = self.target_entry.get().strip()
        if not raw.isdigit() or int(raw) < 1:
            messagebox.showwarning(APP_NAME, "Isi jumlah akun dengan angka minimal 1.")
            return
        target = int(raw)
        use_custom = self.fp_seg.get() == "Custom"
        delay = float(self.delay_var.get())

        self.target, self.ok, self.fail, self.accounts = target, 0, 0, []
        self.acc_box.configure(state="normal")
        self.acc_box.delete("1.0", "end")
        self.acc_box.configure(state="disabled")
        self._refresh_stats()
        self.state_lbl.configure(text="Menghubungkan ke Telegram ...", text_color=C_INFO)

        async def job():
            sessions = shopee_core.get_available_telegram_sessions()
            client = shopee_core.create_client(sessions[0] if sessions else None)
            try:
                await shopee_core.start_client(client)
                print("✅ Terhubung ke Telegram. Mulai mendaftarkan akun...")
                await daf.run_register_fresh_batch(
                    client=client, total_target=target, use_custom_fp=use_custom, step_delay=delay,
                    on_event=lambda e: LOG_QUEUE.put(("event", e)))
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        self.app.run_job(job, self)

    def set_running(self, running: bool):
        self.start_btn.configure(state="disabled" if running else "normal",
                                 text="Berjalan..." if running else "Mulai Daftar")
        self.stop_btn.configure(state="normal" if running else "disabled",
                                fg_color=C_ERR if running else C_CARD_ALT,
                                hover_color="#e04848" if running else C_BORDER)
        if running:
            self.state_lbl.configure(text="Sedang berjalan. Klik Berhenti kapan saja.", text_color=C_WARN)
        else:
            self.state_lbl.configure(
                text=f"Selesai. {self.ok} dari {self.target} akun berhasil. Hasil tersimpan di akun_fresh.txt.",
                text_color=C_OK if self.ok >= self.target else C_WARN)


# =====================================================================
# Halaman: Pengaturan
# =====================================================================
class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        label(self, "Pengaturan", 24, "bold").pack(anchor="w")
        label(self, "Kredensial Telegram, sesi login, dan folder hasil.", 12, color=C_MUTED).pack(
            anchor="w", pady=(2, 14))

        # API
        c = card(self)
        c.pack(fill="x", pady=(0, 12))
        label(c, "API Telegram", 15, "bold").pack(anchor="w", padx=18, pady=(16, 2))
        label(c, "Ambil dari my.telegram.org > API development tools. Cukup diisi sekali.",
              12, color=C_MUTED).pack(anchor="w", padx=18)
        form = ctk.CTkFrame(c, fg_color="transparent")
        form.pack(fill="x", padx=18, pady=12)
        form.grid_columnconfigure(1, weight=1)
        label(form, "API ID", 12, color=C_MUTED).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 14))
        self.api_id = ctk.CTkEntry(form, height=36, fg_color=C_CARD_ALT, border_color=C_BORDER,
                                   placeholder_text="contoh: 28374651")
        self.api_id.grid(row=0, column=1, sticky="ew", pady=6)
        label(form, "API HASH", 12, color=C_MUTED).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 14))
        self.api_hash = ctk.CTkEntry(form, height=36, fg_color=C_CARD_ALT, border_color=C_BORDER,
                                     show="•", placeholder_text="32 karakter huruf & angka")
        self.api_hash.grid(row=1, column=1, sticky="ew", pady=6)
        self.show_hash = ctk.CTkCheckBox(form, text="Tampilkan API HASH", text_color=C_MUTED,
                                         fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                                         command=self._toggle_hash)
        self.show_hash.grid(row=2, column=1, sticky="w", pady=(2, 0))
        brow = ctk.CTkFrame(c, fg_color="transparent")
        brow.pack(fill="x", padx=18, pady=(0, 16))
        primary_button(brow, "Simpan", self.save_api, width=110).pack(side="left")
        self.api_msg = label(brow, "", 12, color=C_MUTED)
        self.api_msg.pack(side="left", padx=12)

        # Sesi
        s = card(self)
        s.pack(fill="x", pady=(0, 12))
        label(s, "Sesi Login Telegram", 15, "bold").pack(anchor="w", padx=18, pady=(16, 2))
        self.session_lbl = label(s, "", 12, color=C_MUTED)
        self.session_lbl.pack(anchor="w", padx=18)
        srow = ctk.CTkFrame(s, fg_color="transparent")
        srow.pack(fill="x", padx=18, pady=(12, 16))
        ctk.CTkButton(srow, text="Reset Login & API", width=150, height=34, fg_color=C_CARD_ALT,
                      hover_color=C_ERR, corner_radius=10, command=self.reset_all).pack(side="left")
        label(srow, "Hapus API tersimpan dan sesi login. Perlu login ulang setelahnya.",
              11, color=C_MUTED).pack(side="left", padx=12)

        # Folder / hasil
        f = card(self)
        f.pack(fill="both", expand=True)
        head = ctk.CTkFrame(f, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 6))
        label(head, "File Hasil", 15, "bold").pack(side="left")
        ghost_button(head, "Buka Folder", lambda: open_path(BASE_DIR), width=110).pack(side="right")
        self.results_box = ctk.CTkScrollableFrame(f, fg_color="transparent", height=140)
        self.results_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.refresh()

    def _toggle_hash(self):
        self.api_hash.configure(show="" if self.show_hash.get() else "•")

    def refresh(self):
        api_id, api_hash = shopee_core.load_credentials()
        self.api_id.delete(0, "end")
        self.api_hash.delete(0, "end")
        if api_id and api_hash:
            self.api_id.insert(0, str(api_id))
            self.api_hash.insert(0, api_hash)
            self.api_msg.configure(text="Tersimpan", text_color=C_OK)
        else:
            self.api_msg.configure(text="Belum diisi", text_color=C_WARN)
        sessions = sorted(p.name for p in Path(".").glob("*.session"))
        self.session_lbl.configure(
            text=("Sesi tersimpan: " + ", ".join(sessions)) if sessions else "Belum ada sesi. Login otomatis saat pertama kali menjalankan fitur.")

        for w in self.results_box.winfo_children():
            w.destroy()
        found = False
        for fname, desc in RESULT_FILES:
            p = Path(fname)
            if not p.is_file():
                continue
            found = True
            row = ctk.CTkFrame(self.results_box, fg_color=C_CARD_ALT, corner_radius=8)
            row.pack(fill="x", pady=3)
            label(row, desc, 12).pack(side="left", padx=12, pady=8)
            label(row, fname, 11, color=C_MUTED).pack(side="left")
            ghost_button(row, "Buka", lambda pp=p: open_path(pp.resolve()), width=60, height=26).pack(
                side="right", padx=8, pady=6)
        if not found:
            label(self.results_box, "Belum ada file hasil.", 12, color=C_MUTED).pack(anchor="w", padx=6, pady=8)

    def save_api(self):
        raw_id = self.api_id.get().strip()
        api_hash = self.api_hash.get().strip()
        if not raw_id.isdigit() or int(raw_id) <= 0:
            self.api_msg.configure(text="API ID harus berupa angka.", text_color=C_ERR)
            return
        if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
            self.api_msg.configure(text="API HASH harus 32 karakter huruf/angka (hex).", text_color=C_ERR)
            return
        shopee_core.save_credentials(int(raw_id), api_hash)
        self.api_msg.configure(text="Tersimpan", text_color=C_OK)
        self.app.refresh_pages()

    def reset_all(self):
        if self.app.busy:
            messagebox.showinfo(APP_NAME, "Hentikan proses yang sedang berjalan terlebih dahulu.")
            return
        if messagebox.askyesno(APP_NAME, "Hapus API tersimpan dan semua sesi login Telegram?"):
            shopee_core.reset_credentials()
            for p in Path(".").glob("*.session"):
                try:
                    p.unlink()
                except OSError:
                    pass
            self.app.refresh_pages()


# =====================================================================
# Aplikasi utama
# =====================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1180x740")
        self.minsize(1000, 660)
        self.configure(fg_color=C_BG)

        self.busy = False
        self.loop = None
        self.task = None
        self.active_page = None
        self.running_page = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=26, pady=22)

        self.pages = {"home": HomePage(self.content, self)}
        for k in FEATURES:
            self.pages[k] = RegisterPage(self.content, self) if k == "register" else TaskPage(self.content, self, k)
        self.pages["settings"] = SettingsPage(self.content, self)

        self.show("home")
        self.after(60, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        builtins.input = self._thread_input
        getpass.getpass = lambda prompt="": self._thread_input(prompt, secret=True)

    # ---------- sidebar ----------
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=0, width=230)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(20, weight=1)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 22))
        label(brand, APP_NAME, 20, "bold").pack(anchor="w")
        label(brand, "Sembah aku, hamba otomasimu", 11, color=C_MUTED).pack(anchor="w")

        self.nav = {}
        items = [("home", "Beranda")] + [(k, f["nav"]) for k, f in FEATURES.items()] + [("settings", "Pengaturan")]
        r = 1
        for key, text in items:
            if key == "settings":
                r = 21
            b = ctk.CTkButton(sb, text=text, anchor="w", height=40, corner_radius=10,
                              fg_color="transparent", hover_color=C_CARD_ALT, text_color=C_MUTED,
                              font=ctk.CTkFont(size=13, weight="bold"),
                              command=lambda k=key: self.show(k))
            b.grid(row=r, column=0, sticky="ew", padx=12, pady=2)
            self.nav[key] = b
            r += 1
        self.run_dot = label(sb, "", 11, color=C_WARN)
        self.run_dot.grid(row=22, column=0, sticky="w", padx=20, pady=(8, 16))

    def show(self, key: str):
        if self.active_page is not None:
            self.active_page.pack_forget()
        page = self.pages[key]
        if hasattr(page, "refresh"):
            page.refresh()
        page.pack(fill="both", expand=True)
        self.active_page = page
        for k, b in self.nav.items():
            on = k == key
            b.configure(fg_color=C_CARD_ALT if on else "transparent",
                        text_color=C_TEXT if on else C_MUTED)

    def refresh_pages(self):
        for p in self.pages.values():
            if hasattr(p, "refresh"):
                p.refresh()

    # ---------- job runner ----------
    def run_job(self, coro_factory, page):
        if self.busy:
            return
        self.busy = True
        self.running_page = page
        page.set_running(True)
        self.run_dot.configure(text=f"Berjalan: {page.cfg['nav']}")

        def target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop
            self.task = loop.create_task(coro_factory())
            try:
                loop.run_until_complete(self.task)
            except asyncio.CancelledError:
                print("⏹ Proses dihentikan oleh pengguna.")
            except (KeyboardInterrupt, EOFError):
                print("⏹ Dibatalkan.")
            except Exception as exc:  # noqa: BLE001
                print(f"❌ Terjadi kesalahan: {exc}")
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
                self.loop = None
                self.task = None
                LOG_QUEUE.put(("done", None))

        threading.Thread(target=target, daemon=True).start()

    def stop_job(self):
        loop, task = self.loop, self.task
        if loop and task and not task.done():
            loop.call_soon_threadsafe(task.cancel)
            self.run_dot.configure(text="Menghentikan...")
            # tutup kotak input yang masih terbuka agar proses tidak menggantung
            for w in self.winfo_children():
                if isinstance(w, PromptDialog):
                    w._finish(None)

    # ---------- jembatan input() dari thread kerja ----------
    def _thread_input(self, prompt="", secret=False):
        if threading.current_thread() is threading.main_thread():
            return ""
        done = threading.Event()
        box = {}

        def on_done(value):
            box["v"] = value
            done.set()

        LOG_QUEUE.put(("ask", (str(prompt), secret, on_done)))
        done.wait()
        if box.get("v") is None:
            raise EOFError("Input dibatalkan")
        return box["v"].strip()

    # ---------- pompa antrean log -> UI ----------
    def _pump(self):
        try:
            for _ in range(200):
                kind, payload = LOG_QUEUE.get_nowait()
                page = self.running_page
                if kind == "log":
                    if page:
                        page.handle_line(payload)
                elif kind == "event":
                    if page and hasattr(page, "handle_event"):
                        page.handle_event(payload)
                elif kind == "ask":
                    prompt, secret, on_done = payload
                    PromptDialog(self, prompt, secret, on_done)
                elif kind == "done":
                    self.busy = False
                    self.run_dot.configure(text="")
                    if page:
                        page.set_running(False)
                    self.refresh_pages()
        except queue.Empty:
            pass
        self.after(60, self._pump)

    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno(APP_NAME, "Proses masih berjalan. Tetap keluar?"):
                return
            self.stop_job()
        self.destroy()
        os._exit(0)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
