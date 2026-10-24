@echo off
chcp 65001 >nul
title Build Shopee Tools EXE
echo ====================================================
echo   BUILD SHOPEE TOOLS (.exe)
echo ====================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python belum terpasang. Install dari https://www.python.org/downloads/
    echo     Centang "Add Python to PATH" saat instalasi.
    pause
    exit /b 1
)
echo [1/4] Memasang dependensi...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail
echo.
echo [2/4] Membuat DaftarAkunFresh.exe (aplikasi dengan tampilan jendela)...
python -m PyInstaller --onefile --windowed --clean --name DaftarAkunFresh ^
    --hidden-import shopee_core --hidden-import daftar_akun_fresh ^
    gui_daftar_akun.py
if errorlevel 1 goto :fail
echo.
echo [3/4] Membuat ShopeeBot.exe (menu konsol: cek misi, voucher, dll)...
python -m PyInstaller --onefile --console --name ShopeeBot ^
    --hidden-import daftar_akun_fresh --hidden-import voucher_claim ^
    --hidden-import food --hidden-import shopee_core ^
    cek_misi_termux.py
if errorlevel 1 goto :fail
echo.
echo [4/4] Selesai!
echo.
echo  dist\DaftarAkunFresh.exe  - Daftar akun fresh (tampilan jendela, ada tombol STOP)
echo  dist\ShopeeBot.exe        - Menu konsol lengkap
echo.
echo  Tips: sesi Telegram dan hasil disimpan di folder yang sama dengan file .exe.
echo.
pause
exit /b 0
:fail
echo.
echo [X] Build gagal. Cek pesan error di atas.
pause
exit /b 1
