@echo off
REM Bangun ShopeeTools.exe (jalankan di Windows, butuh Python 3.9+)
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name ShopeeTools --collect-all customtkinter gui.py
echo.
echo Selesai. File ada di: dist\ShopeeTools.exe
pause
