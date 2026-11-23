@echo off
REM Jalankan pengujian otomatis (kasus sengaja salah). Jalankan Jalankan_Aplikasi.bat sekali dulu.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest -v
pause
