#!/usr/bin/env python3
"""Launcher satu pintu untuk semua fitur Shopee Tools.

Jalankan:
    python main.py
"""

import asyncio
from pathlib import Path
import sys

import cek_misi_termux
import shopee_core
import voucher_claim

BASE_DIR = Path(__file__).resolve().parent

MENU = """
======================================================================
     🚀 SHOPEE TOOLS - MENU UTAMA
======================================================================
  1. 🎟️  Klaim Voucher ShopeeFood
  2. 🎯 Cek Misi Bayar QRIS
  3. 🍔 Cek Voucher Shopee Food
  4. ⚡ Cek Keduanya (Misi QRIS + Voucher Food)
  5. 📦 Mode Massal / Bulk (pilih fitur + file akun)
  6. 📝 Daftar Akun (lihat / tambah / buat dari template)
  7. 👥 Kelola Multi-Worker (Multi-Login Telegram)
  8. ⚙️  Reset Pengaturan (Hapus Sesi & API Telegram)
  0. 🚪 Keluar
======================================================================
"""


def _run_cek_misi(*cli_args: str) -> None:
    """Jalankan alur cek_misi_termux.main() dengan argumen CLI tertentu."""
    old_argv = sys.argv
    sys.argv = ["cek_misi_termux.py", *cli_args]
    try:
        asyncio.run(cek_misi_termux.main())
    finally:
        sys.argv = old_argv


def _list_account_files() -> list:
    files = []
    for p in sorted(BASE_DIR.glob("*.txt")):
        name = p.name
        if name.endswith(".example.txt") or name in ("requirements.txt",):
            continue
        if name.startswith(("hasil_", "valid_", "diskon_", "misi_selesai", "bot_responses")):
            continue
        files.append(p)
    return files


def _count_lines(path: Path) -> int:
    try:
        return sum(
            1
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    except OSError:
        return 0


def menu_daftar_akun() -> None:
    while True:
        files = _list_account_files()
        print("\n📝 DAFTAR AKUN")
        if files:
            for p in files:
                print(f"   • {p.name} ({_count_lines(p)} baris)")
        else:
            print("   (belum ada file akun .txt)")
        print("  [1] Buat file dari template (.example.txt)")
        print("  [2] Tambah akun ke file (ketik/paste, kosongkan baris untuk selesai)")
        print("  [3] Lihat isi file")
        print("  [0] Kembali")
        opt = input("Pilih [0-3]: ").strip()

        if opt == "1":
            templates = sorted(BASE_DIR.glob("*.example.txt"))
            if not templates:
                print("❌ Tidak ada template.")
                continue
            for i, t in enumerate(templates, 1):
                print(f"  [{i}] {t.name}")
            sel = input("Pilih template: ").strip()
            if not sel.isdigit() or not (1 <= int(sel) <= len(templates)):
                print("❌ Pilihan tidak valid.")
                continue
            src = templates[int(sel) - 1]
            dst = BASE_DIR / src.name.replace(".example", "")
            if dst.exists():
                print(f"⚠️ {dst.name} sudah ada, tidak ditimpa.")
                continue
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✅ Dibuat: {dst.name}. Pilih menu 2 untuk mengisi akun.")

        elif opt == "2":
            name = input("Nama file (mis. accounts.txt, food.txt, daftar_username.txt): ").strip()
            if not name:
                continue
            if Path(name).name != name or not name.endswith(".txt"):
                print("❌ Gunakan nama file .txt di folder ini saja.")
                continue
            print("Masukkan akun (satu per baris). Baris kosong = selesai:")
            lines = []
            while True:
                line = input("> ").strip()
                if not line:
                    break
                lines.append(line)
            if lines:
                path = BASE_DIR / name
                prefix = ""
                if path.exists():
                    existing = path.read_text(encoding="utf-8", errors="ignore")
                    if existing and not existing.endswith("\n"):
                        prefix = "\n"
                with path.open("a", encoding="utf-8") as f:
                    f.write(prefix + "\n".join(lines) + "\n")
                print(f"✅ {len(lines)} akun ditambahkan ke {name}.")

        elif opt == "3":
            name = input("Nama file: ").strip()
            path = BASE_DIR / Path(name).name
            if not path.is_file():
                print("❌ File tidak ditemukan.")
                continue
            print(f"\n--- {path.name} ---")
            print(path.read_text(encoding="utf-8", errors="ignore"))

        elif opt in ("0", "q", ""):
            return


def main() -> None:
    while True:
        print(MENU)
        choice = input("Pilih menu [0-8]: ").strip()
        if choice == "1":
            asyncio.run(voucher_claim.interactive_voucher_claim_menu())
        elif choice == "2":
            _run_cek_misi("--mode", "misi")
        elif choice == "3":
            _run_cek_misi("--mode", "food")
        elif choice == "4":
            _run_cek_misi("--mode", "both")
        elif choice == "5":
            print("\n  [1] Cek Misi QRIS  [2] Cek Voucher Food  [3] Keduanya  [4] Klaim Voucher")
            sel = input("Pilih fitur [1-4, default 1]: ").strip()
            mode = {"2": "food", "3": "both", "4": "claim"}.get(sel, "misi")
            _run_cek_misi("--mode", mode, "--bulk")
        elif choice == "6":
            menu_daftar_akun()
            continue
        elif choice == "7":
            asyncio.run(cek_misi_termux.kelola_workers_menu())
            continue
        elif choice == "8":
            shopee_core.reset_credentials()
        elif choice in ("0", "q", "exit"):
            print("Sampai jumpa!")
            return
        else:
            print("❌ Pilihan tidak valid.")
            continue

        input("\nTekan Enter untuk kembali ke menu utama...")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n\nDihentikan oleh pengguna.")
