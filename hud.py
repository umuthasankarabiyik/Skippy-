"""Fütüristik HUD görünümü ve glitch animasyonları.

- frame_points / frame_ops : çerçeve geometrisi (Qt'siz, test edilebilir). Köşeleri kesik, kenarında çentik, köşelerinde
  ok işaretleri / küçük bloklar olan kırmızı HUD çerçeveleri. variant: 0 = konuşma balonu, 1 = bildirim, 2 = sayaç.
- paint_frame     : bu geometriyi Qt ile çizer (hafif parlama + içi çok hafif kareli koyu zemin).
- GlitchState     : glitch animasyonunun kare tablosu ve durum makinesi (Qt'siz).
- HudWidget       : çerçevesini kendi çizen pencere (balon, sayaç). Açılırken / kapanırken yatay şeritlere ayrılıp
                    kayar ve titrer (glitch).
- GlitchWindow    : normal pencerelere (sohbet, Tamagotchi paneli, not defteri) glitch ile açılıp kapanma ekleyen karışım sınıfı.
"""
import random

from PyQt6.QtCore import QPoint, QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QWidget

RED = "#FF2A2A"
PANEL_BG = (16, 3, 6, 238)   # koyu kırmızımsı siyah
GRID_STEP = 9                # içindeki kare desenin aralığı (px)
MARGIN = 12                  # çerçevenin etrafındaki boş pay (glitch kaymaları ve dışa taşan süsler için)

GL_MS = 32                   # glitch kare süresi
# (opaklık, yatay kayma px). Kayma yönü her karede rastgele seçilir.
FRAMES = {
    "in":    [(0.0, 0), (0.9, 12), (0.25, 9), (1.0, 5), (0.35, 7), (1.0, 2), (0.7, 3), (1.0, 0)],
    "out":   [(1.0, 0), (0.4, 8), (1.0, 11), (0.2, 6), (0.8, 5), (0.1, 4), (0.5, 2), (0.0, 0)],
    "pulse": [(0.55, 6), (1.0, 4), (1.0, 0)],   # görünürken metin değişince kısa titreme
}


# ------------------------------------------------------------ çerçeve geometrisi (Qt'siz)
def frame_points(x, y, w, h, variant):
    """Çerçevenin dış hattı (köşe noktaları, saat yönünde)."""
    c = max(4.0, min(10.0, h * 0.28, w * 0.2))  # köşe kesiği
    if variant == 1:    # bildirim: sağ üst ve sol alt köşe kesik
        return [(x, y), (x + w - c, y), (x + w, y + c), (x + w, y + h), (x + c, y + h), (x, y + h - c)]
    if variant == 2:    # sayaç: dört köşe kesik, üst kenarda basamaklı çentik
        return [(x + c, y), (x + w * 0.4, y), (x + w * 0.4 + 3, y + 3), (x + w * 0.7, y + 3), (x + w * 0.7 + 3, y),
                (x + w - c, y), (x + w, y + c), (x + w, y + h - c), (x + w - c, y + h), (x + c, y + h),
                (x, y + h - c), (x, y + c)]
    # balon: sol üst ve sağ alt köşe kesik, üst kenarda çentik
    return [(x + c, y), (x + w * 0.55, y), (x + w * 0.55 + 4, y + 3), (x + w * 0.8, y + 3), (x + w * 0.8 + 4, y),
            (x + w, y), (x + w, y + h - c), (x + w - c, y + h), (x, y + h), (x, y + c)]


def frame_ops(x, y, w, h, variant, tag_w=0):
    """Çerçevenin süslerini basit çizim komutlarına çevirir:
    ("line", p1, p2, kalınlık, alfa) · ("rect", x, y, w, h) · ("fill", noktalar) · ("dot", cx, cy, r)"""
    c = max(4.0, min(10.0, h * 0.28, w * 0.2))
    ops = []
    if variant == 0:
        for i in range(3):                                   # >>> ok işaretleri
            x0 = x + 14 + i * 7
            ops.append(("line", (x0, y + 6), (x0 + 3.5, y + 9.5), 1.6, 255))
            ops.append(("line", (x0 + 3.5, y + 9.5), (x0, y + 13), 1.6, 255))
        for i in range(3):                                   # kenarın üstünde ■■■
            ops.append(("rect", x + w * 0.55 - 34 + i * 10, y - 4, 6, 4))
        tw = min(46.0, w * 0.3)                              # sol altta dolu yamuk
        ops.append(("fill", [(x + 10, y + h), (x + 16, y + h - 5), (x + 16 + tw, y + h - 5), (x + 22 + tw, y + h)]))
        ops.append(("line", (x + w - 5, y + h * 0.3), (x + w - 5, y + h * 0.7), 1.2, 200))   # sağda ince çift çizgi
        ops.append(("line", (x + w - 9, y + h * 0.4), (x + w - 9, y + h * 0.6), 1.2, 120))
        ops.append(("dot", x + w - 10, y + 10, 2.2))
    elif variant == 1:
        if tag_w:                                            # sol üstte dolu etiket bloğu
            ops.append(("fill", [(x, y), (x + tag_w, y), (x + tag_w + 6, y + 7), (x + tag_w, y + 14), (x, y + 14)]))
        for i in range(3):                                   # altta ▲▲▲
            bx = x + c + 8 + i * 9
            ops.append(("fill", [(bx, y + h - 3), (bx + 3.5, y + h - 9), (bx + 7, y + h - 3)]))
        for i in range(max(0, int(w * 0.4 // 5))):           # altta noktalı çizgi
            ops.append(("rect", x + w * 0.58 + i * 5, y + h - 5, 2, 1.8))
        ops.append(("line", (x + 5, y + h * 0.4), (x + 5, y + h * 0.8), 1.2, 200))
    else:
        ops.append(("rect", x + 5, y + h * 0.3, 2.5, h * 0.4))   # solda küçük blok
        for i in range(4):                                       # sağ üstte //// taraması
            hx = x + w - 30 + i * 5
            ops.append(("line", (hx, y + h - 6), (hx + 4, y + 6), 1.4, 255))
        ops.append(("line", (x + 14, y + h - 4), (x + w * 0.42, y + h - 4), 1.2, 120))
    return ops


# ------------------------------------------------------------------ Qt çizimi
def paint_frame(p, x, y, w, h, color, variant, tag_w=0):
    """HUD çerçevesini çizer: parlama, koyu zemin, çok hafif kareler, dış hat ve süsler."""
    col = QColor(color)
    pts = frame_points(x, y, w, h, variant)
    path = QPainterPath()
    path.moveTo(QPointF(*pts[0]))
    for q in pts[1:]:
        path.lineTo(QPointF(*q))
    path.closeSubpath()

    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    glow = QColor(col)
    glow.setAlpha(45)
    gp = QPen(glow, 6)
    gp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(gp)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(*PANEL_BG))
    p.drawPath(path)

    p.save()                                   # içi çok hafif kareli
    p.setClipPath(path)
    grid = QColor(col)
    grid.setAlpha(26)
    p.setPen(QPen(grid, 1))
    gx = x + GRID_STEP
    while gx < x + w:
        p.drawLine(QPointF(gx, y), QPointF(gx, y + h))
        gx += GRID_STEP
    gy = y + GRID_STEP
    while gy < y + h:
        p.drawLine(QPointF(x, gy), QPointF(x + w, gy))
        gy += GRID_STEP
    p.restore()

    pen = QPen(col, 2)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    for op in frame_ops(x, y, w, h, variant, tag_w):
        kind = op[0]
        if kind == "line":
            c2 = QColor(col)
            c2.setAlpha(op[4])
            lp = QPen(c2, op[3])
            lp.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(lp)
            p.drawLine(QPointF(*op[1]), QPointF(*op[2]))
        elif kind == "rect":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRect(QRectF(op[1], op[2], op[3], op[4]))
        elif kind == "fill":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(*q) for q in op[1]]))
        elif kind == "dot":
            p.setPen(QPen(col, 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(op[1], op[2]), op[3], op[3])


# ----------------------------------------------------------- glitch durum makinesi
class GlitchState:
    """mode: None / "in" / "out" / "pulse". step() her çağrıda bir kare ilerletir."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.mode, self.i = None, 0
        self.opacity, self.amp = 1.0, 0.0

    def start(self, mode):
        self.mode, self.i = mode, 0
        self.opacity, self.amp = (0.0 if mode == "in" else 1.0), 0.0

    def step(self, rng=random):
        """(opaklık, işaretli yatay kayma, biten mod). Animasyon bitince biten mod 'in'/'out'/'pulse', yoksa None."""
        frames = FRAMES[self.mode]
        op, mag = frames[self.i]
        self.i += 1
        dx = mag * rng.choice((-1, 1))
        if self.i >= len(frames):
            done = self.mode
            self.reset()
            return op, dx, done
        self.opacity, self.amp = op, mag
        return op, dx, None


# ------------------------------------------------- kendi çerçevesini çizen pencere
class HudWidget(QWidget):
    """Tıklamaları engellemeyen, çerçevesini kendisi çizen pencere. Alt sınıflar draw(p) yazar."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.X11BypassWindowManagerHint)  # WM yok: görev çubuğunda sekme açmaz
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._gl = GlitchState()
        self._gl_timer = QTimer(self)
        self._gl_timer.timeout.connect(self._gl_tick)

    def draw(self, p):  # alt sınıf doldurur
        raise NotImplementedError

    def glitch_show(self):
        if self._gl.mode is None and self.isVisible():
            return
        self._gl.start("in")  # kapanma sürüyorsa iptal edilip yeniden açılır
        self.show()
        self.raise_()
        self._gl_timer.start(GL_MS)

    def glitch_hide(self):
        if not self.isVisible() or self._gl.mode == "out":
            return
        self._gl.start("out")
        self._gl_timer.start(GL_MS)

    def glitch_pulse(self):
        if self.isVisible() and self._gl.mode is None:
            self._gl.start("pulse")
            self._gl_timer.start(GL_MS)

    def _gl_tick(self):
        _, _, done = self._gl.step()
        if done:
            self._gl_timer.stop()
            if done == "out":
                self.hide()
        self.update()

    def hideEvent(self, e):
        self._gl_timer.stop()
        self._gl.reset()
        super().hideEvent(e)

    def paintEvent(self, _):
        st = self._gl
        p = QPainter(self)
        if st.mode is None:
            self.draw(p)
            p.end()
            return
        if st.opacity > 0.01:
            pix = QPixmap(self.size())
            pix.fill(Qt.GlobalColor.transparent)
            q = QPainter(pix)
            self.draw(q)
            q.end()
            p.setOpacity(st.opacity)
            w, h = self.width(), self.height()
            amp = int(min(st.amp, MARGIN - 2))
            y = 0
            while y < h:  # yatay şeritlere ayırıp rastgele kaydır
                sh = random.randint(3, 10)
                dx = random.randint(-amp, amp) if amp and random.random() < 0.65 else 0
                p.drawPixmap(dx, y, pix, 0, y, w, min(sh, h - y))
                y += sh
        p.end()


# ---------------------------------------- normal pencereler için glitch açılış / kapanış
class GlitchWindow:
    """QWidget'tan ÖNCE karıştırılır: class Panel(GlitchWindow, QWidget). show() yerine glitch_show(),
    hide() yerine glitch_hide() kullanılır; X ile kapatma da glitch ile kapanır."""

    def _glw_init(self):
        if not hasattr(self, "_glw"):
            self._glw = GlitchState()
            self._glw_home = None
            self._glw_timer = QTimer(self)
            self._glw_timer.timeout.connect(self._glw_tick)

    def glitch_show(self):
        self._glw_init()
        st = self._glw
        if st.mode is None and self.isVisible():
            self.raise_()
            self.activateWindow()
            return
        if st.mode is None:
            self._glw_home = self.pos()  # kapanma sürüyorsa eski konum korunur
        st.start("in")
        self.setWindowOpacity(0.0)
        self.move(self._glw_home)
        self.show()
        self.raise_()
        self.activateWindow()
        self._glw_timer.start(GL_MS)

    def glitch_hide(self):
        self._glw_init()
        st = self._glw
        if not self.isVisible() or st.mode == "out":
            return
        if st.mode is None:
            self._glw_home = self.pos()
        st.start("out")
        self._glw_timer.start(GL_MS)

    def _glw_tick(self):
        op, dx, done = self._glw.step()
        home = self._glw_home
        if done:
            self._glw_timer.stop()
            if done == "out":
                self.hide()
            self.move(home)
            self.setWindowOpacity(1.0)
        else:
            self.setWindowOpacity(op)
            self.move(QPoint(home.x() + dx, home.y()))

    def closeEvent(self, e):
        self._glw_init()
        if not self.isVisible() or self._glw.mode == "out":
            e.accept()
            return
        e.ignore()
        self.glitch_hide()
