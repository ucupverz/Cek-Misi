#!/usr/bin/env python3
"""Modul Daftar Akun Fresh ShopeeFood via @shp_tools_bot (Telegram).

Flow (mengikuti respons bot / stateful):
1. /account -> klik 'Daftar Akun' -> klik 'Nomor Otomatis'
2. Bot sendiri yang mengurus OTP ("Menunggu OTP masuk ... kirim ulang #N").
   Kita cukup menunggu sampai bot memberi salah satu hasil:
   a. "OTP tak masuk ... Coba lagi /account" / error lain -> gagal, ulang dari /account
   b. "OTP benar" + tombol "Fingerprint Otomatis" / "Fingerprint Custom"
      -> klik tombol sesuai pilihan (TIDAK ada string fingerprint yang dikirim ke chat)
   (untuk Custom: bot lalu menampilkan tombol "Gunakan Fingerprint Tersimpan" -> diklik juga)
3. Tunggu hasil akhir akun (username / password / UserID / cookie) lalu simpan.
"""

import asyncio
from datetime import datetime
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

# Batas aman menunggu OTP + hasil dari bot (bot sendiri menunggu ~61 dtk x beberapa kirim ulang)
DEFAULT_WAIT_TIMEOUT = 420.0


# =====================================================================
# HELPER BOT
# =====================================================================

def _bot_messages_since(messages, base_id: int):
    """Pesan dari bot (bukan kita) yang lebih baru dari base_id, urut naik."""
    return sorted((m for m in messages if m.id > base_id and not getattr(m, "out", False)), key=lambda m: m.id)


def _iter_buttons(msg):
    for r, row in enumerate(getattr(msg, "buttons", None) or []):
        for c, btn in enumerate(row):
            yield r, c, btn


async def wait_button(client, target_bot: str, base_id: int, match_fn, timeout: float = 20.0, poll: float = 0.8):
    """Tunggu tombol inline yang labelnya cocok pada pesan bot setelah base_id.

    Dibaca ulang tiap polling, jadi pesan yang di-EDIT bot (tombol berganti)
    tetap terdeteksi.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        messages = await client.get_messages(target_bot, limit=15)
        for msg in reversed(_bot_messages_since(messages, base_id)):  # terbaru dulu
            for r, c, btn in _iter_buttons(msg):
                if match_fn((getattr(btn, "text", "") or "").casefold()):
                    return msg, btn, r, c
        if asyncio.get_running_loop().time() >= deadline:
            return None, None, -1, -1
        await asyncio.sleep(poll)


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
        out["error"] = _first_error_line(text) or "tidak ada penanda sukses"
    return out


_ERROR_KEYS = ("gagal", "error", "tidak bisa", "ditolak", "limit", "banned", "tidak memenuhi",
               "captcha", "provider", "otp tak masuk", "coba lagi", "timeout", "habis", "tidak tersedia")


def _first_error_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s and any(k in s.casefold() for k in _ERROR_KEYS + ("❌",)):
            return s
    return ""


# =====================================================================
# PENYIMPANAN HASIL
# =====================================================================

def save_fresh_account(res: dict, output_file: Union[str, Path] = DEFAULT_OUTPUT_FILE,
                       cookie_file: Union[str, Path] = DEFAULT_COOKIE_FILE) -> bool:
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


def save_failed_account(reason: str, output_file: Union[str, Path] = DEFAULT_FAILED_FILE):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with Path(output_file).open("a", encoding="utf-8") as f:
            f.write(f"[{now_str}] {reason}\n")
    except Exception:
        pass


# =====================================================================
# KLASIFIKASI PESAN BOT
# =====================================================================

def classify_bot_text(text: str) -> str:
    """Kembalikan: 'success' | 'waiting' | 'otp_ok' | 'error' | 'other'."""
    low = (text or "").casefold()
    if not low.strip():
        return "other"
    if "berhasil didaftarkan" in low or (("username:" in low and "password:" in low)
                                         or ("userid:" in low and "nomor:" in low)):
        return "success"
    if "menunggu otp" in low or "memproses" in low or "mohon tunggu" in low or "loading" in low:
        return "waiting"
    if "otp benar" in low or "otp terverifikasi" in low:
        return "otp_ok"
    if "❌" in text or any(k in low for k in _ERROR_KEYS):
        return "error"
    return "other"


def _is_fp_button(label: str) -> bool:
    return "fingerprint" in label and ("custom" in label or "otomatis" in label)


def _is_stored_fp_button(label: str) -> bool:
    """Tombol 'Gunakan Fingerprint Tersimpan' (muncul setelah memilih Fingerprint Custom)."""
    return "tersimpan" in label


# =====================================================================
# CORE FLOW: DAFTAR 1 AKUN
# =====================================================================

async def register_one_account(
    client,
    target_bot: str = DEFAULT_BOT,
    use_custom_fp: bool = True,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    on_step=None,
    poll: float = 1.5,
) -> Tuple[bool, str, dict]:
    """Daftarkan 1 akun. Return (sukses, alasan, hasil_parse)."""

    def step(msg: str):
        if on_step:
            on_step(msg)

    loop = asyncio.get_running_loop()

    # 1. /account
    step("Mengirim /account ...")
    try:
        cmd = await client.send_message(target_bot, "/account")
        base_id = cmd.id
    except Exception as exc:
        return False, f"gagal kirim /account: {exc}", {}
    await asyncio.sleep(1.5)

    # 2. Klik 'Daftar Akun'
    step("Klik tombol 'Daftar Akun' ...")
    msg, btn, r, c = await wait_button(
        client, target_bot, base_id,
        lambda l: any(k in l for k in ("daftar akun", "register", "daftar baru", "buat akun")),
        timeout=25.0)
    if not btn:
        return False, "tombol 'Daftar Akun' tidak ditemukan", {}
    try:
        await click(btn, msg, r, c)
    except Exception as exc:
        return False, f"gagal klik Daftar Akun: {exc}", {}
    await asyncio.sleep(1.5)

    # 3. Klik 'Nomor Otomatis'
    step("Klik tombol 'Nomor Otomatis' ...")
    msg, btn, r, c = await wait_button(
        client, target_bot, base_id,
        lambda l: any(k in l for k in ("nomor otomatis", "auto number", "nomor auto")),
        timeout=25.0)
    if not btn:
        return False, "tombol 'Nomor Otomatis' tidak ditemukan", {}
    try:
        await click(btn, msg, r, c)
    except Exception as exc:
        return False, f"gagal klik Nomor Otomatis: {exc}", {}
    await asyncio.sleep(2.0)

    # 4. Ikuti state bot: tunggu OTP -> pilih fingerprint -> hasil akhir
    step("Menunggu bot memproses OTP (bot kirim ulang sendiri, harap sabar) ...")
    fp_wanted = "custom" if use_custom_fp else "otomatis"
    fp_clicked_ids = set()
    stored_clicked_ids = set()
    last_state = ""
    deadline = loop.time() + wait_timeout

    while loop.time() < deadline:
        messages = await client.get_messages(target_bot, limit=15)
        bot_msgs = _bot_messages_since(messages, base_id)

        # 4a. Hasil akhir sukses (pesan mana pun)
        for m in reversed(bot_msgs):
            txt = (getattr(m, "text", "") or "").strip()
            if txt and classify_bot_text(txt) == "success":
                parsed = parse_account_result(txt)
                if parsed.get("success"):
                    return True, "ok", parsed
                return False, parsed.get("error") or "hasil tidak valid", parsed

        # 4b0. Setelah Fingerprint Custom: klik 'Gunakan Fingerprint Tersimpan'
        stored = None
        for m in reversed(bot_msgs):
            if m.id in stored_clicked_ids:
                continue
            for r2, c2, b in _iter_buttons(m):
                if _is_stored_fp_button((getattr(b, "text", "") or "").casefold()):
                    stored = (m, r2, c2, b)
                    break
            if stored:
                break
        if stored:
            m, r2, c2, b = stored
            step(f"Klik '{b.text}' ...")
            try:
                await click(b, m, r2, c2)
            except Exception as exc:
                return False, f"gagal klik fingerprint tersimpan: {exc}", {}
            stored_clicked_ids.add(m.id)
            last_state = "fp"
            await asyncio.sleep(2.0)
            continue

        # 4b. Tombol pilihan fingerprint (OTP sudah benar)
        for m in reversed(bot_msgs):
            if m.id in fp_clicked_ids:
                continue
            fp_btns = [(r2, c2, b) for r2, c2, b in _iter_buttons(m)
                       if _is_fp_button((getattr(b, "text", "") or "").casefold())]
            if not fp_btns:
                continue
            pick = next((x for x in fp_btns if fp_wanted in (x[2].text or "").casefold()), None)
            if pick is None:
                return False, f"tombol Fingerprint {fp_wanted.title()} tidak ada di bot", {}
            step(f"OTP benar. Klik '{pick[2].text}' ...")
            try:
                await click(pick[2], m, pick[0], pick[1])
            except Exception as exc:
                return False, f"gagal klik fingerprint: {exc}", {}
            fp_clicked_ids.add(m.id)
            last_state = "fp"
            await asyncio.sleep(2.0)
            break
        else:
            # 4c. Pesan bot terbaru menentukan state: error / menunggu
            latest = next((m for m in reversed(bot_msgs) if (getattr(m, "text", "") or "").strip()), None)
            if latest is not None:
                txt = latest.text.strip()
                state = classify_bot_text(txt)
                if state == "error":
                    return False, _first_error_line(txt) or txt.splitlines()[0], {}
                if state == "waiting" and last_state != "wait":
                    last_state = "wait"
                    step("Bot menunggu OTP masuk ... (tunggu terus, jangan pindah command)")
                elif state == "otp_ok" and last_state != "otp_ok":
                    last_state = "otp_ok"
                    step("OTP benar, menunggu pilihan fingerprint dari bot ...")
                elif fp_clicked_ids and last_state == "fp":
                    last_state = "fp_wait"
                    step("Fingerprint dipilih, menunggu hasil akun ...")
        await asyncio.sleep(poll)

    if fp_clicked_ids or stored_clicked_ids:
        return False, "timeout menunggu hasil akhir setelah fingerprint", {}
    return False, "timeout menunggu OTP / respons bot", {}


# =====================================================================
# BATCH RUNNER
# =====================================================================

async def run_register_fresh_batch(
    client,
    total_target: int = 10,
    target_bot: str = DEFAULT_BOT,
    use_custom_fp: bool = True,
    step_delay: float = 5.0,
    retry_delay: float = 3.0,
    output_file: Union[str, Path] = DEFAULT_OUTPUT_FILE,
    cookie_file: Union[str, Path] = DEFAULT_COOKIE_FILE,
    on_event=None,
) -> dict:
    """Ulangi flow dari /account sampai jumlah akun target tercapai.

    Berhenti lewat Ctrl+C / membatalkan task (tombol Berhenti di aplikasi).
    on_event(dict): type = attempt | step | attempt_fail | success | done
    """
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
    print(f"📝 {BOLD}DAFTAR AKUN{RESET}")
    print(f"{CYAN}===================================================={RESET}")
    print(f"🤖 Bot         : {BOLD}{target_bot}{RESET}")
    print(f"🎯 Target akun : {BOLD}{total_target}{RESET}")
    print(f"🔑 Fingerprint : {BOLD}{'Custom' if use_custom_fp else 'Otomatis'}{RESET}")
    print(f"📂 Hasil       : {output_file}")
    print(f"{CYAN}----------------------------------------------------{RESET}\n")

    success_count = 0
    fail_count = 0
    attempts = 0
    results = []

    try:
        while success_count < total_target:
            attempts += 1
            bar = shopee_core.render_progress_bar(success_count, total_target)
            print(f"{CYAN}{bar}{RESET} Percobaan ke-{attempts} (butuh {total_target - success_count} lagi)")
            emit(type="attempt", index=attempts, success=success_count, fail=fail_count, target=total_target)
            try:
                ok, reason, parsed = await register_one_account(
                    client, target_bot=target_bot, use_custom_fp=use_custom_fp,
                    on_step=lambda m: (print(f"  ├─ {m}"), emit(type="step", text=m)))
            except FloodWaitError as exc:
                print(f"  └─ {YELLOW}⚠️ Telegram FloodWait {exc.seconds} dtk, istirahat dulu ...{RESET}")
                emit(type="step", text=f"FloodWait {exc.seconds} dtk, menunggu ...")
                await asyncio.sleep(exc.seconds + 3)
                continue
            except Exception as exc:
                ok, reason, parsed = False, f"exception: {exc}", {}

            if ok:
                save_fresh_account(parsed, output_file, cookie_file)
                success_count += 1
                results.append({"attempt": attempts, "success": True, "result": parsed})
                print(f"  └─ {GREEN}{BOLD}✅ Akun berhasil: {parsed.get('username')} | UID {parsed.get('user_id')}{RESET}\n")
                emit(type="success", result=parsed, success=success_count, fail=fail_count, target=total_target)
                if success_count < total_target:
                    await asyncio.sleep(step_delay)
            else:
                fail_count += 1
                save_failed_account(reason)
                results.append({"attempt": attempts, "success": False, "reason": reason})
                print(f"  └─ {YELLOW}⚠️ Gagal: {reason}{RESET}")
                print(f"  ↻ Ulang dari /account ...\n")
                emit(type="attempt_fail", reason=reason)
                await asyncio.sleep(retry_delay)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(f"\n{YELLOW}Dihentikan oleh pengguna.{RESET}")

    print(f"{CYAN}{BOLD}==================== RINGKASAN ===================={RESET}")
    print(f"🎯 Target akun     : {total_target}")
    print(f"🔄 Total percobaan : {attempts}")
    print(f"{GREEN}✅ Berhasil         : {success_count}{RESET}")
    print(f"{RED}❌ Percobaan gagal  : {fail_count}{RESET}")
    print(f"📂 File hasil       : {output_file}\n")
    emit(type="done", success=success_count, fail=fail_count, target=total_target, attempts=attempts)
    return {"total": total_target, "success": success_count, "fail": fail_count, "results": results}


# =====================================================================
# MENU KONSOL
# =====================================================================

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [Enter = {default}]" if default else ""
    return input(f"{WHITE}{prompt}{suffix}: {RESET}").strip() or default


async def interactive_register_menu():
    print(f"\n{CYAN}{BOLD}===================================================={RESET}")
    print(f"📝 {BOLD}DAFTAR AKUN ({DEFAULT_BOT}){RESET}")
    print(f"{CYAN}===================================================={RESET}")
    print("Otomatis: /account > Daftar Akun > Nomor Otomatis > (bot urus OTP) > pilih fingerprint.")
    print("Jika bot gagal, proses diulang dari /account sampai target tercapai. Ctrl+C untuk berhenti.\n")
    raw = _ask("Mau daftar berapa akun?", "10")
    total = int(raw) if raw.isdigit() and int(raw) > 0 else 10
    print("  [1] Fingerprint Custom\n  [2] Fingerprint Otomatis")
    use_custom = _ask("Pilih fingerprint", "1") != "2"
    delay = 6.0
    try:
        delay = max(0.0, float(_ask("Jeda antar akun (detik)", "6")))
    except ValueError:
        pass

    client = shopee_core.create_client()
    try:
        await shopee_core.start_client(client)
        await run_register_fresh_batch(client, total_target=total, use_custom_fp=use_custom, step_delay=delay)
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
