@echo off
chcp 65001 >nul
title Build ShopeeBot EXE
echo ====================================================
echo   BUILD SHOPEE BOT ALL-IN-ONE (.exe)
echo ====================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python belum terpasang. Install dari https://www.python.org/downloads/
    echo     Centang "Add Python to PATH" saat instalasi.
    pause
    exit /b 1
)
echo [1/3] Memasang dependensi...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail
echo.
echo [2/3] Membuat file .exe (tunggu 1-3 menit)...
python -m PyInstaller --onefile --console --clean --name ShopeeBot ^
    --hidden-import daftar_akun_fresh --hidden-import voucher_claim ^
    --hidden-import food --hidden-import shopee_core ^
    cek_misi_termux.py
if errorlevel 1 goto :fail
echo.
echo [3/3] Selesai!
echo.
echo  File EXE : dist\ShopeeBot.exe
echo  Jalankan : double-click ShopeeBot.exe
echo  Tips     : taruh file nomor.txt / accounts.txt di folder yang sama
echo             dengan ShopeeBot.exe agar terbaca otomatis.
echo.
pause
exit /b 0
:fail
echo.
echo [X] Build gagal. Cek pesan error di atas.
pause
exit /b 1
