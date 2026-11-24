"""Neon Şehir — idle şehir kurucu mini oyunu (Tamagotchi modu).

Bu oyunda jeton KAZANILMAZ; tek amacı jetonları harcayabileceğin bir yer olmak. Bina dikersin, yükseltirsin, yıkarsın.
Yıkınca jeton iadesi yoktur (iade de bir kazanç olurdu). Ölüm / bitiş ekranı yok; jetonun olduğu sürece sonsuza dek sürer.
Şehir cfg["city"] içinde saklanır: {"cells": {"x,y": [anahtar, seviye]}, "spent": harcanan toplam jeton}.
"""
import math
import random
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import hud

TITLE, SUBTITLE = "Neon Şehir", "Idle Şehir Kurucu"
GRID = 7
MAX_LEVEL = 5
TW, TH = 76, 38  # bir karenin izometrik genişlik / yüksekliği

# anahtar: (ad, simge, taban fiyat, ana renk, açıklama)
BUILDINGS = {
    "neon": ("Neon Tabela", "🪧", 5, "#FF4FD8", "Ucuz ama şehre ruh katar."),
    "apartman": ("Apartman", "🏢", 10, "#4FE3FF", "Sıradan bir kule blok."),
    "vinc": ("Vinç", "🏗", 14, "#FFB020", "Şehir hep inşaat halinde görünür."),
    "drone": ("Drone İstasyonu", "🛸", 18, "#5CFF9D", "Başının üstünde uçuşan dronlar."),
    "hologram": ("Hologram Reklam", "🔮", 24, "#B070FF", "Kimsenin almayacağı şeyleri satar."),
    "fabrika": ("Robot Fabrikası", "🏭", 30, "#FF7A3D", "Dumanı tüten bir üretim hattı."),
    "reaktor": ("Füzyon Reaktörü", "⚛", 36, "#7D5CFF", "Şehrin yapay kalbi."),
    "gokdelen": ("Gökdelen", "🌆", 45, "#FF3B5C", "Bulutları delen bir kule."),
}

LINES = {
    "build": ["Bir bina daha. Jetonların nereye gittiği belli.", "Güzel yer seçtin. İdare eder.",
              "İnşaat tamam. Sorumluluk almıyorum.", "Şehir büyüyor, cüzdan küçülüyor."],
    "upgrade": ["Yükseltme tamam. Daha parlak, daha pahalı.", "Seviye atladı. Faturayı ben kesmiyorum.",
                "Daha yüksek, daha neon, daha boş cüzdan."],
    "demolish": ["Yıkıldı. İade yok, kusura bakma.", "Moloz oldu. Estetik kararmış.", "Ve bir bina daha tarihe karıştı."],
    "broke": ["Jeton bitti. Şehir olduğu gibi kalacak.", "Cüzdan boş. Şehri izlemek bedava."],
}


# ------------------------------------------------------------ Qt'siz mantık
def build_cost(key):
    return BUILDINGS[key][2]


def upgrade_cost(key, level):
    """Mevcut seviyeden bir üst seviyeye: taban fiyatın %60'ı x seviye. Son seviyede None."""
    if level >= MAX_LEVEL:
        return None
    return max(1, int(BUILDINGS[key][2] * 0.6 * level + 0.5))


def total_value(key, level):
    """Bir binaya şimdiye kadar yatırılan toplam jeton (kuruluş + yükseltmeler)."""
    return build_cost(key) + sum(upgrade_cost(key, lv) for lv in range(1, level))


def iso_to_screen(gx, gy, ox, oy):
    """Karenin üst köşesinin ekran konumu."""
    return ox + (gx - gy) * TW / 2, oy + (gx + gy) * TH / 2


def screen_to_cell(x, y, ox, oy):
    """Ekran noktası -> (gx, gy) ya da ızgara dışındaysa None."""
    a = (y - oy) / (TH / 2)
    b = (x - ox) / (TW / 2)
    gx, gy = math.floor((a + b) / 2), math.floor((a - b) / 2)
    return (gx, gy) if 0 <= gx < GRID and 0 <= gy < GRID else None


class City:
    def __init__(self, cfg, wallet, save):
        """wallet: {"coins": n} sözlüğü (Tamagotchi'nin cüzdanı); save: kayıt fonksiyonu."""
        self.wallet, self.save = wallet, save
        c = cfg.setdefault("city", {})
        c.setdefault("cells", {})
        c.setdefault("spent", 0)
        self.c = c
        self.cells = {}
        for k, v in c["cells"].items():  # bozuk kaydı ayıkla
            try:
                x, y = map(int, k.split(","))
                key, lv = v
                if key in BUILDINGS and 0 <= x < GRID and 0 <= y < GRID:
                    self.cells[(x, y)] = [key, max(1, min(MAX_LEVEL, int(lv)))]
            except (ValueError, TypeError):
                continue

    def _store(self):
        self.c["cells"] = {f"{x},{y}": [k, lv] for (x, y), (k, lv) in self.cells.items()}
        self.save()

    def _pay(self, cost):
        self.wallet["coins"] -= cost
        self.c["spent"] += cost

    @property
    def spent(self):
        return self.c["spent"]

    def build(self, cell, key):
        """(başarılı mı, mesaj). Dolu kareye dikilmez; jeton yetmezse harcanmaz."""
        if key not in BUILDINGS:
            return False, "Önce soldaki listeden bir bina seç."
        if cell in self.cells:
            return False, "Burası dolu. Önce yık ya da yükselt."
        cost = build_cost(key)
        if self.wallet["coins"] < cost:
            return False, f"{BUILDINGS[key][0]} için {cost} jeton lazım, cebinde {self.wallet['coins']} var."
        self._pay(cost)
        self.cells[cell] = [key, 1]
        self._store()
        return True, f"{BUILDINGS[key][0]} dikildi (-{cost})."

    def upgrade(self, cell):
        b = self.cells.get(cell)
        if b is None:
            return False, "Burada yükseltilecek bir bina yok."
        key, lv = b
        cost = upgrade_cost(key, lv)
        if cost is None:
            return False, f"{BUILDINGS[key][0]} zaten son seviyede."
        if self.wallet["coins"] < cost:
            return False, f"Yükseltme {cost} jeton, cebinde {self.wallet['coins']} var."
        self._pay(cost)
        b[1] = lv + 1
        self._store()
        return True, f"{BUILDINGS[key][0]} Sv.{lv + 1} oldu (-{cost})."

    def demolish(self, cell):
        b = self.cells.pop(cell, None)
        if b is None:
            return False, "Burada yıkılacak bir şey yok."
        self._store()
        return True, f"{BUILDINGS[b[0]][0]} yıkıldı. İade yok."

    def info(self, cell):
        b = self.cells.get(cell)
        if b is None:
            return "Boş arsa"
        key, lv = b
        up = upgrade_cost(key, lv)
        return f"{BUILDINGS[key][0]} · Sv.{lv}/{MAX_LEVEL} · " + (f"yükseltme {up} jeton" if up else "son seviye")


# ------------------------------------------------------------------ çizim
def _c(hexcol, a=255, mul=1.0):
    col = QColor(hexcol)
    return QColor(min(255, int(col.red() * mul)), min(255, int(col.green() * mul)), min(255, int(col.blue() * mul)), a)


def _poly(*pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def box(p, cx, cy, s, h, color, neon=None, lift=0.0):
    """Karenin merkezi (cx, cy) üzerinde, ayak izi s (0-1) ve yüksekliği h olan izometrik kutu.
    Döndürür: üst yüzün merkezi ve sağ/sol alt kenar uçları (pencereler için)."""
    hw, hh = TW / 2 * s, TH / 2 * s
    cy -= lift
    L, B, R, T = (cx - hw, cy), (cx, cy + hh), (cx + hw, cy), (cx, cy - hh)
    up = lambda pt: (pt[0], pt[1] - h)
    Lu, Bu, Ru, Tu = up(L), up(B), up(R), up(T)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color, mul=0.38))
    p.drawPolygon(_poly(L, B, Bu, Lu))
    p.setBrush(_c(color, mul=0.62))
    p.drawPolygon(_poly(B, R, Ru, Bu))
    p.setBrush(_c(color, mul=0.9))
    p.drawPolygon(_poly(Tu, Ru, Bu, Lu))
    if neon:
        p.setPen(QPen(_c(neon), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(_poly(Tu, Ru, Bu, Lu))
        p.drawLine(QPointF(*Lu), QPointF(*L))
        p.drawLine(QPointF(*Bu), QPointF(*B))
        p.drawLine(QPointF(*Ru), QPointF(*R))
    return (cx, cy - h), (L, B), (B, R)


def windows(p, a, b, h, rows, cols, seed, t, color):
    """a->b alt kenarı olan yüzün üzerine yanıp sönen pencereler."""
    for j in range(rows):
        for i in range(cols):
            if (seed + i * 3 + j * 5) % 4 == 0:
                continue
            if (int(t * 1.3) + seed + i * j) % 13 == 0:  # ara sıra sönüp yanan pencere
                continue
            u, v = (i + 0.5) / cols, (j + 0.5) / rows
            x = a[0] + (b[0] - a[0]) * u
            y = a[1] + (b[1] - a[1]) * u - h * v
            p.fillRect(QRectF(x - 1.5, y - 2, 3, 3.5), _c(color, 230))


def glow(p, x, y, r, color, a=110):
    g = QColor(color)
    for k in (3, 2, 1):
        g.setAlpha(a // (k + 1))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x, y), r * k * 0.7, r * k * 0.7)


def draw_building(p, key, lv, cx, cy, t, seed):
    """Karenin ZEMİN merkezi (cx, cy). Seviye arttıkça bina büyür, ışıklar çoğalır."""
    col = BUILDINGS[key][3]
    blink = 0.5 + 0.5 * math.sin(t * 3 + seed)
    if key == "apartman":
        h = 16 + 11 * lv
        top, left, right = box(p, cx, cy, 0.62, h, "#2A4A66", col)
        windows(p, right[0], right[1], h, 2 + lv, 3, seed, t, "#BFF6FF")
        windows(p, left[0], left[1], h, 2 + lv, 2, seed + 1, t, "#7FD8FF")
    elif key == "gokdelen":
        h = 36 + 17 * lv
        top, left, right = box(p, cx, cy, 0.58, h, "#3B2433", col)
        windows(p, right[0], right[1], h, 4 + 2 * lv, 4, seed, t, "#FFD0D8")
        windows(p, left[0], left[1], h, 4 + 2 * lv, 3, seed + 2, t, "#FF8FA3")
        t2, _, _ = box(p, top[0], top[1] + TH * 0.0, 0.34, 10 + 3 * lv, "#4A2A3C", col)
        p.setPen(QPen(_c("#DDDDDD"), 1.2))
        p.drawLine(QPointF(t2[0], t2[1]), QPointF(t2[0], t2[1] - 16))
        glow(p, t2[0], t2[1] - 16, 3.5, "#FF2040", int(150 * blink))
    elif key == "neon":
        h = 14 + 6 * lv
        p.setPen(QPen(_c("#888899"), 2))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy - h))
        flick = 1.0 if (int(t * 6) + seed) % 17 else 0.35  # ara sıra tabela cızırdar
        w, ph = 10 + 2 * lv, 7 + lv
        sign = QRectF(cx - w / 2, cy - h - ph, w, ph)
        glow(p, cx, cy - h - ph / 2, w * 0.8, col, int(120 * flick))
        p.setPen(QPen(_c(col, int(255 * flick)), 1.6))
        p.setBrush(_c("#200820"))
        p.drawRect(sign)
        p.setPen(QPen(_c("#FFFFFF", int(230 * flick)), 1))
        p.drawLine(QPointF(cx - w / 2 + 2, cy - h - ph / 2), QPointF(cx + w / 2 - 2, cy - h - ph / 2))
    elif key == "vinc":
        mast = 40 + 11 * lv
        box(p, cx, cy, 0.34, 6, "#5A4A20", col)
        p.setPen(QPen(_c(col), 2.2))
        p.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy - mast))
        ang = t * 0.55 + seed
        jx, jy = math.cos(ang) * (16 + 3 * lv), math.sin(ang) * (16 + 3 * lv) * 0.5
        back = (-jx * 0.3, -jy * 0.3)
        top = (cx, cy - mast)
        p.setPen(QPen(_c(col), 2))
        p.drawLine(QPointF(top[0] + back[0], top[1] + back[1]), QPointF(top[0] + jx, top[1] + jy))
        hook_len = 10 + 4 * math.sin(t * 1.3 + seed)
        p.setPen(QPen(_c("#DDDDDD"), 1))
        p.drawLine(QPointF(top[0] + jx * 0.8, top[1] + jy * 0.8),
                   QPointF(top[0] + jx * 0.8, top[1] + jy * 0.8 + hook_len))
        p.fillRect(QRectF(top[0] + jx * 0.8 - 2.5, top[1] + jy * 0.8 + hook_len, 5, 4), _c(col))
        glow(p, top[0], top[1] - 2, 3, "#FF3030", int(160 * blink))
    elif key == "drone":
        box(p, cx, cy, 0.78, 3, "#1E4A36", col)
        p.setPen(QPen(_c(col, 200), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy - 3), TW * 0.2, TH * 0.2)
        for i in range(lv):  # her seviye bir drone daha
            a = t * (0.9 + 0.15 * i) + i * 2.1 + seed
            dx, dy = math.cos(a) * (TW * 0.3 + 6 * i), math.sin(a) * (TH * 0.3 + 3 * i)
            z = 14 + 6 * i + 3 * math.sin(t * 2 + i)
            x, y = cx + dx, cy - z + dy
            glow(p, x, y, 3, col, 120)
            p.fillRect(QRectF(x - 2.5, y - 1.5, 5, 3), _c("#E8FFF0"))
    elif key == "hologram":
        box(p, cx, cy, 0.5, 4, "#2E2050", col)
        bob = 3 * math.sin(t * 1.8 + seed)
        s = 10 + 4 * lv
        y0 = cy - 14 - s - bob
        grad = QLinearGradient(cx, y0 - s, cx, y0 + s)
        grad.setColorAt(0, _c(col, 190))
        grad.setColorAt(1, _c(col, 40))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(_c(col, 230), 1.3))
        p.drawPolygon(_poly((cx, y0 - s), (cx + s * 0.7, y0), (cx, y0 + s), (cx - s * 0.7, y0)))
        p.setPen(QPen(_c("#FFFFFF", 90), 1))
        for k in range(-2, 3):  # tarama çizgileri
            yy = y0 + k * s * 0.3
            p.drawLine(QPointF(cx - s * 0.5, yy), QPointF(cx + s * 0.5, yy))
        p.setPen(QPen(_c(col, 70), 1))
        p.drawLine(QPointF(cx, cy - 4), QPointF(cx, y0 + s))
    elif key == "fabrika":
        h = 12 + 4 * lv
        top, left, right = box(p, cx, cy, 0.82, h, "#4A3326", col)
        windows(p, right[0], right[1], h, 1 + lv // 2, 5, seed, t, "#FFC080")
        for i in range(1 + (lv + 1) // 2):  # bacalar
            bx = cx - 12 + i * 12
            by = cy - h - 2
            p.fillRect(QRectF(bx - 3, by - 14, 6, 14), _c("#3A2A24"))
            p.setPen(QPen(_c(col), 1))
            p.drawLine(QPointF(bx - 3, by - 14), QPointF(bx + 3, by - 14))
            for k in range(3):  # duman
                ph = (t * 0.5 + k / 3 + i * 0.37) % 1.0
                glow(p, bx + 6 * ph + math.sin(t + k) * 2, by - 14 - 28 * ph, 2 + 4 * ph, "#9A9AAA", int(110 * (1 - ph)))
    elif key == "reaktor":
        r = TW * 0.2 + 1.5 * lv
        hh = 14 + 6 * lv
        pulse = 0.6 + 0.4 * math.sin(t * 2.5 + seed)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c("#2A2050"))
        p.drawEllipse(QPointF(cx, cy), r, r * 0.5)
        p.drawRect(QRectF(cx - r, cy - hh, 2 * r, hh))
        p.setBrush(_c("#4A3A8A"))
        p.drawEllipse(QPointF(cx, cy - hh), r, r * 0.5)
        glow(p, cx, cy - hh, r * 0.8, col, int(190 * pulse))
        p.setBrush(_c("#E8E0FF", int(150 + 100 * pulse)))
        p.drawEllipse(QPointF(cx, cy - hh), r * 0.45, r * 0.22)
        p.setPen(QPen(_c(col, 220), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(1, lv + 1):  # seviye başına bir halka
            yy = cy - hh * k / (lv + 1)
            p.drawEllipse(QPointF(cx, yy), r, r * 0.5)
    # seviye noktaları (zeminde, karenin ön köşesinde)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(lv):
        p.setBrush(_c(col))
        p.drawEllipse(QPointF(cx - (lv - 1) * 3 + i * 6, cy + TH * 0.38), 1.8, 1.8)


# ------------------------------------------------------------------ pencere
CANVAS_W, CANVAS_H = 600, 440
OX, OY = CANVAS_W // 2, 128  # ızgaranın üst köşesi
STYLE = """
QWidget#city { background:#0B0A16; }
QPushButton { background:#16122A; color:#9FE8FF; border:1px solid #3A2A6A; padding:5px 6px; font-size:11px; }
QPushButton:hover { border-color:#FF4F9A; }
QPushButton:checked { background:#2A1030; color:#FFE0F4; border:1px solid #FF4F9A; }
QLabel { color:#9FE8FF; font-size:12px; }
"""


class CityView(QWidget):
    """İzometrik şehir tuvali: fare ile kare seçilir, seçili araç o kareye uygulanır."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.hover = None
        self.t0 = time.perf_counter()
        self.setFixedSize(CANVAS_W, CANVAS_H)
        self.setMouseTracking(True)
        rnd = random.Random(7)
        self.far = [(rnd.randint(0, CANVAS_W), rnd.randint(30, 110), rnd.randint(14, 34)) for _ in range(26)]
        self.stars = [(rnd.randint(0, CANVAS_W), rnd.randint(0, 90), rnd.random()) for _ in range(40)]

    def mouseMoveEvent(self, e):
        c = screen_to_cell(e.position().x(), e.position().y(), OX, OY)
        if c != self.hover:
            self.hover = c
            self.win.on_hover(c)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.win.on_hover(None)
        self.update()

    def mousePressEvent(self, e):
        c = screen_to_cell(e.position().x(), e.position().y(), OX, OY)
        if c is not None and e.button() == Qt.MouseButton.LeftButton:
            self.win.on_click(c)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = time.perf_counter() - self.t0
        g = QLinearGradient(0, 0, 0, CANVAS_H)
        g.setColorAt(0, QColor("#0A0420"))
        g.setColorAt(0.45, QColor("#2A0A3A"))
        g.setColorAt(1, QColor("#0B0A16"))
        p.fillRect(self.rect(), g)
        for x, y, ph in self.stars:
            p.fillRect(QRectF(x, y, 1.5, 1.5), QColor(255, 255, 255, int(60 + 120 * abs(math.sin(t * 0.7 + ph * 6)))))
        for x, y, w in self.far:  # uzak siluet
            p.fillRect(QRectF(x, 130 - y * 0.5, w, y * 0.5 + 100), QColor(24, 12, 44))
        # zemin
        city = self.win.city
        for gy in range(GRID):
            for gx in range(GRID):
                x, y = iso_to_screen(gx, gy, OX, OY)
                p.setPen(QPen(QColor(79, 227, 255, 55), 1))
                p.setBrush(QColor(18, 14, 36))
                p.drawPolygon(_poly((x, y), (x + TW / 2, y + TH / 2), (x, y + TH), (x - TW / 2, y + TH / 2)))
        # binalar: arkadan öne
        for (gx, gy) in sorted(city.cells, key=lambda c: c[0] + c[1]):
            key, lv = city.cells[(gx, gy)]
            x, y = iso_to_screen(gx, gy, OX, OY)
            draw_building(p, key, lv, x, y + TH / 2, t, gx * 7 + gy * 13)
        # imleç
        if self.hover is not None:
            gx, gy = self.hover
            x, y = iso_to_screen(gx, gy, OX, OY)
            col = self.win.hover_color(self.hover)
            p.setPen(QPen(col, 2))
            fill = QColor(col)
            fill.setAlpha(60)
            p.setBrush(fill)
            p.drawPolygon(_poly((x, y), (x + TW / 2, y + TH / 2), (x, y + TH), (x - TW / 2, y + TH / 2)))
        # başlık
        f = QFont("Monospace")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setBold(True)
        f.setPixelSize(18)
        p.setFont(f)
        p.setPen(QColor("#FF4F9A"))
        p.drawText(QPointF(14, 28), TITLE.upper())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#7DF0FF"))
        p.drawText(QPointF(14, 44), SUBTITLE.lower())
        p.end()


class CityWindow(hud.GlitchWindow, QWidget):
    def __init__(self, cfg, wallet, save, say=None, on_change=None):
        super().__init__(None, Qt.WindowType.Tool)
        self.city = City(cfg, wallet, save)
        self.wallet, self.say_cb, self.on_change = wallet, say, on_change
        self.tool = None  # None | ("build", anahtar) | ("upgrade",) | ("demolish",)
        self.msg = "Bir bina seç, sonra bir arsaya tıkla."
        self._last_say = 0.0
        self.setObjectName("city")
        self.setWindowTitle(f"{TITLE} — {SUBTITLE}")
        self.setStyleSheet(STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.view = CityView(self)
        self.coins_lbl = QLabel()
        self.coins_lbl.setStyleSheet("font-size:14px; font-weight:bold; color:#FFD84A;")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(30)

        self.buttons = {}
        grid = QGridLayout()
        for i, (key, (name, icon, _, _, _)) in enumerate(BUILDINGS.items()):
            b = QPushButton(f"{icon} {name}\n{build_cost(key)} 🪙")
            b.setCheckable(True)
            b.setToolTip(BUILDINGS[key][4])
            b.clicked.connect(lambda _=False, k=key: self.pick(("build", k)))
            grid.addWidget(b, i // 4, i % 4)
            self.buttons[("build", key)] = b
        for j, (tool, text) in enumerate((("upgrade", "⬆ Yükselt"), ("demolish", "🗑 Yık"))):
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, tl=tool: self.pick((tl,)))
            grid.addWidget(b, 2, j * 2, 1, 2)
            self.buttons[(tool,)] = b

        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        top.addWidget(self.coins_lbl)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.view)
        lay.addLayout(top)
        lay.addLayout(grid)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.refresh()

    # --- araç seçimi
    def pick(self, tool):
        self.tool = None if self.tool == tool else tool
        for k, b in self.buttons.items():
            b.setChecked(k == self.tool)
        self.msg = {None: "Araç bırakıldı.", }.get(self.tool) or self.tool_hint()
        self.refresh()

    def tool_hint(self):
        if self.tool is None:
            return "Bir bina seç, sonra bir arsaya tıkla."
        if self.tool[0] == "build":
            k = self.tool[1]
            return f"{BUILDINGS[k][0]} ({build_cost(k)} jeton): boş bir arsaya tıkla."
        return "Yükseltmek istediğin binaya tıkla." if self.tool[0] == "upgrade" else "Yıkmak istediğin binaya tıkla (iade yok)."

    def hover_color(self, cell):
        """İmleç karesinin rengi: yeşil = yapılabilir, kırmızı = yapılamaz, sarı = yükseltme."""
        ok, bad = QColor(92, 255, 157), QColor(255, 70, 90)
        coins = self.wallet["coins"]
        b = self.city.cells.get(cell)
        if self.tool is None:
            return QColor(125, 240, 255)
        if self.tool[0] == "build":
            return ok if b is None and coins >= build_cost(self.tool[1]) else bad
        if self.tool[0] == "upgrade":
            c = upgrade_cost(*b) if b else None
            return QColor(255, 216, 74) if c is not None and coins >= c else bad
        return bad if b is None else QColor(255, 120, 60)

    def on_hover(self, cell):
        if cell is not None:
            self.status.setText(self.city.info(cell))
        else:
            self.status.setText(self.msg)

    def on_click(self, cell):
        if self.tool is None:
            self.msg = self.city.info(cell) + " — alttan bir araç seç."
        elif self.tool[0] == "build":
            ok, self.msg = self.city.build(cell, self.tool[1])
            self.react("build" if ok else None)
        elif self.tool[0] == "upgrade":
            ok, self.msg = self.city.upgrade(cell)
            self.react("upgrade" if ok else None)
        else:
            ok, self.msg = self.city.demolish(cell)
            self.react("demolish" if ok else None)
        if self.wallet["coins"] <= 0 and self.tool and self.tool[0] != "demolish":
            self.react("broke", force=True)
        self.status.setText(self.msg)
        self.refresh()
        if self.on_change:
            self.on_change()

    def react(self, kind, force=False):
        """Pet ara sıra yorum yapar (art arda tıklamada sürekli konuşmasın)."""
        now = time.time()
        if kind and self.say_cb and (force or now - self._last_say > 9):
            self._last_say = now
            self.say_cb(random.choice(LINES[kind]))

    def showEvent(self, e):
        self.timer.start(60)  # yalnızca pencere görünürken çiz
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def tick(self):
        self.refresh(light=True)
        self.view.update()

    def refresh(self, light=False):
        self.coins_lbl.setText(f"🪙 {self.wallet['coins']}   ·   harcanan {self.city.spent}")
        if not light:
            self.status.setText(self.msg)
        self.view.update()
