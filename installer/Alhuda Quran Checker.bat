@echo off
REM Alhuda Quran Checker (versi terpasang) - membuka http://localhost:8501
title Alhuda Quran Checker
set "ROOT=%~dp0"
set PYTHONNOUSERSITE=1
set PYTHONPATH=
set PYTHONHOME=

REM Lewati pertanyaan email Streamlit saat pertama kali dijalankan
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

cd /d "%ROOT%app"
echo Membuka Alhuda Quran Checker di http://localhost:8501 ...
echo Pembukaan pertama bisa memakan waktu 1-2 menit. Tutup jendela ini untuk menghentikan aplikasi.
"%ROOT%runtime\python.exe" -E -s -m streamlit run gate_app.py
if errorlevel 1 (
    echo.
    echo Aplikasi berhenti dengan galat. Jika port 8501 sedang dipakai, tutup jendela Alhuda Quran Checker lain lalu coba lagi.
)
pause
