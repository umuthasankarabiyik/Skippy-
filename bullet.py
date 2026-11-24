"""Varsayılan karakter: altın bir mermi — büyük gözler, geniş sırıtış, gözlük alnında, mavi kollar, ayak yok.
Yürümez: olduğu yerde süzülür, altında hafif mavi bir hologram diski durur. 120x120'lik alanda çizilir."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen

GOLD, GOLD_L, GOLD_D = QColor("#E3A62B"), QColor("#FFE49A"), QColor("#A06A14")
OUT = QColor("#5B3A0A")
ARM, ARM_D, ARM_L = QColor("#3C9AE0"), QColor("#1F5E9C"), QColor("#8FD0FF")
GOG, GOG_L = QColor("#E4561E"), QColor("#FF9A5A")
INK = QColor("#161616")
MOUTH = QColor("#5A1B12")
HOLO = (80, 200, 255)

# kol pozları (SOL kol için; sağ kolda x işareti ters): omuza göre (kontrol1, kontrol2, el)
POSES = {
    "down": ((-7, 6), (-13, 15), (-14, 27)),
    "hover": ((-9, 5), (-17, 12), (-19, 24)),
    "hip": ((-18, 4), (-21, 15), (-6, 21)),
    "point": ((-14, -4), (-22, -18), (-22, -34)),
    "ear": ((-14, 2), (-22, -8), (-15, -24)),
    "limp": ((-4, 8), (-6, 18), (-6, 28)),
}


def _pt(x, y):
    return QPointF(x, y)


def arm(p, shoulder, pose, side, wob):
    """side -1 = sol, +1 = sağ. wob: elin salınımı (dx, dy)."""
    c1, c2, h = POSES[pose]
    sx, sy = shoulder
    s = -side  # pozlar sol kol içindir
    pts = [_pt(sx + s * c1[0], sy + c1[1]), _pt(sx + s * c2[0] + wob[0] * 0.5, sy + c2[1] + wob[1] * 0.5),
           _pt(sx + s * h[0] + wob[0], sy + h[1] + wob[1])]
    path = QPainterPath()
    path.moveTo(_pt(sx, sy))
    path.cubicTo(*pts)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for width, col in ((10.5, ARM_D), (7.2, ARM), (2.2, ARM_L)):
        pen = QPen(col, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if col is ARM_L:
            path2 = QPainterPath()
            path2.moveTo(_pt(sx - side * 1.0 - 1, sy + 2))
            path2.cubicTo(_pt(pts[0].x() - 1, pts[0].y() + 2), _pt(pts[1].x() - 1, pts[1].y() + 1), _pt(pts[2].x() - 1, pts[2].y() - 2))
            p.drawPath(path2)
        else:
            p.drawPath(path)
    hand = pts[2]
    p.setPen(QPen(ARM_D, 2))
    p.setBrush(ARM)
    p.drawEllipse(hand, 6.4, 6.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ARM_L)
    p.drawEllipse(_pt(hand.x() - 1.8, hand.y() - 2), 2.2, 1.7)


def hologram(p, t, b, dim):
    """Mavi hologram diski (120x120 koordinatında); herhangi bir görünümün altına çizilebilir."""
    r, g, bl = HOLO
    a = 0.5 if dim else 1.0
    cy = 113
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(r, g, bl, int(13 * a)))                   # ışık huzmesi
    beam = QPainterPath()
    beam.moveTo(_pt(28, cy))
    beam.lineTo(_pt(40, 98))
    beam.lineTo(_pt(80, 98))
    beam.lineTo(_pt(92, cy))
    beam.closeSubpath()
    p.drawPath(beam)
    for k in range(3):                                          # yukarı kayan tarama çizgileri
        y = cy - ((t * 0.35 + k * 4.5) % 13)
        w = 34 - (cy - y) * 0.9
        p.setPen(QPen(QColor(r, g, bl, int(38 * a)), 1))
        p.drawLine(_pt(60 - w, y), _pt(60 + w, y))
    p.setPen(QPen(QColor(r, g, bl, int(150 * a)), 1.3))        # disk
    p.setBrush(QColor(r, g, bl, int(34 * a)))
    p.drawEllipse(_pt(60, cy), 34, 6.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(r, g, bl, int(90 * a)), 1))
    p.drawEllipse(_pt(60, cy), 22, 4.2)
    ph = (t * 0.025) % 1.0                                      # yayılan halka
    rx = 10 + 26 * ph
    p.setPen(QPen(QColor(r, g, bl, int(140 * (1 - ph) * a)), 1.2))
    p.drawEllipse(_pt(60, cy), rx, rx * 0.19)
    p.setPen(Qt.PenStyle.NoPen)                                 # küçük kıvılcımlar
    for k in range(3):
        q = (t * 0.02 + k * 0.33) % 1.0
        p.setBrush(QColor(r, g, bl, int(150 * (1 - q) * a)))
        p.drawEllipse(_pt(60 + math.sin(k * 2.4 + t * 0.03) * 22, cy - 2 - q * 12), 1.2, 1.2)


def body(p, b):
    out = QPainterPath()
    out.moveTo(_pt(33, 100 + b))
    out.lineTo(_pt(33, 52 + b))
    out.cubicTo(_pt(33, 30 + b), _pt(48, 14 + b), _pt(60, 5 + b))
    out.cubicTo(_pt(72, 14 + b), _pt(87, 30 + b), _pt(87, 52 + b))
    out.lineTo(_pt(87, 100 + b))
    out.cubicTo(_pt(87, 105 + b), _pt(33, 105 + b), _pt(33, 100 + b))
    out.closeSubpath()
    p.setPen(QPen(OUT, 2.4))
    p.setBrush(GOLD)
    p.drawPath(out)
    p.setPen(Qt.PenStyle.NoPen)
    sh = QPainterPath()                                         # sağ gölge
    sh.moveTo(_pt(86, 100 + b))
    sh.lineTo(_pt(86, 52 + b))
    sh.cubicTo(_pt(86, 31 + b), _pt(72, 15 + b), _pt(61, 7 + b))
    sh.cubicTo(_pt(70, 21 + b), _pt(76, 34 + b), _pt(76, 56 + b))
    sh.lineTo(_pt(76, 100 + b))
    sh.closeSubpath()
    p.setBrush(GOLD_D)
    p.drawPath(sh)
    hl = QPainterPath()                                         # sol parlak şerit
    hl.moveTo(_pt(40, 96 + b))
    hl.lineTo(_pt(40, 54 + b))
    hl.cubicTo(_pt(40, 38 + b), _pt(49, 24 + b), _pt(57, 13 + b))
    hl.cubicTo(_pt(51, 28 + b), _pt(48, 40 + b), _pt(48, 56 + b))
    hl.lineTo(_pt(48, 96 + b))
    hl.closeSubpath()
    p.setBrush(QColor(255, 228, 154, 215))
    p.drawPath(hl)
    p.setPen(QPen(QColor(255, 255, 255, 55), 1))                # fırçalanmış metal çizikleri
    for x0, y0, x1, y1 in ((52, 68, 70, 94), (58, 62, 74, 84), (47, 74, 60, 92), (62, 86, 72, 98)):
        p.drawLine(_pt(x0, y0 + b), _pt(x1, y1 + b))


def eyes(p, t, state, blink, b):
    closed = state == "sleep"
    cy = 60 + b
    squash = 0.15 if blink else 1.0
    look = (math.sin(t * 0.031) * 2.4, math.sin(t * 0.017) * 1.2)
    if state == "sit":
        look = (0.0, 1.6)
    for ex, rx, ry in ((49, 9.6, 10.8), (71, 10.2, 11.4)):
        if closed:
            p.setPen(QPen(INK, 2.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(_pt(ex - rx + 1, cy + 1), _pt(ex + rx - 1, cy + 1))
            continue
        p.setPen(QPen(INK, 1.4))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(_pt(ex, cy), rx, ry * squash)
        if squash > 0.5:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(INK)
            p.drawEllipse(_pt(ex + look[0], cy + look[1]), 3.7, 3.9)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(_pt(ex + look[0] - 1.2, cy + look[1] - 1.4), 1.2, 1.2)
    if closed:
        return
    bp = QPen(INK, 3.4)
    bp.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(bp)
    if state == "happy":
        brows = ((40, 46, 55, 42), (66, 42, 80, 46))
    elif state == "sit":      # sinsi, kaşlar içe çatık
        brows = ((40, 45, 56, 50), (65, 50, 81, 45))
    else:
        brows = ((40, 48, 55, 45), (66, 42, 80, 46))
    for x0, y0, x1, y1 in brows:
        p.drawLine(_pt(x0, y0 + b), _pt(x1, y1 + b))


def mouth(p, state, b):
    my = 78 + b
    if state == "sleep":
        p.setPen(QPen(OUT, 2.2))
        p.drawLine(_pt(54, my + 5), _pt(66, my + 5))
        return
    half, depth, n = (16, 15, 7) if state == "happy" else (13, 11, 6)
    x0, x1 = 60 - half, 60 + half
    m = QPainterPath()
    m.moveTo(_pt(x0, my))
    m.cubicTo(_pt(x0 + half * 0.6, my + 5), _pt(x1 - half * 0.6, my + 5), _pt(x1, my))
    m.cubicTo(_pt(x1 - 3, my + depth), _pt(x0 + 3, my + depth), _pt(x0, my))
    m.closeSubpath()
    p.setPen(QPen(OUT, 2))
    p.setBrush(MOUTH)
    p.drawPath(m)
    if state == "happy":                                        # dil
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E0605A"))
        p.drawEllipse(_pt(60, my + depth - 3), 7, 3.2)
    p.setPen(QPen(QColor("#CFCFCF"), 0.8))                      # diş sırası
    p.setBrush(QColor("#FFFFFF"))
    w = (2 * half - 3) / n
    for i in range(n):
        x = x0 + 1.5 + i * w
        u = (x + w / 2 - 60) / half
        yt = my + 4.6 * (1 - u * u) * 0.85 + 0.4
        p.drawRoundedRect(QRectF(x, yt, w - 0.4, 5.2), 1.2, 1.2)


def goggles(p, state, b, t):
    p.save()
    if state == "sleep":                                        # uyurken gözlük gözlerin üstüne iner
        p.translate(60, 60 + b)
    else:
        p.translate(60, 34 + b)
        p.rotate(-5 + math.sin(t * 0.04) * 1.0)
    for x0 in (-22, 2):
        r = QRectF(x0, -8, 20, 16)
        p.setPen(QPen(GOG, 3.6))
        p.setBrush(QColor(190, 230, 255, 110) if state != "sleep" else QColor(190, 230, 255, 70))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QPen(GOG_L, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(_pt(x0 + 4, -3), _pt(x0 + 8, -5))
    p.setPen(QPen(GOG, 3.6))
    p.drawLine(_pt(-2, -1), _pt(2, -1))                         # köprü
    p.setPen(QPen(GOG, 5))
    p.drawLine(_pt(-23, 0), _pt(-27, 4))                        # kayış uçları
    p.drawLine(_pt(23, 0), _pt(27, 4))
    p.restore()


def float_offset(t, state):
    """Süzülme: dikey kayma (120'lik birim). Her görünüm için ortak."""
    if state == "walk":
        return -2 + math.sin(t * 0.14) * 3.5
    if state == "sleep":
        return 3 + math.sin(t * 0.05) * 1.0
    if state == "sit":
        return -1 + math.sin(t * 0.07) * 1.6
    if state == "happy":
        return -4 + math.sin(t * 0.3) * 4
    if state == "drag":
        return -2
    return -2 + math.sin(t * 0.08) * 2.2


def draw_bullet(p, t, state, blink, holo=True):
    """t: kare sayacı. Yürüme durumu da yerinde süzülmedir; yatay hareket pet.py'de yok."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    hover = state == "walk"
    b = float_offset(t, state)
    if holo:
        hologram(p, t, b, state == "sleep")
    p.translate(0, 4)  # süzülme tepeden taşmasın

    p.save()                                                    # hafif sağa sola salınım (altı ekseninde)
    p.translate(60, 100)
    p.rotate(math.sin(t * 0.05) * (2.6 if hover else 1.4))
    p.translate(-60, -100)

    wob = (math.sin(t * 0.12) * 2.5, math.cos(t * 0.12) * 1.8)
    if state == "happy":
        poses = ("hip", "point")
        wobs = ((0, 0), (math.sin(t * 0.5) * 2.2, math.cos(t * 0.5) * 1.6))
    elif state == "sit":
        poses = ("ear", "ear")
        wobs = ((math.sin(t * 0.3) * 1.5, 0), (-math.sin(t * 0.3) * 1.5, 0))
    elif state == "sleep":
        poses = ("limp", "limp")
        wobs = ((0, 0), (0, 0))
    else:
        poses = ("hover" if hover else "down",) * 2
        wobs = (wob, (-wob[0], wob[1]))
    arm(p, (33, 72 + b), poses[0], -1, wobs[0])
    arm(p, (87, 72 + b), poses[1], 1, wobs[1])
    body(p, b)
    eyes(p, t, state, blink, b)
    mouth(p, state, b)
    goggles(p, state, b, t)
    p.restore()
