#!/usr/bin/env python3
"""Modul Daftar Akun Fresh ShopeeFood via @shp_tools_bot (Telegram).

Flow:
1. /account
2. Klik 'Daftar Akun' (atau 'Register')
3. Bot minta nomor -> kirim nomor otomatis
4. Bot kirim OTP -> OTP diambil otomatis (dari pesan bot / SMS forwarder / manual)
5. Bot minta fingerprint -> kirim fingerprint custom tersimpan
6. Tangkap hasil akun (username/password/UserID/cookie) atau error
7. Jika error -> ulang dari /account (maks. retry per nomor)

OTP source didukung:
- 'bot'   : OTP muncul di pesan bot yang sama (paling umum untuk shp_tools_bot)
- 'sms'   : OTP diambil dari file otp_inbox.txt yang diisi SMS forwarder
- 'input' : manual via prompt (fallback)
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import re
from typing import List, Optional, Tuple, Union

from telethon.errors import FloodWaitError

import shopee_core

try:
    from colorama import init as _colorama_init
    _colorama_init(autoreset=False)
except ImportError:
    pass

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
WHITE = "\033[97m"
BOLD = "\033[1m"
RESET = "\033[0m"

DEFAULT_BOT = "@shp_tools_bot"
DEFAULT_OUTPUT_FILE = Path("akun_fresh.txt")
DEFAULT_COOKIE_FILE = Path("akun_fresh_cookies.txt")
DEFAULT_FAILED_FILE = Path("akun_fresh_failed.txt")
DEFAULT_FINGERPRINT_FILE = Path("fingerprints.json")
DEFAULT_OTP_INBOX = Path("otp_inbox.txt")

# Fingerprint default (custom, dari contoh BABA). Bisa diganti per akun
# lewat fingerprints.json.
DEFAULT_FINGERPRINT = (
    "1AY4z2Ws0NuJ8GJihuyEPQ==|GLcsyxSXAA+BRnfI5tZ0EPsUCicndgQJWzoiE9eIcgQ+"
    "CbgC8mPNTVNAoAvdLB8O1cONe2eMkvXeg6b1GYicbmIEA7dn|jGEEXF1l/xn9Sp3s|08|2"
)


# =====================================================================
# FINGERPRINT & OTP
# =====================================================================

def load_fingerprints() -> List[str]:
    """Load daftar fingerprint dari file JSON. Jika belum ada, buat dari default."""
    if DEFAULT_FINGERPRINT_FILE.is_file():
        try:
            data = json.loads(DEFAULT_FINGERPRINT_FILE.read_text(encoding="utf-8"))
            fps = [str(x).strip() for x in data.get("fingerprints", []) if str(x).strip()]
            if fps:
                return fps
        except Exception:
            pass
    try:
        DEFAULT_FINGERPRINT_FILE.write_text(
            json.dumps({"fingerprints": [DEFAULT_FINGERPRINT]}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return [DEFAULT_FINGERPRINT]


def save_fingerprints(fingerprints: List[str]) -> bool:
    """Simpan daftar fingerprint unik."""
    uniq = list(dict.fromkeys(str(f).strip() for f in fingerprints if str(f).strip()))
    try:
        DEFAULT_FINGERPRINT_FILE.write_text(
            json.dumps({"fingerprints": uniq}, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def pick_fingerprint(index: int = 0) -> str:
    """Ambil fingerprint berdasarkan urutan akun (round-robin)."""
    fps = load_fingerprints()
    if not fps:
        return DEFAULT_FINGERPRINT
    return fps[index % len(fps)]


async def wait_otp_from_inbox(phone: str, timeout: float = 90.0, poll: float = 1.5) -> Optional[str]:
    """Tunggu OTP masuk ke otp_inbox.txt untuk nomor tertentu.

    Format baris: <nomor>|<otp>  atau  <nomor>,<otp>
    """
    phone_clean = re.sub(r"\D", "", phone)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if DEFAULT_OTP_INBOX.is_file():
            try:
                lines = DEFAULT_OTP_INBOX.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in reversed(lines):  # OTP terbaru dulu
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = re.split(r"[|,;\t]+", line)
                    if len(parts) < 2:
                        continue
                    num = re.sub(r"\D", "", parts[0])
                    otp = re.sub(r"\D", "", parts[1])
                    if otp and (not num or num == phone_clean or phone_clean.endswith(num[-8:])):
                        return otp
            except Exception:
                pass
        await asyncio.sleep(poll)
    return None


async def wait_otp_from_bot(client, target_bot: str, after_id: int, timeout: float = 90.0, poll: float = 1.0) -> Optional[str]:
    """Tunggu pesan bot yang mengandung OTP (4-6 digit) setelah after_id."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        messages = await client.get_messages(target_bot, limit=10)
        for msg in sorted((m for m in messages if m.id > after_id and not getattr(m, "out", False)), key=lambda m: m.id):
            text = (getattr(msg, "text", "") or "").strip()
            if not text:
                continue
            low = text.casefold()
            if "otp" in low or "kode" in low or "verifikasi" in low or "verification" in low:
                m = re.search(r"\b(\d{4,6})\b", text)
                if m:
                    return m.group(1)
        await asyncio.sleep(poll)
    return None


# =====================================================================
# HELPER BOT
# =====================================================================

async def wait_button(client, target_bot: str, after_id: int, match_fn, timeout: float = 20.0, poll: float = 0.8):
    """Tunggu tombol inline yang cocok setelah after_id."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        messages = await client.get_messages(target_bot, limit=10)
        for msg in sorted((m for m in messages if m.id > after_id and not getattr(m, "out", False) and getattr(m, "buttons", None)), key=lambda m: m.id):
            for r, row in enumerate(msg.buttons):
                for c, btn in enumerate(row):
                    label = (getattr(btn, "text", "") or "").casefold()
                    if match_fn(label):
                        return msg, btn, r, c
        await asyncio.sleep(poll)
    return None, None, -1, -1


async def click(btn, msg, r: int, c: int):
    if hasattr(btn, "click") and callable(btn.click):
        await btn.click()
    elif hasattr(msg, "click") and callable(msg.click):
        await msg.click(r, c)
    else:
        raise RuntimeError("tombol tidak bisa diklik")


# =====================================================================
# PARSER HASIL AKUN
# =====================================================================

def parse_account_result(text: str) -> dict:
    """Parse teks hasil bot jadi dict: username, password, pin, phone, user_id, fingerprint, cookie, success, raw."""
    out = {
        "success": False,
        "username": "",
        "password": "",
        "pin": "",
        "phone": "",
        "user_id": "",
        "fingerprint": "",
        "device_id": "",
        "cookie": "",
        "raw": text or "",
        "error": "",
    }
    if not text:
        out["error"] = "empty"
        return out

    t = text
    low = t.casefold()

    has_success_marker = "berhasil didaftarkan" in low
    has_creds = ("username:" in low and "password:" in low) or ("userid:" in low and "nomor:" in low)

    def grab(label_patterns):
        for pat in label_patterns:
            m = re.search(pat + r"\s*[:\-]\s*([^\n\r]+)", t, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    out["username"] = grab([r"Username"])
    out["password"] = grab([r"Password"])
    out["pin"] = grab([r"PIN"])
    out["phone"] = grab([r"Nomor", r"Phone", r"No\. HP"])
    out["user_id"] = grab([r"UserID", r"User ID", r"UID"])
    out["fingerprint"] = grab([r"Fingerprint"])
    out["device_id"] = grab([r"deviceId", r"Device ID", r"DeviceID"])

    for line in t.splitlines():
        s = line.strip()
        if ("csrftoken=" in s or "SPC_EC=" in s or "SPC_U=" in s) and ";" in s and "=" in s:
            out["cookie"] = s
            break

    if has_success_marker or (has_creds and out["username"] and out["user_id"]):
        if not any(k in low for k in ("gagal didaftarkan", "tidak berhasil", "error mendaftar")):
            out["success"] = True

    if not out["success"]:
        err = ""
        for line in t.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(k in s.casefold() for k in ("gagal", "error", "tidak bisa", "ditolak", "limit", "banned", "tidak memenuhi")):
                err = s
                break
        out["error"] = err or "tidak ada penanda sukses"
    return out


# =====================================================================
# SIMPAN HASIL
# =====================================================================

def save_fresh_account(res: dict, output_file: Union[str, Path] = DEFAULT_OUTPUT_FILE,
                       cookie_file: Union[str, Path] = DEFAULT_COOKIE_FILE) -> bool:
    """Simpan akun sukses ke akun_fresh.txt + cookie ke akun_fresh_cookies.txt."""
    if not res.get("success"):
        return False
    out_path = Path(output_file)
    cookie_path = Path(cookie_file)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    line = (
        f"[{now_str}] {res.get('username') or '-'}|{res.get('password') or '-'}|"
        f"PIN:{res.get('pin') or '-'}|{res.get('phone') or '-'}|UID:{res.get('user_id') or '-'}|"
        f"DEV:{res.get('device_id') or '-'}|FP:{(res.get('fingerprint') or '-')[:24]}...\n"
    )
    try:
        with out_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

    if res.get("cookie"):
        try:
            with cookie_path.open("a", encoding="utf-8") as f:
                f.write(f"{res.get('username') or '-'}|{res['cookie']}\n")
        except Exception:
            pass
    return True


def save_failed_account(phone: str, reason: str, output_file: Union[str, Path] = DEFAULT_FAILED_FILE):
    """Catat percobaan gagal (nomor + alasan)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with Path(output_file).open("a", encoding="utf-8") as f:
            f.write(f"[{now_str}] {phone} | {reason}\n")
    except Exception:
        pass


# =====================================================================
# CORE FLOW: DAFTAR 1 AKUN
# =====================================================================

async def register_one_account(
    client,
    phone: str,
    fingerprint: str,
    target_bot: str = DEFAULT_BOT,
    otp_source: str = "bot",
    otp_timeout: float = 90.0,
    manual_otp_callback=None,
    on_step=None,
) -> Tuple[bool, str, dict]:
    """Daftarkan 1 akun fresh ke @shp_tools_bot.

    on_step: callback(str) opsional untuk menampilkan progres langkah.
    Returns (success, reason, parsed_result_dict).
    """
    def step(msg: str):
        if on_step:
            on_step(msg)

    # 1. Reset: kirim /account
    step("Mengirim /account ...")
    try:
        prev = await client.get_messages(target_bot, limit=1)
        last_id = prev[0].id if prev else 0
        cmd = await client.send_message(target_bot, "/account")
        last_id = max(last_id, cmd.id)
    except Exception as exc:
        return False, f"gagal kirim /account: {exc}", {}

    await asyncio.sleep(1.5)

    # 2. Klik tombol Daftar Akun
    def match_register(label: str) -> bool:
        return any(k in label for k in ("daftar akun", "register", "daftar baru", "buat akun", "sign up"))

    step("Mencari tombol 'Daftar Akun' ...")
    msg, btn, r, c = await wait_button(client, target_bot, last_id, match_register, timeout=20.0)
    if not btn:
        return False, "tombol 'Daftar Akun' tidak ditemukan", {}
    try:
        await click(btn, msg, r, c)
    except Exception as exc:
        return False, f"gagal klik Daftar Akun: {exc}", {}
    last_id = max(last_id, msg.id)
    await asyncio.sleep(1.5)

    # 3. Kirim nomor otomatis
    step("Mengirim nomor HP ...")
    phone_clean = re.sub(r"[^\d+]", "", phone)
    try:
        sent_phone = await client.send_message(target_bot, phone_clean)
        last_id = max(last_id, sent_phone.id)
    except Exception as exc:
        return False, f"gagal kirim nomor: {exc}", {}

    # 4. Tunggu OTP
    step(f"Menunggu OTP (sumber: {otp_source}, maks {int(otp_timeout)} dtk) ...")
    otp = None
    if otp_source == "bot":
        otp = await wait_otp_from_bot(client, target_bot, sent_phone.id, timeout=otp_timeout)
    elif otp_source == "sms":
        otp = await wait_otp_from_inbox(phone_clean, timeout=otp_timeout)
    if not otp and manual_otp_callback is not None:
        try:
            otp = await manual_otp_callback(phone_clean)
        except Exception:
            otp = None
    if not otp:
        return False, "OTP tidak diterima", {}
    if not re.fullmatch(r"\d{4,6}", otp):
        return False, f"format OTP aneh: {otp}", {}

    # 5. Kirim OTP
    step(f"OTP diterima ({otp}), mengirim ke bot ...")
    try:
        sent_otp = await client.send_message(target_bot, otp)
        last_id = max(last_id, sent_otp.id)
    except Exception as exc:
        return False, f"gagal kirim OTP: {exc}", {}
    await asyncio.sleep(1.5)

    # 6. Kirim fingerprint custom
    step("Mengirim fingerprint ...")
    try:
        sent_fp = await client.send_message(target_bot, fingerprint)
        last_id = max(last_id, sent_fp.id)
    except Exception as exc:
        return False, f"gagal kirim fingerprint: {exc}", {}

    # 7. Tunggu hasil final
    step("Menunggu hasil akun dari bot ...")
    deadline = asyncio.get_running_loop().time() + 60.0
    final_text = ""
    while asyncio.get_running_loop().time() < deadline:
        messages = await client.get_messages(target_bot, limit=10)
        for m in sorted((x for x in messages if x.id > sent_fp.id and not getattr(x, "out", False)), key=lambda x: x.id):
            txt = (getattr(m, "text", "") or "").strip()
            if not txt:
                continue
            low = txt.casefold()
            if any(k in low for k in ("memproses", "mohon tunggu", "loading")):
                continue
            if any(k in low for k in (
                "berhasil didaftarkan",
                "gagal", "error", "tidak bisa", "ditolak",
                "username:", "userid:", "password:",
            )):
                final_text = txt
                break
        if final_text:
            break
        await asyncio.sleep(1.0)

    if not final_text:
        return False, "timeout hasil akhir", {}

    parsed = parse_account_result(final_text)
    if parsed.get("success"):
        return True, "ok", parsed
    return False, parsed.get("error", "gagal didaftarkan"), parsed


# =====================================================================
# BATCH RUNNER
# =====================================================================

async def run_register_fresh_batch(
    client,
    phones: List[str],
    target_bot: str = DEFAULT_BOT,
    otp_source: str = "bot",
    otp_timeout: float = 90.0,
    step_delay: float = 6.0,
    max_retry_per_phone: int = 3,
    output_file: Union[str, Path] = DEFAULT_OUTPUT_FILE,
    cookie_file: Union[str, Path] = DEFAULT_COOKIE_FILE,
    manual_otp_callback=None,
) -> dict:
    """Batch daftar akun fresh. Tiap nomor dicoba ulang sampai sukses atau max_retry."""
    total = len(phones)
    if total == 0:
        print(f"{RED}❌ Daftar nomor kosong.{RESET}")
        return {"total": 0, "success": 0, "fail": 0, "results": []}

    print(f"\n{CYAN}{BOLD}===================================================={RESET}")
    print(f"📝 {BOLD}DAFTAR AKUN FRESH SHOPEEFOOD{RESET}")
    print(f"{CYAN}===================================================={RESET}")
    print(f"🎯 Bot        : {BOLD}{target_bot}{RESET}")
    print(f"📞 Jumlah     : {BOLD}{total} nomor{RESET}")
    print(f"🔑 Sumber OTP : {BOLD}{otp_source}{RESET}")
    print(f"📂 Hasil akun : {output_file}")
    print(f"🍪 Hasil cookie: {cookie_file}")
    print(f"{CYAN}----------------------------------------------------{RESET}")
    print(f"{YELLOW}Tekan Ctrl+C kapan saja untuk berhenti.{RESET}\n")

    success_count = 0
    fail_count = 0
    results = []
    stop_all = False

    for idx, phone in enumerate(phones, 1):
        if stop_all:
            break
        bar = shopee_core.render_progress_bar(idx, total)
        print(f"{CYAN}{bar}{RESET} Nomor {idx}/{total}: {BOLD}{phone}{RESET}")

        fp = pick_fingerprint(idx - 1)
        attempt = 0
        ok = False
        last_reason = ""
        while attempt < max_retry_per_phone and not ok:
            attempt += 1
            if attempt > 1:
                print(f"  ↻ Coba lagi ({attempt}/{max_retry_per_phone}) untuk {phone}")
                await asyncio.sleep(3)
            try:
                ok, reason, parsed = await register_one_account(
                    client=client,
                    phone=phone,
                    fingerprint=fp,
                    target_bot=target_bot,
                    otp_source=otp_source,
                    otp_timeout=otp_timeout,
                    manual_otp_callback=manual_otp_callback,
                    on_step=lambda m: print(f"  ├─ {m}"),
                )
                last_reason = reason
                if ok:
                    save_fresh_account(parsed, output_file, cookie_file)
                    print(f"  └─ {GREEN}{BOLD}✅ Berhasil: {parsed.get('username')} | UID {parsed.get('user_id')}{RESET}")
                    success_count += 1
                    results.append({"phone": phone, "success": True, "result": parsed})
                else:
                    print(f"  └─ {YELLOW}⚠️ Gagal: {reason}{RESET}")
            except FloodWaitError as exc:
                print(f"  └─ {RED}⚠️ Telegram FloodWait {exc.seconds} dtk. Proses dihentikan.{RESET}")
                last_reason = f"FloodWait {exc.seconds}s"
                stop_all = True
                break
            except Exception as exc:
                last_reason = f"exception: {exc}"
                print(f"  └─ {RED}❌ {last_reason}{RESET}")

        if not ok:
            save_failed_account(phone, last_reason or "gagal semua retry")
            fail_count += 1
            results.append({"phone": phone, "success": False, "reason": last_reason})

        print()
        if idx < total and not stop_all:
            await asyncio.sleep(step_delay)

    print(f"{CYAN}{BOLD}==================== RINGKASAN ===================={RESET}")
    print(f"📞 Total nomor  : {total}")
    print(f"{GREEN}✅ Berhasil      : {success_count}{RESET}")
    print(f"{RED}❌ Gagal         : {fail_count}{RESET}")
    print(f"📂 Akun tersimpan di : {output_file}")
    print(f"🍪 Cookie tersimpan di: {cookie_file}")
    if fail_count:
        print(f"📝 Daftar gagal di   : {DEFAULT_FAILED_FILE}")
    print()

    return {"total": total, "success": success_count, "fail": fail_count, "results": results}


# =====================================================================
# CLI / MENU
# =====================================================================

def read_phone_list(path: Union[str, Path]) -> List[str]:
    """Baca daftar nomor dari file teks (satu per baris, # komentar)."""
    p = Path(path.strip().strip('"').strip("'") if isinstance(path, str) else path)
    if not p.is_file():
        raise FileNotFoundError(f"file nomor tidak ditemukan: {p}")
    nums = []
    seen = set()
    for line in p.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        clean = re.sub(r"[^\d+]", "", s)
        if clean and clean not in seen:
            nums.append(clean)
            seen.add(clean)
    return nums


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [Enter = {default}]" if default else ""
    return input(f"{WHITE}{prompt}{suffix}: {RESET}").strip() or default


def _ask_number(prompt: str, default: float, minimum: float = 0.0) -> float:
    raw = _ask(prompt, str(default))
    try:
        return max(minimum, float(raw))
    except ValueError:
        print(f"{YELLOW}Input bukan angka, pakai default {default}.{RESET}")
        return default


def _collect_phones() -> List[str]:
    print(f"\n{CYAN}{BOLD}LANGKAH 1/3 - Nomor HP yang akan didaftarkan{RESET}")
    print("  [1] Baca dari file .txt (satu nomor per baris)")
    print("  [2] Paste langsung di sini")
    src = _ask("Pilih sumber", "2")
    phones: List[str] = []
    if src == "1":
        try:
            return read_phone_list(_ask("Nama file nomor (contoh: nomor.txt)"))
        except FileNotFoundError as exc:
            print(f"{RED}❌ {exc}{RESET}")
            return []
    print(f"{YELLOW}Paste nomor, satu per baris. Tekan Enter pada baris kosong jika sudah selesai.{RESET}")
    seen = set()
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if phones:
                break
            continue
        clean = re.sub(r"[^\d+]", "", line.strip())
        if clean and clean not in seen:
            phones.append(clean)
            seen.add(clean)
    return phones


async def interactive_register_menu():
    """Menu interaktif daftar akun fresh (3 langkah + konfirmasi)."""
    print(f"\n{CYAN}{BOLD}===================================================={RESET}")
    print(f"📝 {BOLD}DAFTAR AKUN FRESH SHOPEEFOOD ({DEFAULT_BOT}){RESET}")
    print(f"{CYAN}===================================================={RESET}")
    print("Bot akan otomatis: /account > Daftar Akun > nomor > OTP > fingerprint.")
    print("Jika gagal, proses diulang otomatis dari awal.")

    phones = _collect_phones()
    if not phones:
        print(f"{RED}❌ Tidak ada nomor yang valid. Kembali ke menu.{RESET}")
        return
    print(f"{GREEN}✔ {len(phones)} nomor siap diproses.{RESET}")

    print(f"\n{CYAN}{BOLD}LANGKAH 2/3 - Cara mengambil OTP{RESET}")
    print("  [1] Dari pesan bot Telegram   (paling umum)")
    print("  [2] Dari SMS forwarder        (file otp_inbox.txt, format: nomor|otp)")
    print("  [3] Ketik manual setiap OTP")
    otp_choice = _ask("Pilih sumber OTP", "1")
    otp_src = {"1": "bot", "2": "sms", "3": "input"}.get(otp_choice, "bot")

    print(f"\n{CYAN}{BOLD}LANGKAH 3/3 - Pengaturan{RESET}")
    delay = _ask_number("Jeda antar nomor (detik)", 6.0)
    retry = int(_ask_number("Maks. percobaan ulang per nomor", 3, minimum=1))
    fp_count = len(load_fingerprints())

    print(f"\n{CYAN}----------------- RINGKASAN PENGATURAN -----------------{RESET}")
    print(f" Nomor        : {len(phones)}")
    print(f" Sumber OTP   : {otp_src}")
    print(f" Jeda         : {delay:g} dtk | Retry: {retry}x")
    print(f" Fingerprint  : {fp_count} tersimpan ({DEFAULT_FINGERPRINT_FILE})")
    print(f"{CYAN}--------------------------------------------------------{RESET}")
    if _ask("Mulai sekarang? (Y/n)", "y").casefold() not in ("y", "ya", "yes"):
        print(f"{YELLOW}Dibatalkan.{RESET}")
        return

    manual_cb = None
    if otp_src == "input":
        async def _manual(phone: str):
            return await asyncio.to_thread(input, f"{WHITE}Masukkan OTP untuk {phone}: {RESET}")
        manual_cb = _manual
    else:
        # fallback manual jika otomatis gagal
        async def _fallback(phone: str):
            ans = await asyncio.to_thread(
                input, f"{YELLOW}OTP otomatis tidak masuk untuk {phone}. Ketik manual (Enter = lewati): {RESET}")
            return ans.strip() or None
        manual_cb = _fallback

    client = shopee_core.create_client()
    try:
        await shopee_core.start_client(client)
        await run_register_fresh_batch(
            client=client,
            phones=phones,
            otp_source=otp_src,
            step_delay=delay,
            max_retry_per_phone=retry,
            manual_otp_callback=manual_cb,
        )
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Dihentikan oleh pengguna.{RESET}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(interactive_register_menu())
    except (KeyboardInterrupt, EOFError):
        print("\nDihentikan.")
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
