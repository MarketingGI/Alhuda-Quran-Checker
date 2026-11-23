import os, runpy
import streamlit as st
import alhuda_license as lic

_here = os.path.dirname(os.path.abspath(__file__))


def main():
    if "_lic" not in st.session_state:
        st.session_state["_lic"] = lic.evaluate()
    res = st.session_state["_lic"]
    if not res["ok"]:
        st.set_page_config(page_title="Aktivasi - Alhuda Quran Checker", page_icon="🔒")
        st.title("🔒 Alhuda Quran Checker")
        st.warning(res["pesan"] or "Aplikasi belum diaktifkan.")
        st.write("Kirim **Kode PC** ini ke pemilik aplikasi untuk meminta izin:")
        st.code(res["kode"])
        st.caption("Hanya kode ini, nama PC, dan nama pengguna Windows yang dikirim ke server lisensi. "
                   "Isi naskah/PDF tidak pernah dikirim.")
        if st.button("Cek ulang"):
            del st.session_state["_lic"]
            st.rerun()
        st.stop()
    runpy.run_path(os.path.join(_here, "app.pyc"), run_name="__main__")
