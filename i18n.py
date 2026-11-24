"""Dil desteği (Türkçe / English).

Dil seçimi: SKIPPY_LANG ortam değişkeni > ~/.config/skippy/lang dosyası > "tr".
İngilizce modda Türkçe kaynak metinler i18n_en.EN tablosuyla çevrilir (menüler, paneller, oyunlar, replikler).
Tabloda olmayan metin olduğu gibi kalır. {isim} / {0} içeren anahtarlar desendir.
Türkçe modda hiçbir şey çevrilmez ve Qt'ye dokunulmaz."""
import os
import re
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "skippy" / "lang"


def _read():
    import sys
    if "--lang" in sys.argv:  # python3 pet.py --lang en
        try:
            v = sys.argv[sys.argv.index("--lang") + 1].lower()
            if v in ("tr", "en"):
                return v
        except IndexError:
            pass
    env = os.environ.get("SKIPPY_LANG", "").strip().lower()
    if env in ("tr", "en"):
        return env
    try:
        v = CONF.read_text().strip().lower()
        if v in ("tr", "en"):
            return v
    except OSError:
        pass
    loc = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").lower()
    return "tr" if loc.startswith("tr") or not loc else "en"  # ilk açılışta sistem diline göre


LANG = _read()


def lang():
    return LANG


def is_en():
    return LANG == "en"


def set_lang(code):
    """Seçimi kalıcı yazar (etkisi yeniden başlatınca görülür)."""
    global LANG
    LANG = "en" if code == "en" else "tr"
    try:
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text(LANG)
    except OSError:
        pass


_PH = re.compile(r"\{(\w+)\}")
_exact, _patterns, _cache = {}, [], {}
_WORDS = {}


def _load():
    if _exact or _patterns:
        return
    from i18n_en import EN
    for k, v in EN.items():
        if _PH.search(k):
            names, pos, regex = [], 0, ""
            for m in _PH.finditer(k):
                regex += re.escape(k[pos:m.start()]) + "(.+?)"
                names.append(m.group(1))
                pos = m.end()
            regex += re.escape(k[pos:])
            _patterns.append((re.compile("^" + regex + "$", re.S), names, v, len(k)))
        else:
            _exact[k] = v
    _patterns.sort(key=lambda p: -p[3])  # uzun / özgül desenler önce
    for k in ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
              "Çalışma", "Dinlenme", "ÇALIŞMA", "DİNLENME", "insan", "tokluk", "mutluluk", "enerji", "jeton"):
        if k in _exact:
            _WORDS[k] = _exact[k]
    _WORDS["jeton"] = "coins"


def _group(v):
    t = T(v)
    if t == v and _WORDS:
        t = re.sub(r"[^\W\d_]+", lambda m: _WORDS.get(m.group(0), m.group(0)), v)
    return t


def T(s):
    """Türkçe metni (İngilizce modda) çevirir; Türkçe modda ya da bulunamazsa aynen döner."""
    if LANG != "en" or not isinstance(s, str) or not s:
        return s
    r = _cache.get(s)
    if r is not None:
        return r
    _load()
    r = _exact.get(s)
    if r is None:
        for rx, names, tpl, _ in _patterns:
            m = rx.match(s)
            if m:
                vals = {n: _group(g) for n, g in zip(names, m.groups())}
                r = _PH.sub(lambda mm: vals.get(mm.group(1), mm.group(0)), tpl)
                break
    if r is None:
        r = s
    if len(_cache) > 3000:
        _cache.clear()
    _cache[s] = r
    return r


def install_qt():
    """İngilizce modda Qt sınıflarını, metin alan çağrıları çeviren alt sınıflarla değiştirir.
    pet.py'de PyQt6 adları içe aktarılmadan ÖNCE çağrılmalıdır."""
    if LANG != "en":
        return
    from PyQt6 import QtGui, QtWidgets

    def tr_args(a):
        return tuple(T(x) if isinstance(x, str) else x for x in a)

    def sub(mod, name, init_text=False, methods=(), statics=()):
        base = getattr(mod, name, None)
        if base is None:
            return
        ns = {}
        if init_text:
            def __init__(self, *a, **k):
                base.__init__(self, *tr_args(a), **k)
            ns["__init__"] = __init__
        for m in methods:
            def f(self, *a, _m=m, **k):
                return getattr(base, _m)(self, *tr_args(a), **k)
            ns[m] = f
        for m in statics:
            def g(parent=None, *a, _m=m, **k):
                return getattr(base, _m)(parent, *tr_args(a), **k)
            ns[m] = staticmethod(g)
        setattr(mod, name, type(name, (base,), ns))

    sub(QtWidgets, "QWidget", methods=("setWindowTitle", "setToolTip"))
    sub(QtWidgets, "QLabel", True, ("setText",))
    sub(QtWidgets, "QPushButton", True, ("setText",))
    sub(QtWidgets, "QCheckBox", True, ("setText",))
    sub(QtWidgets, "QLineEdit", False, ("setPlaceholderText",))
    sub(QtWidgets, "QPlainTextEdit", False, ("setPlaceholderText",))
    sub(QtWidgets, "QMenu", True, ("addMenu", "addAction", "setTitle"))
    sub(QtGui, "QAction", True, ("setText",))
    sub(QtGui, "QPainter", False, ("drawText",))
    sub(QtWidgets, "QInputDialog", False, statics=("getText", "getInt", "getDouble"))
    sub(QtWidgets, "QMessageBox", False, statics=("information", "question", "warning", "critical"))
