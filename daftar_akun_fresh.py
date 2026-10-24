#!/usr/bin/env python3
"""Modul Daftar Akun Fresh ShopeeFood via @shp_tools_bot (Telegram).

Flow:
1. /account
2. Klik 'Daftar Akun'
3. Klik 'Nomor Otomatis' (inline button dari bot)
4. Tunggu bot ngasih respon (OTP / sukses / error)
5. Jika bot minta OTP -> kirim OTP (bisa otomatis dari chat / sms inbox)
6. Kirim fingerprint custom
7. Tangkap hasil akhir (cookie, userid, dll) atau error
8. Jika error -> ulang dari langkah 1 (sampai dapat / batas retry)
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

# Warna terminal
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

# Fallback fingerprint bawaan BABA
DEFAULT_FINGERPRINTS = [
    "uCRo2kEaXUghafMobGRK4A==|0oRwIeqwhjegupUe9pM+qaTtNUbf2vllEdNndC3tfs2AMDmjjb4u1YL4bVd1MqenPV4D3TlPYFCC3HjPPFsSFQ==|Jyy1VWPv6BrsApQu|08|2",
    "tyIINVG/X75cMujgMc/h4A==|d+ciza+Ap8WqPkn7GszY1Vh1V3QvjvEjXYe4Y6uWLujm8nWi0Wh6m/8Xzc10LnifIdoZXFidYDSrFNl5DzRW/18T+Q==|UUMSl5QlkVsH3/9N|08|2",
]

# =====================================================================
# KONFIGURASI FINGERPRINT & FILE
# =====================================================================

def load_fingerprints() -> List[str]:
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
            json.dumps({"fingerprints": DEFAULT_FINGERPRINTS}, indent=2), encoding="utf-8")
    except Exception:
        pass
    return list(DEFAULT_FINGERPRINTS)


def save_fingerprints(fingerprints: List[str]) -> bool:
    uniq = list(dict.fromkeys(str(f).strip() for f in fingerprints if str(f).strip()))
    try:
        DEFAULT_FINGERPRINT_FILE.write_text(json.dumps({"fingerprints": uniq}, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def pick_fingerprint(index: int = 0) -> str:
    fps = load_fingerprints()
    return fps[index % len(fps)] if fps else DEFAULT_FINGERPRINTS[0]

# =====================================================================
# HELPER OTP & BOT
# =====================================================================

async def wait_otp_from_inbox(phone: str, timeout: float = 90.0, poll: float = 1.5) -> Optional[str]:
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
                    if otp and (not phone_clean or not num or num == phone_clean or phone_clean.endswith(num[-8:])):
                        return otp
            except Exception:
                pass
        await asyncio.sleep(poll)
    return None


async def wait_otp_from_bot(client, target_bot: str, after_id: int, timeout: float = 90.0, poll: float = 1.0) -> Optional[str]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        messages = await client.get_messages(target_bot, limit=10)
        for msg in sorted((m for m in messages if m.id > after_id and not getattr(m, "out", False)), key=lambda m: m.id):
            text = (getattr(msg, "text", "") or "").strip()
            if not text:
                continue
            low = text.casefold()
            if "otp" in low or "kode" in low or "verifikasi" in low or "masukkan" in low:
                m = re.search(r"\b(\d{4,6})\b", text)
                if m:
                    return m.group(1)
        await asyncio.sleep(poll)
    return None


async def wait_button(client, target_bot: str, after_id: int, match_fn, timeout: float = 20.0, poll: float = 0.8):
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
# PARSER & PENYIMPANAN HASIL
# =====================================================================

def parse_account_result(text: str) -> dict:
    out = {
        "success": False, "username": "", "password": "", "pin": "", "phone": "",
        "user_id": "", "fingerprint": "", "device_id": "", "cookie": "", "raw": text or "", "error": "",
    }
    if not text:
        out["error"] = "empty text"
        return out

    low = text.casefold()
    has_success_marker = "berhasil didaftarkan" in low
    has_creds = ("username:" in low and "password:" in low) or ("userid:" in low and "nomor:" in low)

    def grab(label_patterns):
        for pat in label_patterns:
            m = re.search(pat + r"\s*[:\-]\s*([^\n\r]+)", text, re.IGNORECASE)
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

    for line in text.splitlines():
        s = line.strip()
        if ("csrftoken=" in s or "SPC_EC=" in s or "SPC_U=" in s) and ";" in s and "=" in s:
            out["cookie"] = s
            break

    if has_success_marker or (has_creds and out["username"] and out["user_id"]):
        if not any(k in low for k in ("gagal didaftarkan", "tidak berhasil", "error mendaftar")):
            out["success"] = True

    if not out["success"]:
        err = ""
        for line in text.splitlines():
            s = line.strip()
            if any(k in s.casefold() for k in ("gagal", "error", "tidak bisa", "ditolak", "limit", "banned", "tidak memenuhi", "captcha")):
                err = s
                break
        out["error"] = err or "tidak ada penanda sukses"
    return out


def save_fresh_account(res: dict, output_file: Union[str, Path] = DEFAULT_OUTPUT_FILE,
                       cookie_file: Union[str, Path] = DEFAULT_COOKIE_FILE):
    if not res.get("success"):
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"[{now_str}] {res.get('username') or '-'}|{res.get('password') or '-'}|PIN:{res.get('pin') or '-'}|"
        f"{res.get('phone') or '-'}|UID:{res.get('user_id') or '-'}|DEV:{res.get('device_id') or '-'}|"
        f"FP:{(res.get('fingerprint') or '')[:24]}...\n"
    )
    try:
        with Path(output_file).open("a", encoding="utf-8") as f:
            f.write(line)
        if res.get("cookie"):
            with Path(cookie_file).open("a", encoding="utf-8") as f:
                f.write(f"{res.get('username') or '-'}|{res['cookie']}\n")
    except Exception:
        pass
    return True


def save_failed_account(phone: str, reason: str, output_file: Union[str, Path] = DEFAULT_FAILED_FILE):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with Path(output_file).open("a", encoding="utf-8") as f:
            f.write(f"[{now_str}] {phone if phone else 'OTOMATIS'} | {reason}\n")
    except Exception:
        pass

# =====================================================================
# CORE FLOW: DAFTAR 1 AKUN
# =====================================================================

async def register_one_account(
    client, target_bot: str = DEFAULT_BOT, otp_source: str = "bot",
    otp_timeout: float = 90.0, manual_otp_callback=None, fp_index: int = 0,
    on_step=None,
) -> Tuple[bool, str, dict]:

    def step(msg: str):
        if on_step:
            on_step(msg)

    # 1. /account
    step("Mengirim /account ...")
    try:
        prev = await client.get_messages(target_bot, limit=1)
        last_id = prev[0].id if prev else 0
        cmd = await client.send_message(target_bot, "/account")
        last_id = max(last_id, cmd.id)
    except Exception as exc:
        return False, f"gagal kirim /account: {exc}", {}

    await asyncio.sleep(1.5)

    # 2. Klik 'Daftar Akun'
    def match_register(label: str) -> bool:
        return any(k in label for k in ("daftar akun", "register", "daftar baru", "buat akun"))

    step("Klik tombol 'Daftar Akun' ...")
    msg, btn, r, c = await wait_button(client, target_bot, last_id, match_register, timeout=20.0)
    if not btn:
        return False, "tombol 'Daftar Akun' tidak ditemukan", {}
    try:
        await click(btn, msg, r, c)
    except Exception as exc:
        return False, f"gagal klik Daftar Akun: {exc}", {}
    last_id = max(last_id, msg.id)
    await asyncio.sleep(1.5)

    # 3. Klik 'Nomor Otomatis'
    def match_auto_number(label: str) -> bool:
        return any(k in label for k in ("nomor otomatis", "otomatis", "auto number"))

    step("Klik tombol 'Nomor Otomatis' ...")
    msg, btn, r, c = await wait_button(client, target_bot, last_id, match_auto_number, timeout=20.0)
    if not btn:
        return False, "tombol 'Nomor Otomatis' tidak ditemukan", {}
    try:
        await click(btn, msg, r, c)
    except Exception as exc:
        return False, f"gagal klik Nomor Otomatis: {exc}", {}
    last_id = max(last_id, msg.id)
    await asyncio.sleep(1.5)

    # 4. Tunggu OTP
    step(f"Menunggu OTP (sumber: {otp_source}, maks {int(otp_timeout)} dtk) ...")
    otp = None
    if otp_source == "bot":
        otp = await wait_otp_from_bot(client, target_bot, last_id, timeout=otp_timeout)
    elif otp_source == "sms":
        otp = await wait_otp_from_inbox("", timeout=otp_timeout)

    if not otp and manual_otp_callback is not None:
        try:
            otp = await manual_otp_callback("")
        except Exception:
            pass

    if otp:
        if not re.fullmatch(r"\d{4,6}", otp):
            return False, f"format OTP aneh: {otp}", {}
        step(f"OTP diterima ({otp}), mengirim ke bot ...")
        try:
            sent_otp = await client.send_message(target_bot, otp)
            last_id = max(last_id, sent_otp.id)
            await asyncio.sleep(2.0)
        except Exception as exc:
            return False, f"gagal kirim OTP: {exc}", {}

    # 5. Kirim Fingerprint
    step("Mengirim fingerprint ...")
    fp = pick_fingerprint(fp_index)
    try:
        sent_fp = await client.send_message(target_bot, fp)
        last_id = max(last_id, sent_fp.id)
    except Exception as exc:
        return False, f"gagal kirim fingerprint: {exc}", {}

    # 6. Tunggu Hasil Akhir
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
                "berhasil didaftarkan", "gagal", "error", "tidak bisa",
                "ditolak", "captcha", "provider", "limit", "username:", "userid:",
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
    client, total_target: int = 10, target_bot: str = DEFAULT_BOT,
    otp_source: str = "bot", otp_timeout: float = 90.0, step_delay: float = 5.0,
    max_retry_per_target: int = 99,
    output_file: Union[str, Path] = DEFAULT_OUTPUT_FILE,
    cookie_file: Union[str, Path] = DEFAULT_COOKIE_FILE,
    manual_otp_callback=None,
    on_event=None,
) -> dict:
    """on_event(dict) opsional: type = attempt | step | success | fail | done."""
    def emit(**kw):
        if on_event:
            try:
                on_event(kw)
            except Exception:
                pass


    if total_target <= 0:
        print(f"{RED}❌ Target harus lebih dari 0.{RESET}")
        return {"total": 0, "success": 0, "fail": 0, "results": []}

    print(f"\n{CYAN}{BOLD}===================================================={RESET}")
    print(f"📝 {BOLD}DAFTAR AKUN FRESH SHOPEEFOOD{RESET}")
    print(f"{CYAN}===================================================={RESET}")
    print(f"🤖 Bot         : {BOLD}{target_bot}{RESET}")
    print(f"🎯 Target akun : {BOLD}{total_target}{RESET}")
    print(f"🔑 Sumber OTP  : {BOLD}{otp_source}{RESET}")
    print(f"📂 Hasil akun  : {output_file}")
    print(f"🍪 Hasil cookie: {cookie_file}")
    print(f"{CYAN}----------------------------------------------------{RESET}")
    print(f"{YELLOW}Tekan Ctrl+C kapan saja untuk berhenti.{RESET}\n")

    success_count = 0
    fail_count = 0
    results = []
    stop_all = False
    global_idx = 0

    try:
        while success_count < total_target and not stop_all:
            global_idx += 1
            emit(type="attempt", index=global_idx, success=success_count, fail=fail_count, target=total_target)
            bar = shopee_core.render_progress_bar(success_count, total_target)
            print(f"{CYAN}{bar}{RESET} Akun {success_count + 1}/{total_target} "
                  f"(butuh {total_target - success_count} lagi)")

            attempt = 0
            ok = False
            last_reason = ""

            while attempt < max_retry_per_target and not ok:
                attempt += 1
                if attempt > 1:
                    print(f"  ↻ Ulang dari awal (percobaan #{attempt}) ...")
                    await asyncio.sleep(3)
                try:
                    ok, reason, parsed = await register_one_account(
                        client=client, target_bot=target_bot, otp_source=otp_source,
                        otp_timeout=otp_timeout, manual_otp_callback=manual_otp_callback,
                        fp_index=global_idx, on_step=lambda m: (print(f"  ├─ {m}"), emit(type="step", text=m)),
                    )
                    last_reason = reason
                    if ok:
                        save_fresh_account(parsed, output_file, cookie_file)
                        print(f"  └─ {GREEN}{BOLD}✅ Berhasil: {parsed.get('username')} | UID {parsed.get('user_id')}{RESET}")
                        success_count += 1
                        emit(type="success", result=parsed, success=success_count, fail=fail_count, target=total_target)
                        results.append({"attempt": global_idx, "success": True, "result": parsed})
                    else:
                        print(f"  └─ {YELLOW}⚠️ Gagal: {reason}{RESET}")
                        emit(type="attempt_fail", reason=reason)
                except FloodWaitError as exc:
                    print(f"  └─ {RED}⚠️ Telegram FloodWait {exc.seconds} dtk. Proses dihentikan.{RESET}")
                    last_reason = f"FloodWait {exc.seconds}s"
                    stop_all = True
                    break
                except Exception as exc:
                    last_reason = f"exception: {exc}"
                    print(f"  └─ {RED}❌ {last_reason}{RESET}")

            if not ok:
                save_failed_account("OTOMATIS", last_reason or "gagal semua retry")
                fail_count += 1
                emit(type="fail", reason=last_reason, success=success_count, fail=fail_count, target=total_target)
                results.append({"attempt": global_idx, "success": False, "reason": last_reason})

            print()
            if not stop_all and success_count < total_target:
                await asyncio.sleep(step_delay)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(f"\n{YELLOW}Dihentikan oleh pengguna.{RESET}")

    print(f"{CYAN}{BOLD}==================== RINGKASAN ===================={RESET}")
    print(f"🎯 Target akun     : {total_target}")
    print(f"🔄 Total percobaan : {global_idx}")
    print(f"{GREEN}✅ Berhasil         : {success_count}{RESET}")
    print(f"{RED}❌ Gagal            : {fail_count}{RESET}")
    print(f"📂 File hasil       : {output_file} & {cookie_file}\n")

    emit(type="done", success=success_count, fail=fail_count, target=total_target, attempts=global_idx)
    return {"total": total_target, "success": success_count, "fail": fail_count, "results": results}

# =====================================================================
# CLI / MENU
# =====================================================================

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [Enter = {default}]" if default else ""
    return input(f"{WHITE}{prompt}{suffix}: {RESET}").strip() or default


async def interactive_register_menu():
    print(f"\n{CYAN}{BOLD}===================================================={RESET}")
    print(f"📝 {BOLD}DAFTAR AKUN FRESH ({DEFAULT_BOT}){RESET}")
    print(f"{CYAN}===================================================={RESET}")
    print("Otomatis: /account > Daftar Akun > Nomor Otomatis > OTP > fingerprint.")
    print("Jika gagal, proses diulang otomatis dari awal sampai target tercapai.")

    print(f"\n{CYAN}{BOLD}LANGKAH 1/3 - Jumlah akun{RESET}")
    target_str = _ask("Mau daftar berapa akun fresh?", "10")
    total_target = int(target_str) if target_str.isdigit() and int(target_str) > 0 else 10

    print(f"\n{CYAN}{BOLD}LANGKAH 2/3 - Cara mengambil OTP{RESET}")
    print("  [1] Dari pesan bot Telegram (paling umum)")
    print("  [2] Dari SMS forwarder (file otp_inbox.txt, format: nomor|otp)")
    print("  [3] Ketik manual setiap OTP")
    otp_src = {"1": "bot", "2": "sms", "3": "input", "bot": "bot", "sms": "sms", "input": "input"}.get(
        _ask("Pilih sumber OTP", "1").casefold(), "bot")

    print(f"\n{CYAN}{BOLD}LANGKAH 3/3 - Pengaturan{RESET}")
    delay = 6.0
    raw_delay = _ask("Jeda antar akun (detik)", "6")
    try:
        delay = max(0.0, float(raw_delay))
    except ValueError:
        print(f"{YELLOW}Bukan angka, pakai 6 detik.{RESET}")

    print(f"\n{CYAN}---------------- RINGKASAN PENGATURAN ----------------{RESET}")
    print(f" Target akun : {total_target}")
    print(f" Sumber OTP  : {otp_src}")
    print(f" Jeda        : {delay:g} dtk")
    print(f" Fingerprint : {len(load_fingerprints())} tersimpan ({DEFAULT_FINGERPRINT_FILE})")
    print(f"{CYAN}------------------------------------------------------{RESET}")
    if _ask("Mulai sekarang? (Y/n)", "y").casefold() not in ("y", "ya", "yes"):
        print(f"{YELLOW}Dibatalkan.{RESET}")
        return

    async def _manual(_phone: str):
        label = "Masukkan OTP" if otp_src == "input" else "OTP otomatis tidak masuk. Ketik manual (Enter = lewati)"
        ans = await asyncio.to_thread(input, f"{YELLOW}{label}: {RESET}")
        return ans.strip() or None

    client = shopee_core.create_client()
    try:
        await shopee_core.start_client(client)
        await run_register_fresh_batch(
            client=client, total_target=total_target, otp_source=otp_src,
            step_delay=delay, manual_otp_callback=_manual,
        )
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
