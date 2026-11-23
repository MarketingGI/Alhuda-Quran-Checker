# Alhuda Quran Checker

Aplikasi lokal untuk membandingkan PDF naskah mushaf dengan master rujukan sebelum turun cetak.
Berjalan di `http://localhost:8501`, sepenuhnya offline. Pembandingnya **deterministik (kode)**:
tidak ada AI yang menilai, menebak, atau mengoreksi teks Al-Qur'an.

## Menjalankan (Windows 11)

1. Pasang **Python 3.10+** dari python.org (centang *Add python.exe to PATH*).
2. Klik dua kali **`Jalankan_Aplikasi.bat`**.
   - Pertama kali: library diunduh sekali (butuh internet ±5 menit). Setelah itu bisa offline.
   - Browser terbuka di `http://localhost:8501`.
3. Unggah **Master** dan **Naskah**, tekan **Bandingkan**.
4. Lihat temuan (tab *Daftar temuan* / *Tampilan per halaman*), lalu **Siapkan laporan PDF → Unduh**.

Aplikasi hanya mendengarkan `localhost`, jadi tidak bisa diakses dari komputer lain.
Telemetri Streamlit dimatikan (`.streamlit/config.toml`).

## Produk baru tanpa master: teks standar Kemenag

Untuk produk baru (desain baru) yang belum punya master PDF, pilih **Sumber master → Teks standar Kemenag**.
Cukup unggah naskahnya, lalu tekan **Periksa**.

- **Syarat:** naskah harus PDF dengan **teks hidup**, yaitu diekspor dari InDesign *sebelum* teks di-outline.
  PDF yang teksnya sudah menjadi kurva ditolak dengan pesan yang jelas.
- **Teks standar** disimpan di `quran_checker/data/quran_kemenag.json` (6.236 ayat, 604 halaman), jadi tetap offline.
  Sumbernya teks web Kemenag (quran.kemenag.go.id) lewat paket `quran-kemenag` 1.0.12 (lisensi ISC).
  **Sebelum dipakai sebagai rujukan final, cocokkan dulu dengan rilis resmi LPMQ.**
- **Surah/ayat dicari otomatis:** setiap halaman dicocokkan dengan potongan teks standar; di *Tampilan per halaman*
  tertulis isi halaman itu (mis. "QS Al-Ahzab (33):55–62").
- **Yang diperiksa:** huruf dan harakat (hilang/tambahan/berubah), tanda waqaf dan simbol (۞ ࣖ mim iqlab, dsb.),
  teks yang hilang atau terulang di antara halaman, nomor ayat, dan huruf yang keluar dari batas halaman.
- **Tahan perbedaan cara simpan PDF:** urutan baca terbalik dideteksi otomatis; hamzah/madda dibandingkan
  dalam bentuk terurai (أ = ا + ٔ); urutan harakat bertumpuk dan ligatur lam-alif dinormalkan;
  tanda waqaf dicocokkan lewat letaknya di halaman (toleransi beberapa huruf).
- **Karakter yang tidak terbaca** (font tanpa pemetaan Unicode yang benar) dilaporkan sebagai
  *Tidak terbaca (pemetaan font)* [Sedang] beserta teks standar di posisi itu, untuk dicek mata.
- **Tidak bisa** dibandingkan tanpa master PDF: diff visual, warna tajwid, header/ornamen. Baris judul surah
  dicatat [Rendah] dan tidak dibandingkan.
- Setelah edisi pertama lulus tashih, simpan PDF-nya sebagai master untuk cetak ulang (mode *PDF master*).
- Kecepatan: ±1 menit untuk 604 halaman.

## Cara kerja

PDF dari InDesign biasanya mengubah teks mushaf menjadi **kurva (outline)**, sehingga tidak ada teks
Unicode yang bisa dibaca. Aplikasi memilih mode secara otomatis:

| Mode | Kapan | Yang dibandingkan |
|---|---|---|
| **Vektor** | Teks sudah di-outline (seperti file contoh hal. 426) | Setiap bentuk (huruf, harakat, titik, tanda waqaf, penanda ayat) dijadikan "sidik bentuk" dari koordinat kurvanya. Font sama → bentuk sama → sidik sama, di posisi mana pun. |
| **Teks** | Semua halaman punya lapisan teks Arab | Karakter Unicode setelah normalisasi (ی→ي, ک→ك, angka Persia, urutan harakat kanonik, karakter tak kasatmata dibuang). ى dan ي **tidak** disamakan. |

Lapisan pemeriksaan:

1. **Diff utama (glyph/teks)**: urutan isi master vs naskah diselaraskan per baris lalu per token,
   tanpa memakai posisi absolut. Karena itu hasilnya tetap akurat walau ada *reflow*
   (baris/halaman bergeser). Laporannya berupa: *Hilang*, *Tambahan*, *Berubah*, *Warna berubah* (tajwid).
2. **Posisi bergeser** (mode vektor): harakat/tanda yang posisinya berubah relatif terhadap huruf di sekitarnya
   (mis. fathah turun ke posisi kasrah).
3. **Glyph terpotong** (mode vektor): bentuk yang keluar dari batas frame/clip sehingga tidak tercetak utuh,
   termasuk perubahan batas frame dibanding master.
4. **Struktur**: penanda ayat (jumlah, hilang/tambah/berubah, ganda). Di mode teks juga dicek
   nomor ayat berurutan, jumlah basmalah, tanda ۞ dan ۩.
5. **Elemen non-teks**: header, nomor halaman, nama surah/juz, ornamen, legenda tajwid.
6. **Diff visual** (pemeriksaan kedua): halaman dirender ke gambar dan dibandingkan piksel.
   Area beda yang belum dijelaskan temuan lain dilaporkan sebagai *Beda visual*.
   Derau render (tepi huruf bergeser sepersekian piksel, anti-aliasing) diabaikan: sebuah piksel baru dianggap beda
   bila warnanya tidak ada di sekitar posisi yang sama pada gambar lain (dicek dua arah), dan area beda harus
   minimal 6 piksel. Tanda sekecil fathah/titik yang hilang, bergeser ±1,5 pt, atau berubah warna tetap terdeteksi.

Keparahan: **Tinggi** = isi berubah/hilang/terpotong; **Sedang** = warna, posisi kecil, elemen non-teks, beda visual.

## Struktur kode

```
app.py                      UI Streamlit
quran_checker/
  extract.py                ekstraksi token (vektor & teks), deteksi frame, baris, penanda ayat
  normalize.py              normalisasi Unicode Arab
  align.py                  penyelarasan urutan (tahan reflow)
  diff_tokens.py            analisis: hilang/tambah/berubah, warna, posisi, terpotong, dekorasi
  structure.py              nomor ayat, basmalah, hizb/sajdah
  visual.py                 diff piksel
  compare.py                orkestrasi + ekstraksi paralel
  reference.py              mode teks standar Kemenag (tanpa master PDF)
  data/quran_kemenag.json   teks standar (offline)
  report.py                 crop berdampingan, laporan PDF
tests/                      pengujian (kasus sengaja salah)
```

## Pengujian

Klik **`Jalankan_Tes.bat`** (atau `python -m pytest -v`). Kasus yang diuji:

- **Mode vektor** (memodifikasi master hal. 426 langsung di level path PDF): hapus satu harakat,
  hapus satu huruf, ganti bentuk harakat, geser harakat 4 pt ke bawah, tukar tanda waqaf ج ↔ قلى,
  ubah warna tajwid, ganti angka penanda ayat 61 dengan angka 60, serta file "Ada Salah" asli dari tim.
  Ada juga kontrol: master vs master dan mutasi kosong tidak boleh menghasilkan temuan.
- **Mode teks** (PDF uji dibuat dari teks): ubah satu harakat, hapus satu huruf, tukar tanda waqaf,
  nomor ayat salah, huruf tambahan, dan kontrol tanpa perubahan.
- **Normalisasi**: varian ی/ک, urutan harakat bertumpuk, karakter tak kasatmata.
- **Diff visual**: geseran 0,15–0,3 pt dan halaman identik tidak boleh jadi temuan; tanda kecil hilang, titik hilang,
  tanda turun 1,5 pt, latar krem hilang, dan warna tajwid beda harus terdeteksi (100/150/200 dpi).
- **Teks standar** (PDF uji hal. 425–428 dibuat dari teks Kemenag dengan font Amiri Quran di `tests/fonts`, lisensi OFL):
  tanpa perubahan (tidak boleh ada temuan Tinggi, halaman dikenali sebagai 33:55–62), ubah satu harakat, hapus satu kata,
  baris hilang di antara halaman, nomor ayat salah, tanda waqaf ditukar, urutan halaman tertukar, dan naskah outline ditolak.

Tes mode vektor memakai `tests/data/master_426.pdf` dan `tests/data/naskah_426_salah.pdf`.
Untuk menguji halaman lain, ganti file itu dan sesuaikan koordinat di `tests/test_vector_mode.py`.

## Batasan yang perlu diketahui

- **Mode vektor tidak tahu nama huruf.** Temuan berbunyi "tanda kecil hitam berubah" atau "bentuk huruf hilang"
  disertai gambar master vs naskah, bukan "ي berubah jadi ى". Editor menilai dari gambarnya.
- **Nomor ayat di mode vektor dibandingkan dengan master per bentuk**, bukan dibaca sebagai angka.
  Kalau master sendiri salah nomor, kesalahan itu tidak terdeteksi. Mode teks memeriksa urutan nomor secara mandiri.
- **Mode teks bergantung pada pemetaan font ke Unicode.** Bila hasil ekstraksi mengandung karakter janggal,
  aplikasi menampilkan PERINGATAN di *Catatan pemeriksaan*.
- **Diff visual dilewati** bila halaman banyak bergeser (reflow); diff glyph tetap berjalan.
- **Kecepatan**: ekstraksi ±0,5 detik per halaman per inti CPU. Satu mushaf ±600 halaman (master + naskah)
  di komputer 8 inti ±2–4 menit, ditambah diff visual ±0,5 detik per halaman pada 150 dpi.
