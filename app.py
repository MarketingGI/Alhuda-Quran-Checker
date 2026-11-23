"""Alhuda Quran Checker — antarmuka lokal (Streamlit).

Jalankan:  streamlit run app.py
Semua proses berjalan di komputer ini; tidak ada data yang dikirim ke internet.
"""
from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

import pymupdf as fitz
import streamlit as st

from quran_checker.compare import Options, compare_pdfs
from quran_checker.models import SEVERITY_ORDER
from quran_checker.reference import compare_with_reference
from quran_checker.report import SEV_RGB, build_report_pdf, page_with_boxes, side_by_side

st.set_page_config(page_title="Alhuda Quran Checker", page_icon="📖", layout="wide")

st.markdown(
    """
    <style>
    .ar {direction: rtl; unicode-bidi: isolate; font-family: 'Traditional Arabic','Amiri','Noto Naskh Arabic','Arial',serif; font-size: 1.6rem;}
    .sev {font-weight: 700; padding: 1px 8px; border-radius: 10px; color: white; font-size: .8rem;}
    .block-container {padding-top: 1.5rem;}
    .lbl {display: inline-block; font-weight: 700; font-size: .8rem; letter-spacing: .05em; color: white;
          padding: 2px 10px; border-radius: 4px; margin-bottom: 6px;}
    .lbl-m {background: #2f6fd6;}
    .lbl-n {background: #555;}
    </style>
    """,
    unsafe_allow_html=True,
)


def sev_badge(sev: str) -> str:
    r, g, b = SEV_RGB[sev]
    return f"<span class='sev' style='background:rgb({r},{g},{b})'>{sev}</span>"


FRAME_M = (47, 111, 214)  # bingkai biru = master
FRAME_N = (85, 85, 85)  # bingkai abu tua = naskah


def framed(img, color, w: int = 5):
    """Beri bingkai berwarna agar gambar master dan naskah tidak menyatu."""
    import cv2

    return cv2.copyMakeBorder(img, w, w, w, w, cv2.BORDER_CONSTANT, value=color)


def label(which: str, text: str | None = None) -> str:
    cls = "lbl-m" if which == "m" else "lbl-n"
    return f"<span class='lbl {cls}'>{text or ('MASTER' if which == 'm' else 'NASKAH')}</span>"


def show(slot, which: str, img, text: str | None = None):
    with slot.container(border=True):
        st.markdown(label(which, text), unsafe_allow_html=True)
        if img is None:
            st.info("Tidak ada pasangan di master.")
        else:
            st.image(framed(img, FRAME_M if which == "m" else FRAME_N), width="stretch")


# ------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Pengaturan")
    mode_label = st.selectbox(
        "Mode pembanding",
        ["Otomatis", "Teks (PDF dengan teks hidup)", "Vektor (teks sudah di-outline)"],
        help="Otomatis: pakai mode teks bila semua halaman punya lapisan teks Arab, selain itu mode vektor.",
    )
    do_visual = st.checkbox("Diff visual (pemeriksaan kedua)", value=True)
    dpi = st.select_slider("Resolusi diff visual (dpi)", options=[100, 150, 200, 300], value=150,
                           help="Makin tinggi makin teliti, tapi makin lambat.")
    do_deco = st.checkbox("Periksa elemen di luar area ayat (header, legenda, ornamen)", value=True)
    do_shift = st.checkbox("Periksa pergeseran posisi harakat/huruf", value=True)
    st.caption("Pengaturan di atas berlaku untuk sumber master *PDF master*. "
               "Mode teks standar Kemenag selalu membandingkan huruf, harakat, tanda waqaf, dan nomor ayat.")
    st.divider()
    st.caption("Pembanding bersifat deterministik (kode). Tidak ada AI yang menilai atau mengoreksi teks Al-Qur'an. "
               "Semua proses berjalan offline di komputer ini.")

st.title("📖 Alhuda Quran Checker")
SRC_PDF = "PDF master"
SRC_STD = "Teks standar Kemenag (belum ada master)"
source = st.radio(
    "Sumber master",
    [SRC_PDF, SRC_STD],
    horizontal=True,
    help="Teks standar Kemenag: untuk produk baru yang belum punya master. Naskah harus PDF dengan teks hidup "
         "(diekspor sebelum teks di-outline). Teks standar disimpan di komputer ini, jadi tetap offline.",
)
std_mode = source == SRC_STD

if std_mode:
    st.write("Unggah **naskah** (PDF yang teksnya belum di-outline), lalu tekan **Periksa**. "
             "Aplikasi mencari sendiri surah dan ayat di setiap halaman, lalu membandingkannya huruf demi huruf "
             "dengan teks standar Kemenag.")
    up_master = None
    up_naskah = st.file_uploader("Naskah yang dicek", type=["pdf"], key="naskah_std")
    go = st.button("Periksa", type="primary", disabled=not up_naskah, width="stretch")
else:
    st.write("Unggah **master** (rujukan yang benar) dan **naskah** yang akan dicek, lalu tekan **Bandingkan**.")
    c1, c2 = st.columns(2)
    with c1:
        up_master = st.file_uploader("Master (rujukan)", type=["pdf"], key="master")
    with c2:
        up_naskah = st.file_uploader("Naskah yang dicek", type=["pdf"], key="naskah")
    go = st.button("Bandingkan", type="primary", disabled=not (up_master and up_naskah), width="stretch")

if go:
    opts = Options(
        visual=do_visual,
        visual_dpi=dpi,
        decoration=do_deco,
        shifts=do_shift,
        force_mode={"Otomatis": None}.get(mode_label, "teks" if mode_label.startswith("Teks") else "vektor"),
    )
    mbytes = up_master.getvalue() if up_master else None
    nbytes = up_naskah.getvalue()
    bar = st.progress(0.0, text="Memulai…")
    try:
        cb = lambda f, m: bar.progress(min(1.0, f), text=m)
        result = compare_with_reference(nbytes, progress=cb) if std_mode else compare_pdfs(mbytes, nbytes, opts, progress=cb)
    except Exception as e:  # tampilkan error dengan jelas, jangan diam
        bar.empty()
        st.error(f"Gagal membandingkan: {e}")
        st.stop()
    bar.empty()
    st.session_state.update(
        result=result, mbytes=mbytes, nbytes=nbytes,
        mname=up_master.name if up_master else "Teks standar Kemenag (bawaan aplikasi)", nname=up_naskah.name, report=None,
    )

if "result" not in st.session_state:
    st.stop()

result = st.session_state["result"]
A = fitz.open(stream=st.session_state["mbytes"], filetype="pdf") if st.session_state["mbytes"] else None
STD = A is None
LM = "Teks standar" if STD else "Master"
B = fitz.open(stream=st.session_state["nbytes"], filetype="pdf")
F = result.findings

# ------------------------------------------------------------- ringkasan
st.divider()
sev = Counter(f.severity for f in F)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total temuan", len(F))
m2.metric("Tinggi", sev.get("Tinggi", 0))
m3.metric("Sedang", sev.get("Sedang", 0))
m4.metric("Rendah", sev.get("Rendah", 0))
with st.expander("Catatan pemeriksaan", expanded=False):
    for n in result.notes:
        st.write("• " + n)

col_dl, _ = st.columns([1, 3])
with col_dl:
    if st.session_state.get("report") is None:
        if st.button("Siapkan laporan PDF", width="stretch"):
            with st.spinner("Menyusun laporan…"):
                st.session_state["report"] = build_report_pdf(
                    st.session_state["mbytes"], st.session_state["nbytes"], result,
                    st.session_state["mname"], st.session_state["nname"],
                )
            st.rerun()
    else:
        st.download_button(
            "⬇️ Unduh laporan PDF",
            data=st.session_state["report"],
            file_name=f"Laporan_{Path(st.session_state['nname']).stem}.pdf",
            mime="application/pdf",
            width="stretch",
        )

if not F:
    st.success("Tidak ditemukan perbedaan antara teks standar dan naskah." if STD else "Tidak ditemukan perbedaan antara master dan naskah.")
    st.stop()

tab1, tab2 = st.tabs(["Daftar temuan", "Tampilan per halaman"])

with tab1:
    f1, f2 = st.columns(2)
    sel_sev = f1.multiselect("Keparahan", ["Tinggi", "Sedang", "Rendah"], default=["Tinggi", "Sedang", "Rendah"])
    cats = sorted({f.category for f in F})
    sel_cat = f2.multiselect("Kategori", cats, default=cats)
    shown = [f for f in F if f.severity in sel_sev and f.category in sel_cat]
    shown.sort(key=lambda f: (f.page, SEVERITY_ORDER[f.severity]))
    st.caption(f"Menampilkan {len(shown)} dari {len(F)} temuan. "
               + ("Kotak = posisi di naskah; [QS surah:ayat] = letaknya di teks standar." if STD
                  else "Kotak biru = posisi di master, kotak merah/oranye = posisi di naskah."))
    for f in shown:
        head = f"#{f.id} · Hal. {f.page + 1} · {f.category}"
        with st.expander(f"{head}  [{f.severity}]", expanded=len(shown) <= 10):
            st.markdown(f"{sev_badge(f.severity)} &nbsp; {html.escape(f.message)}", unsafe_allow_html=True)
            if f.detail.get("master") or f.detail.get("naskah"):
                st.markdown(
                    f"Naskah: <span class='ar'>{html.escape(''.join(f.detail.get('naskah', [])) or '-')}</span>"
                    f" &nbsp;&nbsp; {LM}: <span class='ar'>{html.escape(''.join(f.detail.get('master', [])) or '-')}</span>",
                    unsafe_allow_html=True,
                )
            mimg, nimg = side_by_side(A, B, f, dpi=200)
            wide = nimg.shape[1] / nimg.shape[0] > 3
            if STD:
                show(st, "n", nimg)
            elif wide:
                show(st, "n", nimg)
                show(st, "m", mimg)
            else:
                # naskah di kiri, master di kanan
                cn, cm = st.columns(2, gap="large")
                show(cn, "n", nimg)
                show(cm, "m", mimg)

with tab2:
    pages_with = sorted({f.page for f in F})
    pno = st.selectbox(
        "Halaman naskah",
        list(range(B.page_count)),
        index=pages_with[0] if pages_with else 0,
        format_func=lambda i: f"Hal. {i + 1}" + (f"  ({sum(1 for f in F if f.page == i)} temuan)" if i in pages_with else ""),
    )
    if STD:
        span = next((pi.note for pi in result.naskah_pages if pi.index == pno), "")
        if span:
            st.caption(f"Isi halaman ini menurut teks standar: {span}")
        cb = st
    else:
        cb, ca = st.columns(2, gap="large")  # naskah kiri, master kanan
        if pno < A.page_count:
            mf = [f for f in F if f.master_page == pno]
            # kotak di master memakai posisi master
            from dataclasses import replace

            show(ca, "m", page_with_boxes(A, pno, [replace(f, page=pno, rect=f.master_rect, severity="Rendah") for f in mf if f.master_rect]))
    show(cb, "n", page_with_boxes(B, pno, F), "NASKAH (nomor = nomor temuan)")
