#!/usr/bin/env python3
"""Aplikasi desktop (GUI) Daftar Akun Fresh ShopeeFood.

Jalankan:  python gui_daftar_akun.py
Build EXE: build_exe.bat  (menghasilkan dist\\DaftarAkunFresh.exe)
"""

import asyncio
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

if getattr(sys, "frozen", False):
    # Simpan sesi / hasil di folder yang sama dengan file .exe
    os.chdir(os.path.dirname(sys.executable))

import daftar_akun_fresh as daf
import shopee_core

# ---------------------------------------------------------------- tema
BG = "#0b1020"
CARD = "#151c33"
CARD2 = "#1c2542"
BORDER = "#26304f"
TEXT = "#e8ecf8"
MUTED = "#8b95b5"
ACCENT = "#6366f1"
ACCENT_H = "#7c7ff5"
GREEN = "#22c55e"
GREEN_H = "#34d27a"
RED = "#ef4444"
RED_H = "#f56565"
YELLOW = "#fbbf24"

FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_H1 = ("Segoe UI", 20, "bold")
FONT_BIG = ("Segoe UI", 24, "bold")
FONT_SM = ("Segoe UI", 9)
MONO = ("Consolas", 9)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class QueueWriter:
    """Mengalihkan print() dari modul lain ke jendela log."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(("log", ANSI_RE.sub("", str(s))))
        return len(s or "")

    def flush(self):
        pass

    def isatty(self):
        return False


class TextDialog(tk.Toplevel):
    """Dialog input bergaya modern (pengganti simpledialog)."""

    def __init__(self, parent, title, prompt, secret=False, hint=""):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.configure(bg=CARD, padx=24, pady=20)
        self.resizable(False, False)
        self.transient(parent)
        tk.Label(self, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(self, text=prompt, bg=CARD, fg=MUTED, font=FONT, justify="left",
                 wraplength=360).pack(anchor="w", pady=(4, 10))
        self.var = tk.StringVar()
        ent = tk.Entry(self, textvariable=self.var, show="•" if secret else "", width=40,
                       bg=CARD2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Segoe UI", 11),
                       highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        ent.pack(fill="x", ipady=6)
        if hint:
            tk.Label(self, text=hint, bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", pady=(6, 0))
        row = tk.Frame(self, bg=CARD)
        row.pack(fill="x", pady=(16, 0))
        make_button(row, "Batal", self._cancel, CARD2, BORDER).pack(side="right", padx=(8, 0))
        make_button(row, "OK", self._ok, ACCENT, ACCENT_H).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        ent.focus_set()
        self.wait_window(self)

    def _ok(self):
        self.result = self.var.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def make_button(parent, text, command, bg, hover, fg=TEXT, font=FONT_B, padx=18, pady=8):
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=hover,
                  activeforeground=fg, relief="flat", bd=0, cursor="hand2", font=font,
                  padx=padx, pady=pady, disabledforeground="#5b6485")
    b._bg, b._hover = bg, hover

    def enter(_):
        if str(b["state"]) == "normal":
            b.configure(bg=hover)

    def leave(_):
        b.configure(bg=b._bg if str(b["state"]) == "normal" else CARD2)

    b.bind("<Enter>", enter)
    b.bind("<Leave>", leave)
    return b


def open_path(path: Path):
    try:
        path = path.resolve()
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror("Gagal membuka", str(exc))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.running = False
        self.loop = None
        self.task = None
        self.thread = None
        self.dialog = None
        self.accounts = []
        self.ok_count = 0
        self.fail_count = 0
        self.attempts = 0
        self.target = 0
        self.started_at = 0.0

        root.title("Daftar Akun Fresh ShopeeFood")
        root.configure(bg=BG)
        root.geometry("1040x700")
        root.minsize(920, 620)
        self._style()
        self._build()
        sys.stdout = QueueWriter(self.q)
        sys.stderr = QueueWriter(self.q)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, self.poll)
        self.root.after(1000, self.tick)
        self.set_status("Siap. Atur jumlah akun di kiri, lalu klik MULAI.", MUTED)
        self.log("Selamat datang! Klik MULAI untuk mendaftarkan akun. Tombol STOP bisa dipakai kapan saja.\n", "muted")

    # ------------------------------------------------------------ UI
    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TProgressbar", troughcolor=CARD2, background=ACCENT, bordercolor=CARD2,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(18, 8), borderwidth=0,
                    font=FONT_B)
        s.map("TNotebook.Tab", background=[("selected", CARD2)], foreground=[("selected", TEXT)])
        s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=28,
                    borderwidth=0, font=FONT)
        s.configure("Treeview.Heading", background=CARD2, foreground=MUTED, relief="flat", font=FONT_B)
        s.map("Treeview", background=[("selected", ACCENT)])
        s.configure("TSpinbox", fieldbackground=CARD2, background=CARD2, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER, lightcolor=CARD2, darkcolor=CARD2)
        s.configure("TRadiobutton", background=CARD, foreground=TEXT, font=FONT)
        s.map("TRadiobutton", background=[("active", CARD)])
        s.configure("Vertical.TScrollbar", background=CARD2, troughcolor=CARD, bordercolor=CARD,
                    arrowcolor=MUTED)

    def card(self, parent, **kw):
        return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER, **kw)

    def _build(self):
        # Header
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=24, pady=(18, 10))
        tk.Label(head, text="📝  Daftar Akun Fresh", bg=BG, fg=TEXT, font=FONT_H1).pack(anchor="w")
        tk.Label(head, text=f"ShopeeFood  •  otomatis via {daf.DEFAULT_BOT}", bg=BG, fg=MUTED,
                 font=FONT).pack(anchor="w")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(4, 8))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ---------- Kiri: pengaturan
        left = self.card(body, width=300)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 16))
        left.grid_propagate(False)
        pad = tk.Frame(left, bg=CARD)
        pad.pack(fill="both", expand=True, padx=18, pady=16)

        self._section(pad, "1  Jumlah akun")
        self.var_target = tk.StringVar(value="10")
        self.sp_target = ttk.Spinbox(pad, from_=1, to=999, textvariable=self.var_target, width=8,
                                     font=("Segoe UI", 12))
        self.sp_target.pack(anchor="w", pady=(4, 2), ipady=3)
        tk.Label(pad, text="Berapa akun yang ingin didapat.", bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w")

        self._section(pad, "2  Sumber OTP")
        self.var_otp = tk.StringVar(value="bot")
        self.otp_radios = []
        for val, title, desc in (
            ("bot", "Dari bot Telegram", "Paling umum, otomatis."),
            ("sms", "Dari SMS forwarder", "Baca file otp_inbox.txt"),
            ("input", "Ketik manual", "Muncul kotak input saat OTP perlu."),
        ):
            rb = ttk.Radiobutton(pad, text=title, value=val, variable=self.var_otp)
            rb.pack(anchor="w", pady=(4, 0))
            tk.Label(pad, text=desc, bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=(22, 0))
            self.otp_radios.append(rb)

        self._section(pad, "3  Jeda antar akun (detik)")
        self.var_delay = tk.StringVar(value="6")
        self.sp_delay = ttk.Spinbox(pad, from_=0, to=120, textvariable=self.var_delay, width=8,
                                    font=("Segoe UI", 12))
        self.sp_delay.pack(anchor="w", pady=(4, 0), ipady=3)

        tk.Frame(pad, bg=CARD).pack(fill="both", expand=True)

        self.btn_start = make_button(pad, "▶   MULAI", self.start, GREEN, GREEN_H, fg="#06210f",
                                     font=("Segoe UI", 12, "bold"), pady=12)
        self.btn_start.pack(fill="x")
        self.btn_stop = make_button(pad, "■   STOP", self.stop, RED, RED_H, font=("Segoe UI", 12, "bold"),
                                    pady=12)
        self.btn_stop.pack(fill="x", pady=(10, 0))
        self.btn_stop.configure(state="disabled", bg=CARD2)

        # ---------- Kanan
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        stats = tk.Frame(right, bg=BG)
        stats.grid(row=0, column=0, sticky="ew")
        for i in range(3):
            stats.columnconfigure(i, weight=1)
        self.lbl_ok = self._stat(stats, 0, "Berhasil", GREEN)
        self.lbl_fail = self._stat(stats, 1, "Percobaan gagal", RED)
        self.lbl_time = self._stat(stats, 2, "Waktu berjalan", ACCENT_H, text="00:00")

        prog = self.card(right)
        prog.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        pin = tk.Frame(prog, bg=CARD)
        pin.pack(fill="x", padx=16, pady=12)
        top = tk.Frame(pin, bg=CARD)
        top.pack(fill="x")
        self.lbl_prog = tk.Label(top, text="0 / 0 akun", bg=CARD, fg=TEXT, font=FONT_B)
        self.lbl_prog.pack(side="left")
        self.lbl_pct = tk.Label(top, text="0%", bg=CARD, fg=MUTED, font=FONT)
        self.lbl_pct.pack(side="right")
        self.bar = ttk.Progressbar(pin, mode="determinate", maximum=100)
        self.bar.pack(fill="x", pady=(8, 8))
        self.lbl_status = tk.Label(pin, text="", bg=CARD, fg=MUTED, font=FONT, anchor="w", justify="left")
        self.lbl_status.pack(fill="x")

        # tombol utilitas
        tools = tk.Frame(right, bg=BG)
        tools.grid(row=2, column=0, sticky="ew", pady=(12, 8))
        make_button(tools, "📋 Salin semua akun", self.copy_all, CARD2, BORDER, font=FONT, pady=6).pack(side="left")
        make_button(tools, "📂 Buka folder hasil", lambda: open_path(Path(".")), CARD2, BORDER, font=FONT,
                    pady=6).pack(side="left", padx=8)
        make_button(tools, "🔑 Edit fingerprint", self.edit_fp, CARD2, BORDER, font=FONT, pady=6).pack(side="left")
        make_button(tools, "🧹 Bersihkan log", self.clear_log, CARD2, BORDER, font=FONT, pady=6).pack(side="right")

        nb = ttk.Notebook(right)
        nb.grid(row=3, column=0, sticky="nsew")
        self.nb = nb

        tab_acc = tk.Frame(nb, bg=CARD)
        nb.add(tab_acc, text="  Akun Berhasil  ")
        cols = ("no", "username", "password", "uid", "phone")
        self.tree = ttk.Treeview(tab_acc, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("no", "#", 40), ("username", "Username", 190), ("password", "Password", 150),
                        ("uid", "User ID", 130), ("phone", "Nomor", 140)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w", stretch=(c != "no"))
        sb = ttk.Scrollbar(tab_acc, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.copy_selected)
        self.empty_lbl = tk.Label(tab_acc, text="Belum ada akun.\nAkun yang berhasil muncul di sini.\n"
                                  "Klik 2x pada baris untuk menyalin.", bg=CARD, fg=MUTED, font=FONT)
        self.empty_lbl.place(relx=0.5, rely=0.5, anchor="center")

        tab_log = tk.Frame(nb, bg=CARD)
        nb.add(tab_log, text="  Log Aktivitas  ")
        self.txt = tk.Text(tab_log, bg=CARD, fg=TEXT, font=MONO, relief="flat", wrap="word",
                           padx=12, pady=10, state="disabled", insertbackground=TEXT, borderwidth=0)
        lsb = ttk.Scrollbar(tab_log, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=lsb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.txt.tag_configure("ok", foreground=GREEN)
        self.txt.tag_configure("warn", foreground=YELLOW)
        self.txt.tag_configure("err", foreground=RED)
        self.txt.tag_configure("muted", foreground=MUTED)
        self.txt.tag_configure("head", foreground=ACCENT_H)

        # footer
        foot = tk.Label(self.root, bg=BG, fg=MUTED, font=FONT_SM, anchor="w",
                        text=f"Hasil tersimpan di: {daf.DEFAULT_OUTPUT_FILE} • {daf.DEFAULT_COOKIE_FILE}   "
                             f"|   Gagal dicatat di: {daf.DEFAULT_FAILED_FILE}")
        foot.pack(fill="x", padx=24, pady=(0, 10))

    def _section(self, parent, text):
        tk.Label(parent, text=text, bg=CARD, fg=TEXT, font=FONT_B).pack(anchor="w", pady=(14, 0))

    def _stat(self, parent, col, title, color, text="0"):
        c = self.card(parent)
        c.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 12, 0))
        tk.Label(c, text=title, bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=16, pady=(10, 0))
        lbl = tk.Label(c, text=text, bg=CARD, fg=color, font=FONT_BIG)
        lbl.pack(anchor="w", padx=16, pady=(0, 8))
        return lbl

    # ---------------------------------------------------------- helpers
    def log(self, text, tag=None):
        self.txt.configure(state="normal")
        self.txt.insert("end", text, tag or ())
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def set_status(self, text, color=TEXT):
        self.lbl_status.configure(text=text, fg=color)

    def refresh_stats(self):
        self.lbl_ok.configure(text=str(self.ok_count))
        self.lbl_fail.configure(text=str(self.fail_count))
        tgt = max(self.target, 1)
        pct = min(100, int(self.ok_count * 100 / tgt)) if self.target else 0
        self.bar["value"] = pct
        self.lbl_prog.configure(text=f"{self.ok_count} / {self.target} akun")
        self.lbl_pct.configure(text=f"{pct}%")

    def tick(self):
        if self.running:
            sec = int(time.time() - self.started_at)
            self.lbl_time.configure(text=f"{sec // 60:02d}:{sec % 60:02d}")
        self.root.after(1000, self.tick)

    def edit_fp(self):
        daf.load_fingerprints()  # pastikan file ada
        open_path(daf.DEFAULT_FINGERPRINT_FILE)

    def copy_text(self, text, info):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status(info, GREEN)

    def copy_selected(self, _e=None):
        sel = self.tree.selection()
        if sel:
            v = self.tree.item(sel[0], "values")
            self.copy_text(f"{v[1]}|{v[2]}", f"Disalin: {v[1]}|{v[2]}")

    def copy_all(self):
        if not self.accounts:
            self.set_status("Belum ada akun untuk disalin.", YELLOW)
            return
        lines = [f"{a.get('username')}|{a.get('password')}" for a in self.accounts]
        self.copy_text("\n".join(lines), f"{len(lines)} akun disalin ke clipboard.")

    # ------------------------------------------------------ dialog (thread-safe)
    def ask(self, title, prompt, secret=False, hint=""):
        """Dipanggil dari thread worker; menampilkan dialog di thread GUI."""
        out: queue.Queue = queue.Queue()

        def show():
            d = TextDialog(self.root, title, prompt, secret, hint)
            out.put(d.result)

        self.q.put(("call", show))
        return out.get()

    # ------------------------------------------------------------ kontrol
    def set_running(self, running: bool):
        self.running = running
        st = "disabled" if running else "normal"
        for w in (self.sp_target, self.sp_delay, *self.otp_radios):
            w.configure(state=st)
        if running:
            self.btn_start.configure(state="disabled", bg=CARD2, text="⏳  Berjalan ...")
            self.btn_stop.configure(state="normal", bg=RED, text="■   STOP")
        else:
            self.btn_start.configure(state="normal", bg=GREEN, text="▶   MULAI")
            self.btn_stop.configure(state="disabled", bg=CARD2, text="■   STOP")

    def start(self):
        if self.running:
            return
        try:
            target = int(self.var_target.get())
            if target < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Jumlah akun", "Isi jumlah akun dengan angka minimal 1.")
            return
        try:
            delay = max(0.0, float(self.var_delay.get()))
        except ValueError:
            messagebox.showwarning("Jeda", "Isi jeda dengan angka (detik).")
            return
        cfg = {"target": target, "delay": delay, "otp": self.var_otp.get()}

        self.target = target
        self.ok_count = self.fail_count = self.attempts = 0
        self.accounts = []
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.empty_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self.refresh_stats()
        self.started_at = time.time()
        self.set_running(True)
        self.set_status("Menghubungkan ke Telegram ...", ACCENT_H)
        self.log(f"\n=== Mulai: target {target} akun, OTP: {cfg['otp']}, jeda {delay:g}s ===\n", "head")
        self.thread = threading.Thread(target=self._worker, args=(cfg,), daemon=True)
        self.thread.start()

    def stop(self):
        if not self.running:
            return
        self.btn_stop.configure(state="disabled", bg=CARD2, text="Menghentikan ...")
        self.set_status("Menghentikan proses ... mohon tunggu sebentar.", YELLOW)
        loop, task = self.loop, self.task
        if loop and task:
            loop.call_soon_threadsafe(task.cancel)
        # tutup dialog yang sedang terbuka agar worker tidak menggantung
        for w in self.root.winfo_children():
            if isinstance(w, TextDialog):
                w._cancel()

    def on_close(self):
        if self.running:
            if not messagebox.askyesno("Keluar", "Proses masih berjalan. Hentikan dan keluar?"):
                return
            self.stop()
            if self.thread:
                self.thread.join(timeout=4)
        self.root.destroy()

    # ------------------------------------------------------------ worker
    def _worker(self, cfg):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.task = self.loop.create_task(self._run(cfg))
        try:
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            self.q.put(("log", "Dihentikan oleh pengguna.\n"))
        except Exception as exc:
            self.q.put(("log", f"❌ Error: {exc}\n"))
            self.q.put(("event", {"type": "error", "text": str(exc)}))
        finally:
            try:
                self.loop.close()
            except Exception:
                pass
            self.q.put(("event", {"type": "finished"}))

    async def _login(self):
        api_id, api_hash = shopee_core.load_credentials()
        if not (api_id and api_hash):
            while True:
                v = await asyncio.get_running_loop().run_in_executor(
                    None, self.ask, "API Telegram (sekali saja)",
                    "Masukkan API_ID (angka) dari https://my.telegram.org", False, "")
                if v is None:
                    raise RuntimeError("API_ID dibatalkan.")
                if v.isdigit() and int(v) > 0:
                    api_id = int(v)
                    break
            while True:
                h = await asyncio.get_running_loop().run_in_executor(
                    None, self.ask, "API Telegram (sekali saja)",
                    "Masukkan API_HASH (32 karakter huruf/angka).", False, "")
                if h is None:
                    raise RuntimeError("API_HASH dibatalkan.")
                if re.fullmatch(r"[0-9a-fA-F]{32}", h):
                    api_hash = h
                    break
            shopee_core.save_credentials(api_id, api_hash)

        client = shopee_core.create_client()
        await client.connect()
        if not await client.is_user_authorized():
            self.q.put(("status", ("Login Telegram diperlukan - isi kotak yang muncul.", YELLOW)))

            def need(title, prompt, secret=False, hint="", allow_empty=False):
                while True:
                    v = self.ask(title, prompt, secret, hint)
                    if v is None:
                        raise RuntimeError("Login Telegram dibatalkan.")
                    if v or allow_empty:
                        return v

            await client.start(
                phone=lambda: need("Login Telegram", "Nomor telepon Telegram Anda.",
                                   hint="Format internasional, contoh: +6281234567890"),
                code_callback=lambda: need("Login Telegram", "Kode login yang dikirim Telegram ke aplikasi Anda."),
                password=lambda: need("Login Telegram", "Password 2FA (kosongkan jika tidak ada).", True,
                                      allow_empty=True),
            )
        return client

    async def _run(self, cfg):
        client = None
        try:
            client = await self._login()
            self.q.put(("status", ("Terhubung. Memproses pendaftaran ...", ACCENT_H)))
            loop = asyncio.get_running_loop()

            async def manual(_phone):
                label = ("Masukkan kode OTP yang Anda terima." if cfg["otp"] == "input"
                         else "OTP otomatis tidak masuk. Ketik manual, atau Batal untuk lewati.")
                return await loop.run_in_executor(None, self.ask, "OTP dibutuhkan", label, False, "")

            await daf.run_register_fresh_batch(
                client=client,
                total_target=cfg["target"],
                otp_source=cfg["otp"],
                step_delay=cfg["delay"],
                manual_otp_callback=manual,
                on_event=lambda e: self.q.put(("event", e)),
            )
        finally:
            if client is not None:
                try:
                    await asyncio.shield(client.disconnect())
                except BaseException:
                    pass

    # ------------------------------------------------------------ event pump
    def poll(self):
        try:
            for _ in range(200):
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._handle_log(data)
                elif kind == "event":
                    self._handle_event(data)
                elif kind == "status":
                    self.set_status(*data)
                elif kind == "call":
                    data()
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def _handle_log(self, text):
        for line in text.splitlines(True):
            if not line.strip():
                continue
            tag = None
            if "✅" in line:
                tag = "ok"
            elif "⚠️" in line or "↻" in line:
                tag = "warn"
            elif "❌" in line:
                tag = "err"
            elif "===" in line or "RINGKASAN" in line:
                tag = "head"
            elif "├─" in line:
                tag = "muted"
            self.log(line if line.endswith("\n") else line + "\n", tag)

    def _handle_event(self, e):
        t = e.get("type")
        if t == "attempt":
            self.attempts = e.get("index", self.attempts)
            self.set_status(f"Mendaftarkan akun {self.ok_count + 1} dari {self.target} ...", TEXT)
        elif t == "step":
            self.set_status(e.get("text", ""), MUTED)
        elif t == "attempt_fail":
            self.fail_count += 1
            self.set_status(f"Gagal: {e.get('reason')} - mengulang otomatis ...", YELLOW)
            self.refresh_stats()
        elif t == "success":
            r = e.get("result", {})
            self.ok_count = e.get("success", self.ok_count)
            self.accounts.append(r)
            self.empty_lbl.place_forget()
            self.tree.insert("", "end", values=(len(self.accounts), r.get("username") or "-",
                                                r.get("password") or "-", r.get("user_id") or "-",
                                                r.get("phone") or "-"))
            self.tree.yview_moveto(1)
            self.set_status(f"Berhasil: {r.get('username')}", GREEN)
            self.refresh_stats()
        elif t == "done":
            self.refresh_stats()
        elif t == "error":
            self.set_status(f"Error: {e.get('text')}", RED)
            messagebox.showerror("Terjadi kesalahan", str(e.get("text")))
        elif t == "finished":
            self.set_running(False)
            if self.ok_count >= self.target and self.target:
                self.set_status(f"Selesai! {self.ok_count} akun berhasil disimpan ke {daf.DEFAULT_OUTPUT_FILE}.", GREEN)
            else:
                self.set_status(f"Berhenti. {self.ok_count} dari {self.target} akun berhasil. Hasil sudah tersimpan.",
                                YELLOW)
            self.refresh_stats()


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
