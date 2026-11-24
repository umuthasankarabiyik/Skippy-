"""Çalışma / dinlenme geri sayım sayacı (petin kalk / otur modlarına bağlı).

Her mod geçişinde (elle ya da sayaç dolunca) o mod için ayarlanan süre baştan geri saymaya başlar.
Süre dolunca pet modu kendisi değiştirir. Kalk modu = ÇALIŞMA, otur modu = DİNLENME (oyun / mola).
Çalışma süresi dolunca Tamagotchi parasından (jeton) ödül verilir: her COIN_EVERY_S saniye için 1 jeton.
Süreler config'de saniye olarak tutulur: cd_stand_s, cd_sit_s (açık/kapalı: cd_on).
"""
import re
import time

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPen
from PyQt6.QtWidgets import QApplication

import hud

DEFAULT_STAND_S = 50 * 60   # kalk modu (ders çalışma)
DEFAULT_SIT_S = 10 * 60     # otur modu (oyun / dinlenme)
MIN_S, MAX_S = 60, 12 * 3600
COIN_EVERY_S = 10 * 60      # çalışma ödülü: her 10 dakika için 1 jeton (10 dakikadan kısaysa 0)

UNITS = (("saat", 3600), ("sa", 3600), ("s", 3600), ("h", 3600),
         ("dakika", 60), ("dak", 60), ("dk", 60), ("d", 60), ("m", 60),
         ("saniye", 1), ("sn", 1))


# ------------------------------------------------------------ Qt'siz mantık
def coins_for(secs):
    """Tamamlanan bir çalışma süresinin jeton ödülü: 50 dk -> 5, 25 dk -> 2, 1 sa 30 dk -> 9."""
    return int(secs) // COIN_EVERY_S


def parse_duration(text):
    """'45', '45 dk', '1:30', '1 saat 30 dk', '1.5 saat', '90m' -> saniye. Anlaşılmazsa None.
    Birimsiz sayı dakika sayılır. Sonuç 1 dakika ile 12 saat arasında olmalı."""
    t = text.lower().strip().replace(",", ".")
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", t)
    if m:
        secs = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)
    elif re.fullmatch(r"\d+(\.\d+)?", t):
        secs = float(t) * 60
    else:
        parts = re.findall(r"(\d+(?:\.\d+)?)\s*([a-zçğıöşü]+)", t)
        if not parts or re.sub(r"(\d+(?:\.\d+)?)\s*([a-zçğıöşü]+)|\s", "", t):
            return None
        secs = 0.0
        for num, unit in parts:
            mult = next((v for k, v in UNITS if unit == k), None)
            if mult is None:
                return None
            secs += float(num) * mult
    secs = int(round(secs))
    return secs if MIN_S <= secs <= MAX_S else None


def fmt_duration(secs):
    """3000 -> '50 dk', 5400 -> '1 sa 30 dk' (ayar menüsünde gösterim için)."""
    h, m = divmod(int(secs) // 60, 60)
    if h and m:
        return f"{h} sa {m} dk"
    return f"{h} sa" if h else f"{m} dk"


def fmt_clock(secs):
    """Ekrandaki geri sayım: 59:59 ya da 1:05:09."""
    secs = max(0, int(secs + 0.999))  # yukarı yuvarla: 0:00'ı gerçekten bittiğinde göster
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class Countdown:
    def __init__(self):
        self.end = 0.0
        self.total = 0

    def start(self, seconds, now=None):
        self.total = int(seconds)
        self.end = (now if now is not None else time.time()) + self.total

    def remaining(self, now=None):
        return max(0.0, self.end - (now if now is not None else time.time()))

    def expired(self, now=None):
        return self.end > 0 and self.remaining(now) <= 0


# ------------------------------------------------------------- ekran etiketi
STAND_COLOR, SIT_COLOR, WARN_COLOR = "#7DF0FF", "#FF6FD8", "#FFD84A"


def _mono(px):
    f = QFont("Monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    f.setBold(True)
    return f


class Pill(hud.HudWidget):
    """Pet'in başının üstündeki, HUD çerçeveli geri sayım etiketi: ">> ÇALIŞMA | 49:12 ////".
    Çerçeve ve yazı moda göre camgöbeği (çalışma) / pembe (dinlenme) / sarı (son dakika). Glitch ile açılıp kapanır."""
    H = 28

    def __init__(self):
        super().__init__()
        self.f_label, self.f_clock = _mono(10), _mono(15)
        self.mode, self.clock, self.color = "ÇALIŞMA", "00:00", STAND_COLOR
        self.inner_w, self.label_w = 100, 50
        self.set_text(self.mode, self.clock, self.color)

    def visual_height(self):
        """Çerçevenin görünen yüksekliği (pencere payları hariç)."""
        return self.H

    def set_text(self, mode, clock, color):
        self.mode, self.clock, self.color = mode, clock, color
        self.label_w = QFontMetrics(self.f_label).horizontalAdvance(mode)
        clock_w = QFontMetrics(self.f_clock).horizontalAdvance(clock)
        self.inner_w = 28 + self.label_w + 12 + clock_w + 40
        m = hud.MARGIN
        self.setFixedSize(int(self.inner_w) + 2 * m, self.H + 2 * m)
        self.update()

    def draw(self, p):
        m, w, h = hud.MARGIN, self.inner_w, self.H
        hud.paint_frame(p, m, m, w, h, self.color, 2)
        col = QColor(self.color)
        chevron = QPen(col, 1.6)
        chevron.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(chevron)
        for i in range(2):  # >> işaretleri
            x0 = m + 11 + i * 6
            p.drawLine(QPointF(x0, m + 9), QPointF(x0 + 3.5, m + 14))
            p.drawLine(QPointF(x0 + 3.5, m + 14), QPointF(x0, m + 19))
        fm = QFontMetrics(self.f_label)
        p.setFont(self.f_label)
        p.setPen(col)
        p.drawText(QPointF(m + 28, m + (h + fm.ascent() - fm.descent()) / 2), self.mode)
        sx = m + 28 + self.label_w + 6
        dim = QColor(col)
        dim.setAlpha(120)
        p.setPen(QPen(dim, 1))
        p.drawLine(QPointF(sx, m + 7), QPointF(sx, m + h - 7))
        fm2 = QFontMetrics(self.f_clock)
        p.setFont(self.f_clock)
        p.setPen(col)
        p.drawText(QPointF(sx + 6, m + (h + fm2.ascent() - fm2.descent()) / 2), self.clock)

    def follow(self, pet_x, pet_y, pet_px):
        """Pet'in başının hemen üstüne yerleşir (çerçeve ekran dışına taşmaz)."""
        scr = QApplication.primaryScreen().availableGeometry()
        m = hud.MARGIN
        x = pet_x + pet_px // 2 - self.width() // 2
        y = pet_y + 10 - self.height() + m
        x = max(scr.x() - m, min(x, scr.x() + scr.width() - self.width() + m))
        pt = QPoint(x, max(scr.y() - m, y))
        if pt != self.pos():
            self.move(pt)
