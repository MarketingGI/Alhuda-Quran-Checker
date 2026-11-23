from quran_checker.normalize import char_class, normalize_text


def test_farsi_yeh_and_keheh_disamakan():
    assert normalize_text("فی") == normalize_text("في")
    assert normalize_text("کتاب") == normalize_text("كتاب")


def test_alif_maqsurah_tidak_disamakan_dengan_ya():
    assert normalize_text("على") != normalize_text("علي")


def test_urutan_harakat_bertumpuk_kanonik():
    # syaddah + fathah vs fathah + syaddah -> sama setelah normalisasi
    assert normalize_text("نَّ") == normalize_text("نَّ")


def test_karakter_tak_kasatmata_dibuang():
    assert normalize_text("اللّٰ‍هِ‏") == normalize_text("اللّٰهِ")


def test_bentuk_presentasi_ke_huruf_dasar():
    assert normalize_text("ﺳ") == "س"  # ﺳ -> س


def test_harakat_tidak_dibuang():
    assert normalize_text("بِ") != normalize_text("بَ")


def test_golongan_karakter():
    assert char_class("َ") == "harakat"
    assert char_class("ۚ") == "tanda waqaf"
    assert char_class("ب") == "huruf"
    assert char_class("٢") == "angka"
