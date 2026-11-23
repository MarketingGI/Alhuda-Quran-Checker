"""Lisensi Alhuda Quran Checker: aktivasi per PC, token bertanda tangan Ed25519.

Hanya Kode PC (hash) + nama PC/pengguna yang dikirim ke server lisensi.
Tidak ada isi naskah atau PDF yang pernah dikirim.
"""
import base64, hashlib, json, os, socket, time, getpass
import urllib.request, urllib.error

SERVER = "https://alhuda-lisensi.netlify.app"
PUBLIC_KEY_B64 = "bpfmxwkwpLMyZ2CZlVY2orfrreuCITKplJ4LFpCd5l0="
GRACE_BACK = 86400  # toleransi jam mundur 1 hari


# ---------- Ed25519 verifikasi (RFC 8032, Python murni) ----------
_p = 2**255 - 19
_d = (-121665 * pow(121666, _p - 2, _p)) % _p
_q = 2**252 + 27742317777372353535851937790883648493
_I = pow(2, (_p - 1) // 4, _p)


def _inv(x): return pow(x, _p - 2, _p)


def _xrec(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_p + 3) // 8, _p)
    if (x * x - xx) % _p: x = (x * _I) % _p
    if x % 2: x = _p - x
    return x


_By = 4 * _inv(5)
_B = (_xrec(_By) % _p, _By % _p)


def _add(P, Q):
    x1, y1 = P; x2, y2 = Q
    t = _d * x1 * x2 * y1 * y2
    return ((x1 * y2 + x2 * y1) * _inv(1 + t) % _p, (y1 * y2 + x1 * x2) * _inv(1 - t) % _p)


def _mul(P, e):
    Q = (0, 1)
    while e:
        if e & 1: Q = _add(Q, P)
        P = _add(P, P); e >>= 1
    return Q


def _dec(s):
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _xrec(y)
    if x & 1 != (s[31] >> 7): x = _p - x
    P = (x, y)
    if (-P[0] * P[0] + P[1] * P[1] - 1 - _d * P[0] * P[0] * P[1] * P[1]) % _p:
        raise ValueError("titik tidak valid")
    return P


def _verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    try:
        if len(sig) != 64 or len(pub) != 32: return False
        R = _dec(sig[:32]); A = _dec(pub)
        S = int.from_bytes(sig[32:], "little")
        if S >= _q: return False
        h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _q
        return _mul(_B, S) == _add(R, _mul(A, h))
    except Exception:
        return False


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------- Kode PC ----------
def machine_id() -> str:
    parts = ["alhuda-v1"]
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                           0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        parts.append(winreg.QueryValueEx(k, "MachineGuid")[0])
        k2 = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        parts.append(winreg.QueryValueEx(k2, "ProcessorNameString")[0])
    except Exception:
        try:
            parts.append(open("/etc/machine-id").read().strip())
        except Exception:
            parts.append(socket.gethostname())
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def kode_pc(mid: str) -> str:
    return "-".join(mid[i:i + 4] for i in range(0, 20, 4)).upper()


# ---------- penyimpanan lokal ----------
def _dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "AlhudaQuranChecker")
    os.makedirs(d, exist_ok=True)
    return d


def _path(): return os.path.join(_dir(), "license.json")


def _load():
    try:
        return json.load(open(_path(), encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        json.dump(d, open(_path(), "w", encoding="utf-8"))
    except Exception:
        pass


# ---------- validasi token ----------
def token_status(token: str, mid: str, now: float | None = None):
    """-> (ok, alasan, sisa_hari)"""
    now = now or time.time()
    try:
        payload, sig = token.split(".")
        if not _verify(base64.b64decode(PUBLIC_KEY_B64), payload.encode(), _b64u(sig)):
            return False, "tanda tangan tidak valid", 0
        data = json.loads(_b64u(payload))
    except Exception:
        return False, "token rusak", 0
    if data.get("m") != mid: return False, "token milik PC lain", 0
    st = _load()
    if now < st.get("last_seen", 0) - GRACE_BACK:
        return False, "jam sistem mundur; sambungkan ke internet", 0
    if now > data["exp"]: return False, "masa berlaku habis; sambungkan ke internet", 0
    return True, "ok", int((data["exp"] - now) // 86400)


def _post(path, body, timeout=4):
    req = urllib.request.Request(SERVER + path, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def evaluate():
    """Hasil: dict(ok, status, pesan, kode, sisa_hari)"""
    mid = machine_id()
    out = {"ok": False, "status": "?", "pesan": "", "kode": kode_pc(mid), "sisa_hari": 0}
    online = None
    try:
        online = _post("/api/check", {"machine_id": mid})
        if online.get("status") == "unknown":
            online = _post("/api/request", {"machine_id": mid, "nama_pc": socket.gethostname(),
                                            "pengguna": getpass.getuser()})
    except Exception:
        online = None  # offline / server tak terjangkau

    st = _load()
    if online:
        s = online.get("status")
        out["status"] = s
        if s == "approved" and online.get("token"):
            st["token"] = online["token"]
        elif s in ("revoked", "pending"):
            st.pop("token", None)
            out["pesan"] = ("Lisensi PC ini dinonaktifkan oleh pemilik aplikasi." if s == "revoked"
                            else "Permintaan aktivasi sudah dikirim. Menunggu persetujuan pemilik.")
    now = time.time()
    tok = st.get("token")
    if tok:
        ok, why, days = token_status(tok, mid, now)
        out.update(ok=ok, sisa_hari=days)
        if ok:
            out["status"] = "approved"
            st["last_seen"] = max(st.get("last_seen", 0), now)
        elif not out["pesan"]:
            out["pesan"] = "Lisensi tidak valid: " + why
    elif not out["pesan"]:
        out["pesan"] = ("Tidak bisa menghubungi server lisensi. Sambungkan internet untuk aktivasi pertama."
                        if online is None else "Belum diaktifkan.")
    _save(st)
    return out
