# Lisensi aktivasi per PC

- `client/`: modul di aplikasi. `gate_app.py` -> `alhuda_gate` memeriksa lisensi lalu menjalankan `app.py` asli. Token berupa tanda tangan Ed25519 (diverifikasi dengan Python murni), berlaku 14 hari, diperpanjang otomatis saat online. Yang dikirim ke server hanya hash kode PC, nama PC, dan nama pengguna Windows.
- `server/`: Netlify Functions + Blobs. Endpoint `/api/request`, `/api/check`, `/api/admin`, halaman admin `/admin/`.

## Deploy server (akun Netlify sendiri)

Environment variable (jangan pernah di-commit):

| Nama | Isi |
|---|---|
| `ADMIN_PASSWORD` | password halaman admin |
| `LICENSE_PRIVATE_KEY` | kunci privat Ed25519 PKCS8 DER dalam base64 |

Kunci publik pasangannya ada di `client/alhuda_license.py` (`PUBLIC_KEY_B64`). Jika kunci diganti, ganti keduanya lalu bangun ulang installer.

```
cd licensing/server
npm install
npx netlify-cli deploy --prod --dir=public --functions=netlify/functions --site <SITE_ID>
```

Situs harus **Public** (tanpa login Netlify/password) agar PC lain bisa menghubunginya.
