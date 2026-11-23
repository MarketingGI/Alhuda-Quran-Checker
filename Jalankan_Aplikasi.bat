@echo off
REM Alhuda Quran Checker - jalankan di http://localhost:8501
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Menyiapkan lingkungan Python ^(hanya sekali, butuh internet untuk unduh library^)...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Python belum terpasang. Pasang Python 3.10 atau lebih baru dari python.org,
        echo centang "Add python.exe to PATH", lalu jalankan file ini lagi.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Gagal memasang library. Periksa koneksi internet lalu coba lagi.
        pause
        exit /b 1
    )
)

title Alhuda Quran Checker
echo [2/2] Membuka Alhuda Quran Checker di http://localhost:8501 ...
echo Tutup jendela ini untuk menghentikan aplikasi.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
