# Membuat installer Windows

Installer (`Alhuda_Quran_Checker_Setup_x.y.z.exe`) dibuat dengan NSIS dan memuat Python 3.12 + library, jadi PC tujuan tidak perlu Python atau internet (kecuali aktivasi pertama).

1. Siapkan folder kerja `pkg/` berisi:
   - `runtime/`: salinan Python 3.12 Windows (tanpa `Lib/site-packages`, tkinter, test) + library hasil
     `pip install --target runtime/Lib/site-packages --platform win_amd64 --python-version 3.12 --abi cp312 --only-binary=:all: --no-deps -r installer/requirements-windows.txt`
   - `app/`: `app.py`, `quran_checker/`, `.streamlit/`, lalu `licensing/client/*` (`alhuda_license.py`, `alhuda_gate.py`, `gate_app.py`).
     Set `SERVER` di `alhuda_license.py` ke alamat server lisensi.
   - Kompilasi semua `.py` di `app/` kecuali `gate_app.py` menjadi `.pyc` tanpa sumber (`py_compile`, Python 3.12) dan hapus `.py`-nya.
   - `Alhuda Quran Checker.bat`, `alhuda.ico`, `installer.nsi` dari folder `installer/`.
2. Jalankan `makensis installer.nsi` (NSIS 3).

File `.exe` tidak disimpan di repo. Unduh dari tab **Releases**.

## Catatan lisensi

PyMuPDF berlisensi AGPL: aman untuk pemakaian internal, tetapi minta pertimbangan hukum sebelum aplikasi dibagikan ke pihak luar.
