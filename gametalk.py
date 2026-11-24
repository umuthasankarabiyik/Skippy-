"""Oyun sohbeti: seçtiğin bir oyun açıkken fareyi basılı tuttuğunda Skippy düşmanlara laf sokar.

- Hangi oyunlarda konuşacağı bir beyaz liste ile belirlenir (Minecraft'ta köylülere küfretmesin diye).
  Liste girdileri aktif pencerenin sınıf adı / başlığı / süreç adıyla eşleşir (küçük-büyük harf fark etmez).
- Aktif pencere ve fare düğmesi X11 (XWayland dahil) üzerinden libX11 ile okunur; ek paket gerekmez.
  Saf Wayland pencerelerinde algılama çalışmaz (Steam / Proton oyunları normalde XWayland'dir).
- Konuşma satırları lines.py'de (GAME_TAUNTS); bu modül Qt'den bağımsızdır."""
import ctypes
import ctypes.util
import os
import random
import time

DEFAULTS = {"enabled": True, "games": [], "hold_ms": 450, "cooldown_s": 8, "clicks": 4}
CLICK_WINDOW_S = 1.2  # bu sürede "clicks" kadar tık = abanarak ateş (yarı otomatik silahlar)
BUTTON1 = 1 << 8


def settings(cfg):
    g = cfg.setdefault("gametalk", {})
    for k, v in DEFAULTS.items():
        g.setdefault(k, list(v) if isinstance(v, list) else v)
    return g


class X11:
    """libX11 üzerinden: aktif pencere bilgisi ve fare düğmesi durumu."""

    def __init__(self):
        self.ok = False
        self.error = ""
        try:
            name = ctypes.util.find_library("X11") or "libX11.so.6"
            self.x = ctypes.CDLL(name)
            x = self.x
            x.XOpenDisplay.restype = ctypes.c_void_p
            x.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x.XDefaultRootWindow.restype = ctypes.c_ulong
            x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x.XInternAtom.restype = ctypes.c_ulong
            x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            x.XGetWindowProperty.restype = ctypes.c_int
            x.XGetWindowProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
            x.XFree.argtypes = [ctypes.c_void_p]
            x.XQueryPointer.restype = ctypes.c_int
            x.XQueryPointer.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint)]
            # Xlib hataları (kapanmış pencere vb.) uygulamayı kapatmasın
            self._handler_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
            self._handler = self._handler_t(lambda d, e: 0)
            x.XSetErrorHandler.argtypes = [self._handler_t]
            x.XSetErrorHandler(self._handler)
            self.d = x.XOpenDisplay(None)
            if not self.d:
                self.error = "X sunucusuna bağlanılamadı"
                return
            self.root = x.XDefaultRootWindow(self.d)
            self.atoms = {n: x.XInternAtom(self.d, n.encode(), 0) for n in
                          ("_NET_ACTIVE_WINDOW", "WM_CLASS", "_NET_WM_NAME", "WM_NAME", "_NET_WM_PID", "UTF8_STRING", "STRING")}
            self.ok = True
        except Exception as e:  # libX11 yok vb.
            self.error = str(e)

    def _prop(self, win, name, req_type=0, length=256):
        x, a = self.x, self.atoms
        at, fmt, n, rest = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        st = x.XGetWindowProperty(self.d, win, a[name], 0, length, 0, req_type, ctypes.byref(at), ctypes.byref(fmt),
                                  ctypes.byref(n), ctypes.byref(rest), ctypes.byref(data))
        if st != 0 or not data or n.value == 0:
            return None
        try:
            if fmt.value == 32:
                return [ctypes.cast(data, ctypes.POINTER(ctypes.c_long))[i] for i in range(n.value)]
            if fmt.value == 8:
                return bytes(bytearray(data[i] for i in range(n.value)))
        finally:
            x.XFree(data)
        return None

    def active_window(self):
        if not self.ok:
            return None
        v = self._prop(self.root, "_NET_ACTIVE_WINDOW", 0, 1)
        return v[0] if v and v[0] else None

    def info(self, win=None):
        """-> {'class': [..], 'title': str, 'proc': str} ya da None."""
        if not self.ok:
            return None
        win = win or self.active_window()
        if not win:
            return None
        cls = self._prop(win, "WM_CLASS") or b""
        title = self._prop(win, "_NET_WM_NAME", self.atoms["UTF8_STRING"]) or self._prop(win, "WM_NAME") or b""
        pid = self._prop(win, "_NET_WM_PID", 0, 1)
        proc = ""
        if pid:
            try:
                with open(f"/proc/{pid[0]}/comm") as f:
                    proc = f.read().strip()
            except OSError:
                pass
        return {"class": [c for c in cls.decode("utf-8", "ignore").split("\0") if c],
                "title": title.decode("utf-8", "ignore"), "proc": proc}

    def button1(self):
        if not self.ok:
            return False
        r, c = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = (ctypes.c_int() for _ in range(4))
        m = ctypes.c_uint()
        self.x.XQueryPointer(self.d, self.root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx), ctypes.byref(ry),
                             ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m))
        return bool(m.value & BUTTON1)


def matches(info, games):
    """Aktif pencere beyaz listedeki bir girdiyle eşleşiyor mu? Eşleşen girdiyi döndürür."""
    if not info or not games:
        return None
    hay = [s.lower() for s in info["class"] + [info["title"], info["proc"]] if s]
    for g in games:
        g = g.strip().lower()
        if g and any(g in h for h in hay):
            return g
    return None


def label(info):
    """Listeye eklenecek kısa ad: sınıf adı (yoksa süreç adı)."""
    if not info:
        return ""
    return (info["class"][-1] if info["class"] else info["proc"] or info["title"])[:40].lower()


class Hold:
    """Fare düğmesine göre ne zaman laf atılacağına karar verir (Qt'siz, zamanı dışarıdan alır).
    İki durum tetikler: (1) düğme hold_ms'den uzun basılı tutuldu (otomatik silah / makro),
    (2) CLICK_WINDOW_S içinde `clicks` kadar hızlı tık (tek basışta çalışan silahlara abanmak)."""

    def __init__(self, hold_ms=450, cooldown_s=8, clicks=4, rng=random):
        self.hold_ms, self.cooldown_s, self.clicks, self.rng = hold_ms, cooldown_s, clicks, rng
        self.since = None
        self.prev = False
        self.taps = []
        self.next_ok = 0.0

    def update(self, pressed, now):
        """Basılı mı? -> True ise şimdi bir satır söyle."""
        if pressed and not self.prev:  # yeni tık
            self.taps = [t for t in self.taps if now - t <= CLICK_WINDOW_S] + [now]
        self.prev = pressed
        if not pressed:
            self.since = None
        elif self.since is None:
            self.since = now
        spam = self.clicks > 0 and len([t for t in self.taps if now - t <= CLICK_WINDOW_S]) >= self.clicks
        held = (now - self.since) if self.since is not None else 0.0
        if not (spam or (pressed and held * 1000 >= self.hold_ms)) or now < self.next_ok:
            return False
        cool = self.cooldown_s * (0.5 if held > 3.0 else 1.0)  # uzun süre sürekli ateşte daha sık
        self.next_ok = now + cool * self.rng.uniform(0.75, 1.25)
        self.taps = []
        return True


class Picker:
    """Aynı satırı art arda tekrarlamadan seçer."""

    def __init__(self, rng=random):
        self.rng, self.last = rng, set()

    def pick(self, pool):
        left = [x for x in pool if x not in self.last] or list(pool)
        c = self.rng.choice(left)
        self.last.add(c)
        if len(self.last) > max(1, len(pool) // 2):
            self.last.pop()
        return c
