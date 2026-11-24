"""Mermi Pet'in mini oyunu: cyberpunk şehirde Doom tarzı boomer shooter (raycasting).

Kontroller:  W/S ileri-geri · A/D yan adım · ←/→ dön · Boşluk/Ctrl/fare ateş · Q (basılı) hack · Esc çık
Silahlar:    1 Goril protez (başlangıç) · 2 Katana · 3 Tabanca · 4 Pompalı (düşmanlardan düşer) · F/fare tekerleği: sıradaki
Hack:        her öldürme 1 stack (en çok 5); Q basılıyken bir düşmana bakınca 3 stack harcar, düşman yanarak ölür, can paketi düşürür
"""
import math
import random
import time
from collections import namedtuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

import hud

# ===================================================================== motor (Qt'siz)
MAP_ROWS = [
    "1111111111111111",
    "1..............1",
    "1.222......333.1",
    "1.2..........3.1",
    "1.2....11....3.1",
    "1......1.......1",
    "1..33..1..22...1",
    "1..3.......2...1",
    "1..3...........1",
    "1....22.....3..1",
    "1....2......3..1",
    "1..........11..1",
    "1.111..........1",
    "1..............1",
    "1..............1",
    "1111111111111111",
]
MAP = [[0 if c == "." else int(c) for c in row] for row in MAP_ROWS]
MAP_H, MAP_W = len(MAP), len(MAP[0])
PLANE = 0.9          # görüş genişliği (≈84°)
MOVE_SPEED = 3.2
TURN_SPEED = 2.4
FIRE_COOLDOWN = 0.55
MAX_AMMO, MAX_HP = 50, 100
MAX_ROUNDS, MAX_BATT = 90, 100   # tabanca kurşunu (pompalı kartuşundan ayrı) ve katana pili
PISTOL_CD, KATANA_CD, PUNCH_CD = 0.22, 0.5, 0.55
KATANA_COST, KATANA_RANGE = 12, 1.9
PUNCH_RANGE = 1.3                # goril protez: çok kısa menzil
WEAPONS = ("fists", "katana", "pistol", "shotgun")
MAX_STACKS, HACK_COST, HACK_BURN = 5, 3, 0.8   # hack barı: en çok 5 stack, 3 harcar, düşman 0.8 sn yanıp ölür
HACK_HEALTH_CHANCE = 0.55                      # hack ile öldürülen düşmandan can paketi düşme şansı
WEAPON_FOUND_AMMO = {"katana": 50, "pistol": 24, "shotgun": 12}  # silahı bulunca gelen cephane (pil / kurşun / kartuş)
WEAPON_NAMES = {"fists": "PROTEZ", "katana": "KATANA", "pistol": "TABANCA", "shotgun": "POMPALI"}
TITLE, SUBTITLE = "Happy Slaughtering", "Boomer Shooter"

KINDS = {
    "brawler": {"hp": 3, "speed": 1.7},
    "gunner": {"hp": 2, "speed": 1.0},
}

Inp = namedtuple("Inp", "fwd strafe turn fire hack", defaults=(False,))
NO_INPUT = Inp(0, 0, 0, False)


def solid(x, y):
    if x < 0 or y < 0 or x >= MAP_W or y >= MAP_H:
        return True
    return MAP[int(y)][int(x)] != 0


def blocked(x, y, r=0.25):
    return (solid(x - r, y - r) or solid(x + r, y - r) or solid(x - r, y + r) or solid(x + r, y + r))


def los(x0, y0, x1, y1, stop=0.0):
    """Görüş hattı. stop: hedefe bu kadar yaklaşınca denetimi bırak (duvara yaslanmış / sıkışmış hedef vurulabilsin)."""
    dist = math.hypot(x1 - x0, y1 - y0)
    n = int(dist / 0.15) + 1
    for i in range(1, n):
        f = i / n
        if dist * (1 - f) < stop:
            break
        if solid(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f):
            return False
    return True


class Enemy:
    def __init__(self, kind, x, y):
        self.kind = kind
        self.x, self.y = x, y
        self.hp = KINDS[kind]["hp"]
        self.flash = 0.0
        self.cool = random.uniform(0.5, 2.0)
        self.phase = random.uniform(0, 6.28)  # yürüme animasyonu fazı
        self.stuck = 0.0                      # ilerleyemediği süre
        self.detour_t = 0.0                   # takılınca yan yoldan dolanma süresi
        self.detour = (0.0, 0.0)
        self.burn = 0.0                       # hack ile yanıyorsa kalan süre
        self.hacked = False


class Ball:
    def __init__(self, x, y, vx, vy):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = 4.0


class Pickup:
    def __init__(self, kind, x, y):
        self.kind, self.x, self.y = kind, x, y


class Engine:
    def __init__(self):
        self.reset()

    def reset(self):
        self.x, self.y, self.a = 2.5, 13.5, -math.pi / 2
        self.hp, self.ammo = MAX_HP, 0
        self.rounds, self.battery = 0, 0
        self.weapon = "fists"                    # kolla başlar; diğer silahlar düşmanlardan düşer
        self.unlocked = {"fists"}
        self.kills_since_weapon = 0
        self.stacks = 0                          # hack barı
        self.hack_cd = 0.0
        self.notice, self.notice_t = "", 0.0
        self.swing = 0.0
        self.punch = 0.0
        self.punch_side = 0
        self.wave = 0
        self.kills = 0
        self.enemies, self.balls, self.pickups = [], [], []
        self.cooldown = self.flash = self.hurt = 0.0
        self.banner = 0.0
        self.clear_timer = 0.0
        self.ammo_timer = 0.0
        self.moving = False
        self.state = "playing"  # playing / dead
        self.events = []
        self.next_wave()

    # --- dalgalar
    def spawn_pos(self):
        for _ in range(300):
            x, y = random.randrange(1, MAP_W - 1) + 0.5, random.randrange(1, MAP_H - 1) + 0.5
            if solid(x, y) or math.hypot(x - self.x, y - self.y) < 7:
                continue
            if any(math.hypot(x - e.x, y - e.y) < 1.5 for e in self.enemies):
                continue
            return x, y
        return 13.5, 2.5

    def next_wave(self):
        self.wave += 1
        for _ in range(2 + self.wave):
            self.enemies.append(Enemy("brawler", *self.spawn_pos()))
        for _ in range(min(4, self.wave - 1)):
            self.enemies.append(Enemy("gunner", *self.spawn_pos()))
        if self.wave > 1:
            if "shotgun" in self.unlocked:
                self.ammo = min(MAX_AMMO, self.ammo + 8)
            if "pistol" in self.unlocked:
                self.rounds = min(MAX_ROUNDS, self.rounds + 6)
            if "katana" in self.unlocked:
                self.battery = min(MAX_BATT, self.battery + 8)
            self.hp = min(MAX_HP, self.hp + 15)
        self.banner = 2.0
        self.clear_timer = 0.0

    # --- ışın atma (duvarlar)
    def plane(self):
        dx, dy = math.cos(self.a), math.sin(self.a)
        return dx, dy, dy * PLANE, -dx * PLANE

    def cast(self, cols):
        px, py = self.x, self.y
        dx, dy, plx, ply = self.plane()
        out = []
        for i in range(cols):
            cam = 2.0 * i / cols - 1.0
            rdx, rdy = dx + plx * cam, dy + ply * cam
            mx, my = int(px), int(py)
            ddx = abs(1.0 / rdx) if rdx else 1e30
            ddy = abs(1.0 / rdy) if rdy else 1e30
            if rdx < 0:
                stepx, sdx = -1, (px - mx) * ddx
            else:
                stepx, sdx = 1, (mx + 1.0 - px) * ddx
            if rdy < 0:
                stepy, sdy = -1, (py - my) * ddy
            else:
                stepy, sdy = 1, (my + 1.0 - py) * ddy
            side, tile = 0, 1
            for _ in range(64):
                if sdx < sdy:
                    sdx += ddx
                    mx += stepx
                    side = 0
                else:
                    sdy += ddy
                    my += stepy
                    side = 1
                if mx < 0 or my < 0 or mx >= MAP_W or my >= MAP_H:
                    tile = 1
                    break
                tile = MAP[my][mx]
                if tile:
                    break
            perp = max(0.05, (sdx - ddx) if side == 0 else (sdy - ddy))
            wx = (py + perp * rdy) if side == 0 else (px + perp * rdx)
            out.append((perp, side, tile, wx - math.floor(wx), mx * MAP_W + my))
        return out

    def project(self, sx, sy, cols):
        """Dünya noktasını ekran sütununa çevirir: (sütun, derinlik) ya da None."""
        dx, dy, plx, ply = self.plane()
        rx, ry = sx - self.x, sy - self.y
        inv = 1.0 / (plx * dy - dx * ply)
        tx = inv * (dy * rx - dx * ry)
        ty = inv * (-ply * rx + plx * ry)
        if ty <= 0.15:
            return None
        return cols / 2 * (1 + tx / ty), ty

    # --- güncelleme
    def update(self, dt, inp):
        self.events = []
        self.flash = max(0.0, self.flash - dt)
        self.hurt = max(0.0, self.hurt - dt)
        self.cooldown = max(0.0, self.cooldown - dt)
        self.swing = max(0.0, self.swing - dt)
        self.punch = max(0.0, self.punch - dt)
        self.banner = max(0.0, self.banner - dt)
        self.hack_cd = max(0.0, self.hack_cd - dt)
        self.notice_t = max(0.0, self.notice_t - dt)
        if self.state != "playing":
            return

        self.a += -inp.turn * TURN_SPEED * dt          # sağa dönmek = açıyı azaltmak
        dx, dy, plx, ply = self.plane()
        k = MOVE_SPEED * dt
        mx = dx * inp.fwd + (plx / PLANE) * inp.strafe
        my = dy * inp.fwd + (ply / PLANE) * inp.strafe
        norm = math.hypot(mx, my)
        self.moving = norm > 0
        if norm > 1:
            mx, my = mx / norm, my / norm
        if not blocked(self.x + mx * k, self.y):
            self.x += mx * k
        if not blocked(self.x, self.y + my * k):
            self.y += my * k

        if inp.fire and self.cooldown <= 0:
            self.fire()
        if inp.hack:
            self.try_hack()

        for e in self.enemies[:]:
            self.update_enemy(e, dt)
        self.update_balls(dt)

        for p in self.pickups[:]:
            if math.hypot(p.x - self.x, p.y - self.y) < 0.7:
                if p.kind.startswith("w_"):
                    self.unlock(p.kind[2:])
                elif p.kind == "ammo" and self.ammo < MAX_AMMO:
                    self.ammo = min(MAX_AMMO, self.ammo + 6)
                elif p.kind == "rounds" and self.rounds < MAX_ROUNDS:
                    self.rounds = min(MAX_ROUNDS, self.rounds + 15)
                elif p.kind == "battery" and self.battery < MAX_BATT:
                    self.battery = min(MAX_BATT, self.battery + 25)
                elif p.kind == "health" and self.hp < MAX_HP:
                    self.hp = min(MAX_HP, self.hp + 25)
                else:
                    continue
                self.pickups.remove(p)
                self.events.append("pickup")

        # elindeki cephaneli silahların hepsi boşsa ve yerde de cephane yoksa bir kutu düşür
        kinds = self.ammo_kinds()
        if (kinds and not any(self.has_resource(w) for w in self.unlocked)
                and not any(p.kind in ("ammo", "rounds", "battery") for p in self.pickups)):
            self.ammo_timer += dt
            if self.ammo_timer > 3.0:
                self.ammo_timer = 0.0
                self.pickups.append(Pickup(random.choice(kinds), *self.spawn_pos()))
        if not self.enemies:
            self.clear_timer += dt
            if self.clear_timer >= 2.0:
                self.next_wave()

    # --- silahlar
    def select(self, weapon):
        if weapon in self.unlocked and weapon != self.weapon and self.state == "playing":
            self.weapon = weapon
            self.cooldown = max(self.cooldown, 0.18)
            self.events.append("switch")

    def cycle(self, step=1):
        self.select(WEAPONS[(WEAPONS.index(self.weapon) + step) % len(WEAPONS)])

    def ammo_kinds(self):
        """Elindeki cephane kullanan silahlara ait kutu türleri."""
        return [k for w, k in (("shotgun", "ammo"), ("pistol", "rounds"), ("katana", "battery")) if w in self.unlocked]

    def say(self, text, t=2.2):
        self.notice, self.notice_t = text, t

    def unlock(self, w):
        """Yerden silah alınca: açılır, cephanesi gelir, otomatik eline alınır."""
        self.unlocked.add(w)
        if w == "shotgun":
            self.ammo = min(MAX_AMMO, self.ammo + WEAPON_FOUND_AMMO[w])
        elif w == "pistol":
            self.rounds = min(MAX_ROUNDS, self.rounds + WEAPON_FOUND_AMMO[w])
        elif w == "katana":
            self.battery = min(MAX_BATT, self.battery + WEAPON_FOUND_AMMO[w])
        self.say(f"YENİ SİLAH: {WEAPON_NAMES[w]}")
        self.events.append("weapon")
        self.select(w)

    def has_resource(self, w):
        if w not in self.unlocked:
            return False
        return {"fists": True, "shotgun": self.ammo > 0, "pistol": self.rounds > 0,
                "katana": self.battery >= KATANA_COST}[w]

    def fire(self):
        if not self.has_resource(self.weapon):  # boşsa cephanesi olan sıradaki silaha geç
            for w in ("katana", "pistol", "shotgun", "fists"):
                if self.has_resource(w):
                    self.select(w)
                    return
            self.cooldown = 0.25
            return
        {"fists": self.punch_hit, "shotgun": self.shoot, "pistol": self.shoot_pistol, "katana": self.slash}[self.weapon]()

    def hit_enemy(self, e, dmg):
        e.hp -= dmg
        e.flash = 0.12
        if e.hp <= 0 and e in self.enemies:
            self.enemies.remove(e)
            self.kills += 1
            self.events.append("kill")
            if e.hacked:  # can paketi yalnızca hack ile öldürülenlerden düşer
                if random.random() < HACK_HEALTH_CHANCE:
                    self.pickups.append(Pickup("health", e.x, e.y))
                return
            self.stacks = min(MAX_STACKS, self.stacks + 1)  # her normal öldürme 1 hack stack'i
            self.kills_since_weapon += 1
            locked = [w for w in ("katana", "pistol", "shotgun")
                      if w not in self.unlocked and not any(p.kind == "w_" + w for p in self.pickups)]
            if locked and random.random() < min(0.7, 0.03 + 0.045 * self.kills_since_weapon):
                self.kills_since_weapon = 0           # zamanla silah düşer; her öldürmede şansı artar
                self.pickups.append(Pickup("w_" + random.choice(locked), e.x, e.y))
                return
            roll = random.random()
            for w, kind, chance in (("shotgun", "ammo", 0.17), ("pistol", "rounds", 0.16), ("katana", "battery", 0.10)):
                if w in self.unlocked:
                    if roll < chance:
                        self.pickups.append(Pickup(kind, e.x, e.y))
                        break
                    roll -= chance

    # --- hack
    def hack_target(self):
        """Artı işaretinin altındaki (görüş hattı açık, yanmayan) düşman."""
        dx, dy = math.cos(self.a), math.sin(self.a)
        best, bd = None, 1e9
        for e in self.enemies:
            if e.burn > 0:
                continue
            rx, ry = e.x - self.x, e.y - self.y
            d = rx * dx + ry * dy
            if d < 0.2 or d >= bd:
                continue
            if abs(-rx * dy + ry * dx) > 0.45 + 0.07 * d or not los(self.x, self.y, e.x, e.y, 0.45):
                continue
            best, bd = e, d
        return best

    def try_hack(self):
        """Q basılıyken düşmana bakılıyorsa: 3 stack harcar, düşman alev alıp ölür."""
        if self.hack_cd > 0:
            return
        e = self.hack_target()
        if e is None:
            return
        self.hack_cd = 0.45
        if self.stacks < HACK_COST:
            if self.notice_t < 0.3:
                self.say(f"HACK İÇİN {HACK_COST} STACK GEREK", 1.2)
            return
        self.stacks -= HACK_COST
        e.burn, e.hacked = HACK_BURN, True
        self.events.append("hack")

    def shoot(self):
        """Pompalı: çok kısa menzilde ağır hasar, önündeki herkese."""
        self.ammo -= 1
        self.cooldown = FIRE_COOLDOWN
        self.flash = 0.12
        self.events.append("shoot")
        dx, dy = math.cos(self.a), math.sin(self.a)
        for e in self.enemies[:]:
            rx, ry = e.x - self.x, e.y - self.y
            d = rx * dx + ry * dy
            if d < 0.2:
                continue
            lat = abs(-rx * dy + ry * dx)
            if lat > 0.45 + 0.07 * d or not los(self.x, self.y, e.x, e.y, 0.45):
                continue
            self.hit_enemy(e, 3 if d < 2.5 else 2 if d < 6 else 1)

    def shoot_pistol(self):
        """Tabanca: tek tek ateş, isabetli; yakın/orta mesafede iyi hasar, uzakta zayıf."""
        self.rounds -= 1
        self.cooldown = PISTOL_CD
        self.flash = 0.07
        self.events.append("shoot")
        ang = self.a + random.uniform(-0.03, 0.03)
        dx, dy = math.cos(ang), math.sin(ang)
        best, bd = None, 1e9
        for e in self.enemies:
            rx, ry = e.x - self.x, e.y - self.y
            d = rx * dx + ry * dy
            if d < 0.2 or d >= bd:
                continue
            if abs(-rx * dy + ry * dx) > 0.4 + 0.05 * d or not los(self.x, self.y, e.x, e.y, 0.45):
                continue
            best, bd = e, d
        if best:
            self.hit_enemy(best, 2 if bd < 4.5 else 1)

    def punch_hit(self):
        """Goril protez: cephane gerektirmez, çok yakından ağır vurur ve düşmanı geri savurur."""
        self.cooldown = PUNCH_CD
        self.punch = 0.3
        self.punch_side ^= 1
        self.events.append("shoot")
        dx, dy = math.cos(self.a), math.sin(self.a)
        for e in self.enemies[:]:
            rx, ry = e.x - self.x, e.y - self.y
            d = math.hypot(rx, ry)
            if d > PUNCH_RANGE or (d > 0.5 and (rx * dx + ry * dy) / d < 0.6):
                continue
            if not los(self.x, self.y, e.x, e.y, 0.35):
                continue
            self.hit_enemy(e, 2)
            if e in self.enemies and d > 0:  # geri savur (duvara girmeden)
                for _ in range(6):
                    nx, ny = e.x + rx / d * 0.1, e.y + ry / d * 0.1
                    if blocked(nx, e.y, 0.3) or blocked(e.x, ny, 0.3):
                        break
                    e.x, e.y = nx, ny

    def slash(self):
        """Lazer katana: pil harcar; önündeki yarım daire içindeki herkesi biçer, plazma toplarını geri çevirir."""
        self.battery -= KATANA_COST
        self.cooldown = KATANA_CD
        self.swing = 0.28
        self.events.append("shoot")
        dx, dy = math.cos(self.a), math.sin(self.a)
        for e in self.enemies[:]:
            rx, ry = e.x - self.x, e.y - self.y
            d = math.hypot(rx, ry)
            if d > KATANA_RANGE or (d > 0.6 and (rx * dx + ry * dy) / d < 0.45):
                continue
            if los(self.x, self.y, e.x, e.y, 0.35):
                self.hit_enemy(e, 3)
        for b in self.balls[:]:
            rx, ry = b.x - self.x, b.y - self.y
            d = math.hypot(rx, ry)
            if d < KATANA_RANGE and (d < 0.6 or (rx * dx + ry * dy) / d > 0.45):
                self.balls.remove(b)

    # --- düşman hareketi
    def eject(self, e):
        """Düşman bir şekilde duvara girdiyse en yakın boş noktaya çıkar."""
        if not blocked(e.x, e.y, 0.3):
            return
        for k in range(1, 15):
            r = 0.1 * k
            for j in range(12):
                a = j * math.pi / 6
                nx, ny = e.x + math.cos(a) * r, e.y + math.sin(a) * r
                if not blocked(nx, ny, 0.3):
                    e.x, e.y = nx, ny
                    return
        e.x, e.y = int(e.x) + 0.5, int(e.y) + 0.5

    def move_enemy(self, e, vx, vy, dt):
        x0, y0 = e.x, e.y
        sp = math.hypot(vx, vy)
        if e.detour_t > 0:  # köşeye takılmıştı: kısa süre yan yoldan dolan
            e.detour_t -= dt
            vx, vy = e.detour[0] * sp, e.detour[1] * sp
        nx, ny = e.x + vx * dt, e.y + vy * dt
        if not blocked(nx, e.y, 0.3):
            e.x = nx
        if not blocked(e.x, ny, 0.3):
            e.y = ny
        for o in self.enemies:  # birbirlerinin üstüne binmesinler (duvara itmeden)
            if o is not e:
                ox, oy = e.x - o.x, e.y - o.y
                d = math.hypot(ox, oy)
                if 0 < d < 0.6:
                    px, py = ox / d * 0.02, oy / d * 0.02
                    if not blocked(e.x + px, e.y, 0.3):
                        e.x += px
                    if not blocked(e.x, e.y + py, 0.3):
                        e.y += py
        self.eject(e)
        moved = math.hypot(e.x - x0, e.y - y0)
        if sp > 0 and moved < 0.25 * sp * dt:  # gitmek istiyor ama gidemiyor
            e.stuck += dt
            if e.stuck > 0.35 and e.detour_t <= 0:
                s = random.choice((-1, 1))
                e.detour = (-vy / sp * s, vx / sp * s)  # hareketine dik yön
                e.detour_t, e.stuck = 0.6, 0.0
        else:
            e.stuck = max(0.0, e.stuck - 2 * dt)
        e.phase += moved * 5.0  # adım uzunluğu ≈ 1.25 birim

    def update_enemy(self, e, dt):
        e.flash = max(0.0, e.flash - dt)
        e.cool = max(0.0, e.cool - dt)
        if e.burn > 0:  # yanıyor: kıpırdamaz, saldırmaz; süre bitince ölür
            e.burn -= dt
            if e.burn <= 0:
                self.hit_enemy(e, 999)
            return
        rx, ry = self.x - e.x, self.y - e.y
        d = math.hypot(rx, ry) or 0.001
        ux, uy = rx / d, ry / d
        sp = KINDS[e.kind]["speed"]
        if e.kind == "brawler":
            if d > 0.8:
                self.move_enemy(e, ux * sp, uy * sp, dt)
            elif e.cool <= 0:
                e.cool = 0.9
                self.damage(10)
        else:
            if d > 5.5:
                self.move_enemy(e, ux * sp, uy * sp, dt)
            elif d < 3.0:
                self.move_enemy(e, -ux * sp, -uy * sp, dt)
            if e.cool <= 0 and d < 12 and los(e.x, e.y, self.x, self.y, 0.0):
                e.cool = random.uniform(2.0, 3.0)
                self.balls.append(Ball(e.x, e.y, ux * 4.5, uy * 4.5))

    def update_balls(self, dt):
        for b in self.balls[:]:
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.life -= dt
            if b.life <= 0 or solid(b.x, b.y):
                self.balls.remove(b)
            elif math.hypot(b.x - self.x, b.y - self.y) < 0.45:
                self.balls.remove(b)
                self.damage(14)

    def damage(self, n):
        if self.state != "playing":
            return
        self.hp -= n
        self.hurt = 0.3
        self.events.append("hurt")
        if self.hp <= 0:
            self.hp = 0
            self.state = "dead"
            self.events.append("dead")


# ===================================================================== görüntü (Qt)
COLS = 160
SCALE = 4
WIN_W = COLS * SCALE
VIEW_H = 360
HUD_H = 64
WIN_H = VIEW_H + HUD_H
NEON = [(255, 40, 200), (40, 230, 255), (255, 220, 60), (120, 255, 120)]
WIN_COLORS = [(255, 205, 110), (120, 220, 255), (255, 90, 200)]
PX_PER_RAD = 435  # ufuk çizgisini dönüşle kaydırmak için: 1 radyan ≈ kaç piksel


def make_skyline(seed, total, hmin, hmax, wmin, wmax):
    r = random.Random(seed)
    out, x = [], 0
    while x < total:
        w, h = r.randint(wmin, wmax), r.randint(hmin, hmax)
        wins = [(r.random(), r.random(), r.randint(0, 2)) for _ in range(max(3, w * h // 1400))]
        roof = NEON[r.randint(0, 3)] if r.random() < 0.4 else None
        out.append((x, w, h, roof, wins))
        x += w + r.randint(0, 6)
    return out


NEAR_TOTAL = round(2 * math.pi * PX_PER_RAD)
FAR_TOTAL = round(NEAR_TOTAL * 0.6)
SKY_NEAR = make_skyline(11, NEAR_TOTAL, 70, 165, 45, 95)
SKY_FAR = make_skyline(5, FAR_TOTAL, 40, 120, 30, 70)


def hsh(a, b, c):
    return ((a * 73856093) ^ (b * 19349663) ^ (c * 83492791)) & 0xFFFF


def shade(rgb, f):
    return QColor(*(max(0, min(255, int(c * f))) for c in rgb))


def band(p, y0, y1, c0, c1, n=8):
    h = (y1 - y0) / n
    for i in range(n):
        f = i / (n - 1)
        col = QColor(*(int(c0[j] + (c1[j] - c0[j]) * f) for j in range(3)))
        p.fillRect(0, int(y0 + i * h), WIN_W, int(h) + 2, col)


def draw_fist(p, x, y, sc, sign, rot):
    """Tek bir mekanik goril yumruğu (arkadan görünüş): boğum plakaları, neon çizgi, başparmak, kısa bilek manşeti."""
    steel, dark, light = QColor(70, 74, 90), QColor(24, 26, 34), QColor(150, 158, 174)
    neon = QColor(255, 40, 200)
    p.save()
    p.translate(x, y)
    p.rotate(rot)
    p.scale(sc * sign, sc)                              # sign=-1: sol yumruk (başparmak içe bakar)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(dark)                                    # bilek manşeti
    p.drawRoundedRect(QRectF(-34, 30, 68, 22), 6, 6)
    p.setBrush(neon)
    p.drawRect(QRectF(-34, 36, 68, 3))
    p.setBrush(dark)                                    # gövde gölgesi
    p.drawRoundedRect(QRectF(-48, -46, 96, 88), 16, 16)
    p.setBrush(steel)
    p.drawRoundedRect(QRectF(-45, -44, 90, 82), 15, 15)
    p.setBrush(light)                                   # ışık vuran kenar
    p.drawRect(QRectF(-45, -30, 5, 58))
    p.setBrush(dark)                                    # el sırtı plakası
    p.drawRoundedRect(QRectF(-26, -4, 52, 34), 6, 6)
    p.setBrush(neon)
    p.drawRect(QRectF(-3, 0, 6, 26))
    for i in range(4):                                  # 4 parmak boğumu (üstte, öne dönük)
        bx = -42 + i * 21
        p.setBrush(dark)
        p.drawRoundedRect(QRectF(bx - 1, -60, 22, 34), 8, 8)
        p.setBrush(light)
        p.drawRoundedRect(QRectF(bx + 1, -58, 18, 28), 7, 7)
        p.setBrush(steel)
        p.drawRect(QRectF(bx + 3, -48, 14, 3))
        p.setBrush(neon)
        p.drawRect(QRectF(bx + 7, -57, 6, 3))
    p.setBrush(light)                                   # başparmak
    p.drawPolygon(QPolygonF([QPointF(-45, -10), QPointF(-70, 2), QPointF(-66, 24), QPointF(-45, 22)]))
    p.setBrush(dark)
    p.drawRect(QRectF(-62, 6, 14, 3))
    p.restore()


class GameWindow(QWidget):
    finished = pyqtSignal(int, int)  # öldürme, dalga

    def __init__(self, name="Mermi", sound=None):
        super().__init__(None)
        self.name = name
        self.sound = sound
        self.setWindowTitle(f"{TITLE} — {SUBTITLE}")
        self.setFixedSize(WIN_W, WIN_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.eng = Engine()
        self.keys = set()
        self.reported = False
        self.t = 0.0
        self.last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.frame)
        self.timer.start(25)

    # --- döngü
    def frame(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.last)
        self.last = now
        self.t += dt
        k = self.keys
        inp = Inp(
            (Qt.Key.Key_W in k or Qt.Key.Key_Up in k) - (Qt.Key.Key_S in k or Qt.Key.Key_Down in k),
            (Qt.Key.Key_D in k) - (Qt.Key.Key_A in k),
            (Qt.Key.Key_Right in k) - (Qt.Key.Key_Left in k),
            Qt.Key.Key_Space in k or Qt.Key.Key_Control in k,
            Qt.Key.Key_Q in k,
        )
        self.eng.update(dt, inp)
        if self.sound:
            for ev in self.eng.events:
                self.sound(ev)
        self.update()

    def report(self):
        if not self.reported:
            self.reported = True
            self.finished.emit(self.eng.kills, self.eng.wave)

    def restart(self):
        self.report()
        self.reported = False
        self.eng.reset()

    # --- giriş
    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif self.eng.state == "dead" and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.close()
        elif self.eng.state == "dead" and key == Qt.Key.Key_R:
            self.restart()
        elif key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4):
            self.eng.select({Qt.Key.Key_1: "fists", Qt.Key.Key_2: "katana", Qt.Key.Key_3: "pistol", Qt.Key.Key_4: "shotgun"}[key])
        elif key == Qt.Key.Key_F:
            self.eng.cycle(1)
        else:
            self.keys.add(key)

    def keyReleaseEvent(self, e):
        if not e.isAutoRepeat():
            self.keys.discard(e.key())

    def focusOutEvent(self, e):
        self.keys.clear()
        super().focusOutEvent(e)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.eng.cycle(-1 if d > 0 else 1)

    def mousePressEvent(self, e):
        self.keys.add(Qt.Key.Key_Space)

    def mouseReleaseEvent(self, e):
        self.keys.discard(Qt.Key.Key_Space)

    def closeEvent(self, e):
        self.timer.stop()
        self.report()
        e.accept()

    # --- çizim
    def paintEvent(self, _):
        p = QPainter(self)
        eng = self.eng
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        self.draw_backdrop(p)

        cols = eng.cast(COLS)
        zbuf = [c[0] for c in cols]
        half = VIEW_H // 2
        for i, (perp, side, tile, wx, cell) in enumerate(cols):
            lh = int(VIEW_H / perp)
            y0 = max(0, half - lh // 2)
            y1 = min(VIEW_H, half + lh // 2)
            if y1 > y0:
                self.draw_wall(p, i, perp, side, tile, wx, cell, half, lh, y0, y1)

        self.draw_sprites(p, zbuf)
        self.draw_gun(p)

        if eng.hurt > 0:
            p.fillRect(0, 0, WIN_W, VIEW_H, QColor(200, 0, 0, int(130 * eng.hurt / 0.3)))
        if eng.flash > 0.06:
            p.fillRect(0, 0, WIN_W, VIEW_H, QColor(255, 220, 120, 40))

        # artı işareti
        p.setPen(QPen(QColor(255, 255, 255, 190), 2))
        cx, cy = WIN_W // 2, VIEW_H // 2
        p.drawLine(cx - 8, cy, cx - 3, cy)
        p.drawLine(cx + 3, cy, cx + 8, cy)
        p.drawLine(cx, cy - 8, cx, cy - 3)
        p.drawLine(cx, cy + 3, cx, cy + 8)

        target = eng.hack_target() if eng.state == "playing" and eng.stacks >= HACK_COST else None
        if target is not None:                                # hack hazır ve hedef var: neon mavi köşeli parantez
            p.setPen(QPen(QColor(125, 240, 255, 230), 2))
            for sx_, sy_ in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                px_, py_ = cx + sx_ * 20, cy + sy_ * 20
                p.drawLine(px_, py_, px_ - sx_ * 8, py_)
                p.drawLine(px_, py_, px_, py_ - sy_ * 8)

        self.draw_hud(p)
        self.draw_text(p)
        self.draw_hack(p)
        p.end()

    def draw_hack(self, p):
        """Sol üstte HACK barı: konuşma balonlarıyla aynı HUD çerçeve dili, neon mavi. Her öldürme 1 hücre; 3 hücre = hazır."""
        eng = self.eng
        x, y, w, h = 12, 38, 238, 34
        neon, dim = QColor(125, 240, 255), QColor(46, 92, 108)
        ready = eng.stacks >= HACK_COST
        pulse = 0.65 + 0.35 * math.sin(self.t * 8) if ready else 1.0
        hud.paint_frame(p, x, y, w, h, "#38E8FF", 2)
        f = QFont("Monospace", 8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(neon if ready else QColor(110, 190, 205))
        p.drawText(QPointF(x + 14, y + 22), "Q HACK")
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(MAX_STACKS):
            cx_ = x + 72 + i * 25
            cy_ = y + 9
            shape = QPolygonF([QPointF(cx_ + 5, cy_), QPointF(cx_ + 22, cy_), QPointF(cx_ + 17, cy_ + 16), QPointF(cx_, cy_ + 16)])
            on = i < eng.stacks
            if on:
                a = int(255 * (pulse if i < HACK_COST and ready else 1.0))
                p.setBrush(QColor(125, 240, 255, a))
            else:
                p.setBrush(QColor(10, 30, 40, 200))
            p.drawPolygon(shape)
            p.setPen(QPen(neon if on else dim, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(shape)
            if on:
                p.setPen(QPen(QColor(255, 255, 255, 140), 1))
                p.drawLine(QPointF(cx_ + 8, cy_ + 3), QPointF(cx_ + 19, cy_ + 3))
            p.setPen(Qt.PenStyle.NoPen)
        p.setPen(QPen(QColor(125, 240, 255, 150), 1))         # ilk 3 hücrenin altına "maliyet" çizgisi
        p.drawLine(QPointF(x + 77, y + 29), QPointF(x + 72 + 2 * 25 + 17, y + 29))
        p.setPen(Qt.PenStyle.NoPen)

    def draw_backdrop(self, p):
        """Gece şehri: neon gökyüzü, iki katmanlı gökdelen silueti, ıslak asfalt."""
        horizon = VIEW_H // 2
        band(p, 0, horizon, (8, 5, 28), (125, 30, 115))
        for layer, total, k, body, near in ((SKY_FAR, FAR_TOTAL, 0.6, (46, 20, 74), False),
                                            (SKY_NEAR, NEAR_TOTAL, 1.0, (14, 9, 32), True)):
            off = (-self.eng.a * PX_PER_RAD * k) % total
            for bx, w, h, roof, wins in layer:
                sx = int((bx - off) % total)
                for x0 in (sx, sx - total):
                    if x0 >= WIN_W or x0 + w <= 0:
                        continue
                    top = horizon - h
                    p.fillRect(x0, top, w, h, QColor(*body))
                    if roof:
                        p.fillRect(x0, top, w, 2, QColor(*roof))
                    if near:
                        for fx, fy, ci in wins:
                            p.fillRect(x0 + int(fx * (w - 3)), top + 5 + int(fy * (h - 10)), 2, 3,
                                       QColor(*WIN_COLORS[ci]))
        band(p, horizon, VIEW_H, (70, 26, 92), (6, 5, 12))

    def draw_wall(self, p, i, perp, side, tile, wx, cell, half, lh, y0, y1):
        x = i * SCALE
        f = max(0.25, 1.0 - perp / 14.0) * (0.75 if side else 1.0)
        top = half - lh // 2

        def rect(fy, fh, color):
            ya = max(y0, top + int(lh * fy))
            yb = min(y1, top + int(lh * (fy + fh)) + 1)
            if yb > ya:
                p.fillRect(x, ya, SCALE, yb - ya, color)

        if tile == 1:  # gökdelen cephesi: pencereler
            rect(0, 1, shade((46, 50, 74), f))
            m = (wx * 5) % 1.0
            if m < 0.07:
                rect(0, 1, shade((22, 24, 38), f))
            elif m > 0.2 and perp < 12:
                col = int(wx * 5)
                for r in range(5):
                    h = hsh(cell, col, r) % 7
                    if h < 3:
                        rect(0.08 + r * 0.18, 0.11, shade(WIN_COLORS[h], f + 0.3))
                    else:
                        rect(0.08 + r * 0.18, 0.11, shade((14, 16, 26), f))
        elif tile == 2:  # neon tabela
            rect(0, 1, shade((26, 12, 40), f))
            g = shade(NEON[cell % 4], max(0.75, f + 0.35))
            rect(0.05, 0.04, g)
            rect(0.91, 0.04, g)
            if ((int(wx * 9) * 5 + cell) % 3 and (wx * 9) % 1.0 < 0.7
                    and (int(self.t * 2.5) + cell) % 13):  # ara sıra titrer
                rect(0.22, 0.16, g)
                rect(0.5, 0.16, g)
        else:  # teknik / holografik panel
            rect(0, 1, shade((18, 44, 60), f))
            if (wx * 4) % 1.0 < 0.05:
                rect(0, 1, shade((8, 20, 30), f))
            rect(0.45, 0.07, shade((90, 255, 240), max(0.7, f + 0.3)))
            rect(0.94, 0.03, shade((255, 40, 200), max(0.7, f + 0.3)))

    def draw_sprites(self, p, zbuf):
        eng = self.eng
        items = []
        for kind, lst in (("enemy", eng.enemies), ("pickup", eng.pickups), ("ball", eng.balls)):
            for o in lst:
                pr = eng.project(o.x, o.y, COLS)
                if pr:
                    items.append((pr[1], pr[0], kind, o))
        items.sort(key=lambda it: -it[0])
        half = VIEW_H // 2
        for ty, sx, kind, o in items:
            f = max(0.35, 1.0 - ty / 14.0)
            if kind == "enemy":
                self.draw_enemy(p, o, sx, ty, f, zbuf, half)
            elif kind == "pickup":
                self.draw_pickup(p, o, sx, ty, f, zbuf, half)
            else:
                self.draw_ball(p, sx, ty, zbuf, half)

    def strips(self, sx, ty, size_px, zbuf):
        """Sprite'ın görünen sütunlarını (sütun, u) olarak verir."""
        wcols = max(1, size_px // SCALE)
        left = int(sx - wcols / 2)
        for k in range(wcols):
            c = left + k
            if 0 <= c < COLS and zbuf[c] > ty:
                yield c, (k + 0.5) / wcols

    def draw_enemy(self, p, en, sx, ty, f, zbuf, half):
        """Terminatör tarzı krom iskelet robot: kafatası, kaburga, omurga, ince uzuvlar. Yürürken bacaklar/kollar sallanır."""
        size = int(VIEW_H / ty)
        top = half - size // 2
        brawler = en.kind == "brawler"
        accent = QColor(255, 50, 90) if brawler else QColor(60, 200, 255)
        hit = en.flash > 0
        hot = en.burn > 0
        chrome = QColor(255, 235, 235) if hit else shade((255, 170, 90) if hot else (176, 184, 198), f)
        steel = QColor(255, 205, 205) if hit else shade((220, 90, 40) if hot else (92, 98, 112), f)
        dark = shade((30, 32, 42), f)
        red, white = QColor(255, 30, 30), QColor(255, 255, 255)
        sw = math.sin(en.phase)
        bob = abs(sw) * 0.025                        # yürürken gövde hafif zıplar
        lift = (max(0.0, sw) * 0.07, max(0.0, -sw) * 0.07)  # ayak kaldırma (sol, sağ)
        swing = sw * 0.05                            # kol sallama

        for c, u in self.strips(sx, ty, size, zbuf):
            x = c * SCALE

            def R(y0, y1, col, dy=0.0):
                p.fillRect(x, int(top + size * (y0 + dy)), SCALE, max(1, int(size * (y1 - y0))), col)

            for k, mid in ((0, 0.41), (1, 0.59)):    # bacaklar
                w, lf = abs(u - mid), lift[k]
                if w < 0.03:
                    R(0.60, 0.78, steel)
                    R(0.78 - lf, 0.955 - lf, chrome if w < 0.014 else steel)
                    R(0.765 - lf * 0.5, 0.79 - lf * 0.5, dark)  # diz
                if w < 0.045:
                    R(0.955 - lf, 0.99 - lf, dark)   # ayak
            if 0.38 < u < 0.62:                      # leğen
                R(0.52, 0.58, dark if abs(u - 0.5) < 0.03 else steel, bob)
            if 0.485 < u < 0.515:                    # omurga
                R(0.2, 0.58, chrome if abs(u - 0.5) < 0.007 else steel, bob)
            if 0.33 < u < 0.67:                      # kaburga kafesi (aralar boş: arkası görünür)
                if u < 0.36 or u > 0.64:
                    R(0.27, 0.47, chrome, bob)
                for ry in (0.28, 0.33, 0.38, 0.43):
                    R(ry, ry + 0.022, chrome, bob)
            if 0.25 < u < 0.34 or 0.66 < u < 0.75:  # omuz
                R(0.26, 0.31, dark, bob)
            if 0.255 < u < 0.285:                    # sol kol
                R(0.31, 0.47, steel, bob + swing)
            if 0.245 < u < 0.275:
                R(0.47, 0.62, chrome, bob + swing)
            if 0.24 < u < 0.28:
                R(0.62, 0.66, dark, bob + swing)
            if 0.715 < u < 0.745:                    # sağ kol
                R(0.31, 0.47, steel, bob - swing)
            if brawler:
                if 0.745 <= u < 0.80:                # enerji kılıcı
                    R(0.17, 0.72, accent, bob)
                    if 0.765 < u < 0.78:
                        R(0.19, 0.70, white, bob)
            else:
                if 0.70 < u < 0.98:                  # plazma tüfeği
                    R(0.43, 0.48, dark, bob)
                    if u > 0.92:
                        R(0.43, 0.455, accent, bob)
            # kafatası
            if 0.40 < u < 0.60:
                R(0.03 if 0.43 < u < 0.57 else 0.06, 0.2, chrome, bob)
                if 0.42 < u < 0.47 or 0.53 < u < 0.58:
                    R(0.085, 0.155, dark, bob)
                    R(0.10, 0.14, red, bob)          # parlayan kırmızı göz
                if 0.49 < u < 0.51:
                    R(0.15, 0.18, dark, bob)
                if 0.43 < u < 0.57:
                    R(0.19, 0.23, chrome if int(u * 60) % 2 else dark, bob)  # çene / dişler
        if hot:
            self.draw_flames(p, sx, top, size, ty, zbuf)

    def draw_flames(self, p, sx, top, size, ty, zbuf):
        """Hack ile yanan düşmanın üzerinde dalgalanan alevler ve kıvılcımlar."""
        c0 = int(sx)
        if not 0 <= c0 < COLS or zbuf[c0] < ty:
            return
        base = top + size * 0.97
        sx = sx * SCALE                                           # sütun -> piksel
        p.setPen(Qt.PenStyle.NoPen)
        for layer, (col, hs) in enumerate(((QColor(255, 90, 20, 200), 1.0), (QColor(255, 170, 40, 220), 0.7),
                                           (QColor(255, 240, 150, 230), 0.4))):
            for i in range(9):
                fx = sx + (i - 4) * size * 0.075
                wob = math.sin(self.t * 11 + i * 1.9 + layer)
                hgt = size * hs * (0.42 + 0.3 * abs(math.sin(self.t * 9 + i * 2.3))) * (1.0 - abs(i - 4) * 0.08)
                wid = size * 0.05
                p.setBrush(col)
                p.drawPolygon(QPolygonF([QPointF(fx - wid, base), QPointF(fx + wid, base),
                                         QPointF(fx + wob * size * 0.025, base - hgt)]))
        p.setBrush(QColor(255, 220, 120, 230))
        for i in range(6):                                      # kıvılcımlar
            ph = (self.t * 1.7 + i * 0.37) % 1.0
            p.drawRect(QRectF(sx + math.sin(i * 5.1 + self.t * 3) * size * 0.25, base - ph * size * 1.1, 3, 3))

    def draw_pickup(self, p, pk, sx, ty, f, zbuf, half):
        full = int(VIEW_H / ty)
        size = max(4, int(full * (0.34 if pk.kind.startswith("w_") else 0.26)))
        y = half + full // 2 - size
        k, ff = pk.kind, f + 0.15
        for c, u in self.strips(sx, ty, size, zbuf):
            x = c * SCALE
            if k == "ammo":      # pompalı kartuşu: camgöbeği kutu, macenta bant
                edge = u < 0.12 or u > 0.88
                p.fillRect(x, y, SCALE, size, shade((20, 70, 90) if edge else (60, 210, 235), ff))
                if 0.4 < u < 0.6:
                    p.fillRect(x, y, SCALE, size, shade((255, 40, 200), ff))
            elif k == "rounds":  # tüfek şarjörü: sarı kutu, koyu kurşun dizisi
                edge = u < 0.1 or u > 0.9
                p.fillRect(x, y, SCALE, size, shade((90, 70, 0) if edge else (255, 210, 26), ff))
                if int(u * 7) % 2 == 1 and not edge:
                    p.fillRect(x, y + int(size * 0.2), SCALE, int(size * 0.6), shade((60, 45, 10), ff))
            elif k == "battery":  # katana pili: koyu silindir, kırmızı bant, beyaz kapak
                if 0.2 < u < 0.8:
                    p.fillRect(x, y, SCALE, size, shade((38, 36, 46), ff))
                    p.fillRect(x, y + int(size * 0.4), SCALE, max(2, int(size * 0.2)), shade((255, 40, 70), ff))
                    p.fillRect(x, y, SCALE, max(2, int(size * 0.14)), shade((235, 235, 240), ff))
            elif k.startswith("w_"):  # silah kasası: silahın renginde, beyaz çerçeveli, yüzer
                col = {"w_katana": (255, 50, 70), "w_pistol": (255, 214, 40), "w_shotgun": (60, 230, 255)}[k]
                edge = u < 0.1 or u > 0.9
                bob_ = int(math.sin(self.t * 4 + pk.x * 3) * size * 0.08)
                yy = y - int(size * 0.35) + bob_
                p.fillRect(x, yy, SCALE, size, shade((255, 255, 255) if edge else (26, 20, 40), 1.0))
                if not edge:
                    p.fillRect(x, yy + int(size * 0.1), SCALE, int(size * 0.8), shade(col, ff))
                    if 0.2 < u < 0.8:
                        p.fillRect(x, yy + int(size * 0.38), SCALE, max(2, int(size * 0.24)), shade((20, 16, 30), 1.0))
            else:
                p.fillRect(x, y, SCALE, size, shade((235, 235, 235), ff))
                if 0.38 < u < 0.62:
                    p.fillRect(x, y, SCALE, size, shade((210, 30, 40), ff))
                elif 0.15 < u < 0.85:
                    p.fillRect(x, y + int(size * 0.38), SCALE, max(2, int(size * 0.24)), shade((210, 30, 40), ff))

    def draw_ball(self, p, sx, ty, zbuf, half):
        size = max(4, int(VIEW_H / ty * 0.3))
        for c, u in self.strips(sx, ty, size, zbuf):
            hh = math.sqrt(max(0.0, 1 - (2 * u - 1) ** 2))
            p.fillRect(c * SCALE, int(half - size * 0.5 * hh), SCALE, int(size * hh) + 1, QColor(255, 40, 200))
            p.fillRect(c * SCALE, int(half - size * 0.25 * hh), SCALE, int(size * 0.5 * hh) + 1, QColor(255, 255, 255))

    def draw_gun(self, p):
        {"fists": self.draw_fists, "shotgun": self.draw_shotgun, "pistol": self.draw_pistol,
         "katana": self.draw_katana}[self.eng.weapon](p)

    def draw_fists(self, p):
        """Goril protezin yalnızca yumrukları: boşta alt köşelerde durur, vururken ekranın ortasına fırlar ve büyür."""
        eng = self.eng
        bob = math.sin(self.t * 9) * 4 if eng.moving else 0
        cx = WIN_W // 2
        k = 1 - eng.punch / 0.3 if eng.punch > 0 else 0.0
        if k < 0.4:                                     # hızlı fırla (yavaşlayarak), sonra geri çekil
            u = k / 0.4
            amt = 1 - (1 - u) ** 2
        else:
            amt = max(0.0, 1 - (k - 0.4) / 0.6) ** 1.5
        for side in (1, 0):                             # aktif olmayan önce çizilir, vuran en üstte
            sign = -1 if side == 0 else 1
            a = amt if (eng.punch > 0 and eng.punch_side == side) else 0.0
            x = cx + sign * (190 - 150 * a)
            y = VIEW_H - 52 + bob * (1 - a) - 130 * a
            sc = 1.35 + 1.0 * a
            if a > 0.25:                                # hız çizgileri
                for dx in (-30, 0, 30):
                    p.fillRect(int(x + dx * sc * 0.6 - 3), int(y + 40 * sc), 6, int(70 * a * sc), QColor(180, 240, 255, 60))
            draw_fist(p, x, y, sc, sign, -sign * 10 * (1 - a))
        if eng.punch > 0 and 0.32 < k < 0.58:           # temas anı: sarsıntı + halka
            f = 1 - abs(k - 0.45) / 0.13
            p.fillRect(0, 0, WIN_W, VIEW_H, QColor(255, 255, 255, int(46 * f)))
            p.setPen(QPen(QColor(255, 120, 230, int(220 * f)), 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, VIEW_H * 0.5), 26 + 70 * (1 - f), 20 + 52 * (1 - f))
            p.setPen(Qt.PenStyle.NoPen)

    def draw_pistol(self, p):
        """Arkadan görünüş, alt ortadan namlu yukarı (pompalı gibi): siyah dokulu kabze, gri çerçeve, yıpranmış zeytin-sarı
        kızak + optik bloğu, ortada kırmızı namlu rayı."""
        eng = self.eng
        bob = math.sin(self.t * 9) * 4 if eng.moving else 0
        kick = 12 * eng.flash / 0.07 if eng.flash > 0 else 0
        cx, by = WIN_W // 2, VIEW_H + 40 + bob + kick
        gray, gray_d, gray_l = QColor(168, 170, 176), QColor(104, 106, 114), QColor(214, 216, 220)
        black, grip_l = QColor(24, 24, 28), QColor(62, 62, 70)
        yel, yel_d, yel_l = QColor(196, 190, 62), QColor(128, 124, 36), QColor(228, 222, 100)
        red, red_d = QColor(160, 26, 32), QColor(92, 14, 18)

        def poly(pts, col):
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(cx + x, by + y) for x, y in pts]))

        def rect(x, y, w, h, col):
            p.setBrush(col)
            p.drawRect(QRectF(cx + x, by + y, w, h))

        p.setPen(Qt.PenStyle.NoPen)
        poly([(-28, 0), (28, 0), (24, -74), (-24, -74)], black)             # kabze
        for r in range(6):                                                   # dokulu tutuş
            for c in range(5):
                rect(-19 + c * 8, -8 - r * 11, 4, 3, grip_l)
        rect(-28, -70, 4, 70, grip_l)
        poly([(-34, -74), (34, -74), (30, -114), (-30, -114)], gray)        # çerçeve
        rect(-34, -74, 6, 40, gray_l)
        rect(28, -74, 6, 40, gray_d)
        rect(-12, -66, 24, 4, gray_d)                                        # tetik bölgesi
        rect(-9, -60, 18, 6, black)
        rect(-16, -140, 32, 28, gray_d)                                      # alt fener (ön)
        rect(-6, -139, 12, 4, QColor(255, 250, 200) if eng.flash > 0 else QColor(190, 190, 150))
        poly([(-36, -112), (36, -112), (26, -198), (-26, -198)], yel)       # kızak
        poly([(-36, -112), (-28, -112), (-20, -198), (-26, -198)], yel_l)
        poly([(28, -112), (36, -112), (26, -198), (20, -198)], yel_d)
        for i in range(5):                                                   # kızak tırtılları
            rect(-26 + i * 11, -128, 5, 14, black)
        poly([(-9, -126), (9, -126), (6, -208), (-6, -208)], red)           # kırmızı namlu / ray
        rect(-1, -206, 2, 80, red_d)
        rect(8, -160, 28, 36, yel)                                           # yıpranmış optik bloğu
        rect(8, -160, 28, 4, yel_l)
        for i in range(3):
            rect(12, -150 + i * 8, 20, 3, black)
        rect(-8, -214, 16, 8, black)                                         # namlu ağzı
        rect(-1.5, -220, 3, 6, black)
        for (ox, oy, w, h, c) in ((-30, -118, 8, 6, gray), (10, -134, 9, 6, gray), (-12, -176, 7, 9, gray),
                                  (14, -190, 6, 7, gray), (22, -156, 8, 5, gray), (-22, -150, 6, 10, gray),
                                  (16, -100, 10, 5, gray_l), (-30, -90, 5, 14, gray_d), (-18, -50, 8, 5, grip_l)):
            rect(ox, oy, w, h, c)                                            # dökülmüş boya
        p.setPen(QPen(QColor(80, 76, 30), 1))
        for (x0, y0, x1, y1) in ((-20, -130, -4, -112), (12, -190, 24, -170), (-6, -90, 14, -80), (-26, -160, -12, -142)):
            p.drawLine(QPointF(cx + x0, by + y0), QPointF(cx + x1, by + y1))
        p.setPen(Qt.PenStyle.NoPen)
        if eng.flash > 0.03:
            p.setBrush(QColor(255, 200, 40, 220))
            p.drawEllipse(QPointF(cx, by - 222), 26, 19)
            p.setBrush(QColor(255, 250, 200))
            p.drawEllipse(QPointF(cx, by - 222), 13, 10)

    @staticmethod
    def blade_geometry(px, py, th, r0=36, r1=290, w0=30.0, bow=34.0, n=14):
        """Hafif kıvrık katana bıçağı: (sırt noktaları, kesici kenar noktaları, orta hat). th: bıçağın yönü."""
        ux, uy = math.cos(th), math.sin(th)
        nx, ny = -uy, ux
        spine, edge, mid = [], [], []
        for i in range(n + 1):
            s_ = i / n
            r = r0 + (r1 - r0) * s_
            off = bow * s_ * s_                          # uca doğru kıvrım
            w = w0 * (1 - 0.82 * s_ ** 1.4) * 0.5
            cx_, cy_ = px + ux * r + nx * off, py + uy * r + ny * off
            spine.append(QPointF(cx_ + nx * w, cy_ + ny * w))
            edge.append(QPointF(cx_ - nx * w, cy_ - ny * w))
            mid.append((cx_, cy_, nx, ny, w))
        return spine, edge, mid

    def draw_katana(self, p):
        """Pil ile çalışan kırmızı katana: parlak kırmızı gövde, beyaz çizgi hattı, gümüş kesici kenar, siyah-gri mekanik sap."""
        eng = self.eng
        bob = math.sin(self.t * 9) * 4 if eng.moving else 0
        px, py = WIN_W // 2 + 140, VIEW_H - 6 + bob
        if eng.swing > 0:
            s = 1 - eng.swing / 0.28
            s = 1 - (1 - s) ** 2                         # hızlı başla, yavaş bitir
            th = math.radians(-15 - 150 * s)             # sağdan sola yay
            trail = [math.radians(-15 - 150 * max(0.0, s - 0.1 * k)) for k in (3, 2, 1)]
        else:
            th = math.radians(-104 + math.sin(self.t * 2.2) * 2.5)
            trail = []
        p.setPen(Qt.PenStyle.NoPen)
        for k, t_ in enumerate(trail):                   # sallanırken kırmızı iz
            sp, ed, _ = self.blade_geometry(px, py, t_)
            p.setBrush(QColor(255, 50, 60, 26 + 20 * k))
            p.drawPolygon(QPolygonF(sp + ed[::-1]))
        spine, edge, mid = self.blade_geometry(px, py, th)
        p.setBrush(QColor(196, 18, 32))                  # kırmızı gövde
        p.drawPolygon(QPolygonF(spine + edge[::-1]))
        # kesici kenar: parlak kırmızı şerit (bıçağın %28'i); sırt tarafı: gümüş-gri şerit (%25)
        e_in = [QPointF(e.x() + (s_.x() - e.x()) * 0.28, e.y() + (s_.y() - e.y()) * 0.28) for s_, e in zip(spine, edge)]
        p.setBrush(QColor(240, 32, 48))
        p.drawPolygon(QPolygonF(edge + e_in[::-1]))
        p.setBrush(QColor(196, 200, 210))
        sp_in = [QPointF(s_.x() + (e.x() - s_.x()) * 0.25, s_.y() + (e.y() - s_.y()) * 0.25) for s_, e in zip(spine, edge)]
        p.drawPolygon(QPolygonF(spine + sp_in[::-1]))
        # beyaz çizgi hattı: bıçak boyunca ince çerçeve, kökte dik dönüş
        p.setPen(QPen(QColor(255, 250, 250), 2))
        pts = [QPointF(m[0] + m[2] * m[4] * 0.1, m[1] + m[3] * m[4] * 0.1) for m in mid[1:11]]
        for a_, b_ in zip(pts, pts[1:]):
            p.drawLine(a_, b_)
        m0 = mid[1]
        p.drawLine(QPointF(m0[0] + m0[2] * m0[4] * 0.1, m0[1] + m0[3] * m0[4] * 0.1),
                   QPointF(m0[0] - m0[2] * m0[4] * 0.55, m0[1] - m0[3] * m0[4] * 0.55))
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))    # bıçak ucu parlaması
        p.drawLine(spine[-3], spine[-1])
        p.setPen(Qt.PenStyle.NoPen)
        # sap
        ux, uy = math.cos(th), math.sin(th)
        nx, ny = -uy, ux

        def quad(r0, r1, w, col, off=0.0):
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(px + ux * r0 + nx * (w + off), py + uy * r0 + ny * (w + off)),
                                     QPointF(px + ux * r1 + nx * (w + off), py + uy * r1 + ny * (w + off)),
                                     QPointF(px + ux * r1 - nx * (w - off), py + uy * r1 - ny * (w - off)),
                                     QPointF(px + ux * r0 - nx * (w - off), py + uy * r0 - ny * (w - off))]))

        quad(-90, 36, 11, QColor(28, 28, 34))            # siyah sap gövdesi
        quad(-90, -66, 12, QColor(190, 192, 200))        # alt gri bant
        for k in range(3):
            quad(-60 + k * 20, -54 + k * 20, 12, QColor(196, 24, 36))  # kırmızı çizgiler
        quad(6, 42, 15, QColor(52, 54, 64))              # mekanik gövde / siper
        quad(26, 38, 24, QColor(40, 42, 50))             # açılı siper
        quad(31, 35, 24, QColor(196, 24, 36))
        lvl = max(0.0, min(1.0, eng.battery / MAX_BATT))  # pil göstergesi: 5 ışık
        for k in range(5):
            on = lvl > k / 5.0 + 0.02
            col = (QColor(90, 255, 170) if lvl > 0.25 else QColor(255, 90, 60)) if on else QColor(60, 60, 70)
            quad(-12 + k * 4.6, -9 + k * 4.6, 4.2, col, 0.0)

    def draw_shotgun(self, p):
        eng = self.eng
        bob = math.sin(self.t * 9) * 4 if eng.moving else 0
        kick = 16 * eng.flash / 0.12 if eng.flash > 0 else 0
        cx, by = WIN_W // 2, VIEW_H + 6 + bob + kick
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(55, 55, 62))
        p.drawRect(QRectF(cx - 20, by - 150, 17, 130))
        p.drawRect(QRectF(cx + 3, by - 150, 17, 130))
        p.setBrush(QColor(90, 90, 100))
        p.drawRect(QRectF(cx - 20, by - 150, 5, 130))
        p.drawRect(QRectF(cx + 3, by - 150, 5, 130))
        p.setBrush(QColor(110, 70, 35))
        p.drawRect(QRectF(cx - 28, by - 70, 56, 70))
        p.setBrush(QColor(80, 48, 22))
        p.drawRect(QRectF(cx - 28, by - 70, 56, 8))
        p.setBrush(QColor(60, 230, 255))
        p.drawRect(QRectF(cx - 2, by - 148, 4, 126))
        p.drawRect(QRectF(cx - 24, by - 40, 48, 3))
        if eng.flash > 0.04:
            p.setBrush(QColor(255, 150, 30, 220))
            p.drawEllipse(QPointF(cx, by - 158), 46, 34)
            p.setBrush(QColor(255, 245, 160))
            p.drawEllipse(QPointF(cx, by - 158), 26, 20)

    def draw_hud(self, p):
        eng = self.eng
        p.fillRect(0, VIEW_H, WIN_W, HUD_H, QColor(14, 10, 28))
        p.fillRect(0, VIEW_H, WIN_W, 3, QColor(60, 230, 255))
        p.fillRect(0, VIEW_H + 4, WIN_W, 1, QColor(255, 40, 200))
        small, tiny, big = QFont("Monospace", 9), QFont("Monospace", 7), QFont("Monospace", 22)
        big.setBold(True)
        label, value, color = {
            "fists": ("PROTEZ", "∞", QColor(255, 90, 220)),
            "katana": ("PİL", f"{eng.battery}%", QColor(255, 90, 110)),
            "pistol": ("KURŞUN", f"{eng.rounds}", QColor(255, 214, 40)),
            "shotgun": ("MÜHİMMAT", f"{eng.ammo}", QColor(120, 240, 255)),
        }[eng.weapon]
        low = not eng.has_resource(eng.weapon)
        p.setPen(QColor(255, 40, 200))
        p.setFont(small)
        p.drawText(QPointF(24, VIEW_H + 20), label)
        p.drawText(QPointF(WIN_W - 130, VIEW_H + 20), "CAN")
        p.setFont(big)
        p.setPen(QColor(255, 90, 70) if low else color)
        p.drawText(QPointF(24, VIEW_H + 54), value)
        p.setPen(QColor(255, 120, 110) if eng.hp < 35 else QColor(120, 255, 170))
        p.drawText(QPointF(WIN_W - 130, VIEW_H + 54), f"{eng.hp}%")
        # silah yuvaları 2x2 (üstte 1-2, altta 3-4), ikonlu; seçili olan parlak
        vals = {"fists": "∞", "katana": f"{eng.battery}%", "pistol": eng.rounds, "shotgun": eng.ammo}
        cols = {"fists": QColor(255, 90, 220), "katana": QColor(255, 90, 110),
                "pistol": QColor(255, 214, 40), "shotgun": QColor(120, 240, 255)}
        p.setFont(tiny)
        for i, w in enumerate(WEAPONS):
            x = 112 + (i % 2) * 94
            y = VIEW_H + 7 + (i // 2) * 28
            on = w == eng.weapon
            col = cols[w] if on else QColor(100, 92, 124)
            locked = w not in eng.unlocked
            if locked:
                col = QColor(62, 56, 84)
            elif not eng.has_resource(w):
                col = QColor(120, 50, 50)
            p.fillRect(x - 3, y, 90, 26, QColor(44, 26, 64) if on else QColor(22, 16, 38))
            if on:
                p.fillRect(x - 3, y, 90, 2, cols[w])
            p.setPen(col)
            p.drawText(QPointF(x + 2, y + 17), str(i + 1))
            self.draw_icon(p, w, x + 14, y + 4, col, 0.78)
            p.setPen(col)
            p.drawText(QPointF(x + 52, y + 17), "—" if locked else f"{vals[w]}")
        self.draw_face(p, WIN_W // 2, VIEW_H + 36)

    @staticmethod
    def draw_icon(p, w, x, y, col, scale=1.0):
        """Silah yuvası ikonu (≈ 40x22 px, scale ile küçülür)."""
        p.save()
        p.translate(x, y)
        p.scale(scale, scale)
        dark = QColor(col)
        dark.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        if w == 'fists':       # iki iri yumruk + pistonlar
            p.drawRoundedRect(QRectF(2, 6, 14, 13), 4, 4)
            p.drawRoundedRect(QRectF(20, 6, 14, 13), 4, 4)
            p.setBrush(dark)
            for k in range(3):
                p.drawRect(QRectF(5 + k * 4, 7, 1.5, 7))
                p.drawRect(QRectF(23 + k * 4, 7, 1.5, 7))
            p.drawRect(QRectF(6, 0, 6, 6))
            p.drawRect(QRectF(24, 0, 6, 6))
        elif w == 'katana':    # kıvrık bıçak + sap
            p.setPen(QPen(col, 2.4))
            p.drawLine(QPointF(30, 1), QPointF(34, 4))
            p.drawLine(QPointF(4, 18), QPointF(30, 1))
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            p.drawLine(QPointF(8, 15), QPointF(27, 3))
            p.setPen(QPen(dark, 3))
            p.drawLine(QPointF(0, 21), QPointF(5, 17))
        elif w == 'pistol':    # tabanca silueti
            p.drawRect(QRectF(4, 3, 28, 6))
            p.drawRect(QRectF(8, 9, 22, 4))
            p.drawPolygon(QPolygonF([QPointF(8, 9), QPointF(16, 9), QPointF(13, 21), QPointF(6, 21)]))
            p.setBrush(dark)
            p.drawRect(QRectF(30, 4, 6, 3))
        else:                  # pompalı silueti
            p.drawRect(QRectF(8, 5, 28, 3))
            p.drawRect(QRectF(8, 9, 24, 3))
            p.drawPolygon(QPolygonF([QPointF(0, 7), QPointF(10, 5), QPointF(10, 14), QPointF(2, 17)]))
            p.setBrush(dark)
            p.drawRect(QRectF(16, 12, 8, 3))
        p.restore()

    def draw_face(self, p, cx, cy):
        """Mermi suratlı HUD yüzü (Doom'daki gibi): canı azaldıkça yaralanır."""
        eng = self.eng
        dead = eng.state == "dead"
        p.setPen(QPen(QColor(70, 40, 15), 2))
        p.setBrush(QColor(196, 104, 48))
        p.drawRoundedRect(QRectF(cx - 17, cy - 30, 34, 36), 15, 15)  # uç
        p.setBrush(QColor(222, 170, 70))
        p.drawRoundedRect(QRectF(cx - 17, cy - 6, 34, 32), 4, 4)     # kovan
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))  # parlama çizgisi
        p.drawLine(QPointF(cx + 11, cy - 21), QPointF(cx + 11, cy + 19))
        if eng.hp < 66:  # yara izi
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(170, 20, 20))
            p.drawRect(QRectF(cx - 12, cy - 22, 5, 12 if eng.hp < 33 else 6))
        p.setPen(QPen(QColor(40, 25, 10), 2))
        ey = cy - 9
        for ex in (cx - 7, cx + 7):
            if dead:
                p.drawLine(QPointF(ex - 3, ey - 3), QPointF(ex + 3, ey + 3))
                p.drawLine(QPointF(ex - 3, ey + 3), QPointF(ex + 3, ey - 3))
            elif eng.hp < 33:
                p.drawLine(QPointF(ex - 3, ey), QPointF(ex + 3, ey + 1))
            else:
                p.setBrush(QColor("white"))
                p.drawEllipse(QPointF(ex, ey), 3.5, 4)
                p.setBrush(QColor(30, 20, 10))
                p.drawEllipse(QPointF(ex + 0.5, ey + 0.5), 1.6, 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if eng.hurt > 0 or dead:
            p.drawEllipse(QPointF(cx, cy + 8), 3, 4)
        elif eng.flash > 0:
            p.drawArc(QRectF(cx - 7, cy + 1, 14, 9), 200 * 16, 140 * 16)
        else:
            p.drawLine(QPointF(cx - 5, cy + 9), QPointF(cx + 5, cy + 9))

    def draw_text(self, p):
        eng = self.eng
        f = QFont("Sans", 11)
        f.setBold(True)
        p.setFont(f)
        for dx, col in ((1, QColor(0, 0, 0)), (0, QColor(255, 240, 200))):
            p.setPen(col)
            p.drawText(QPointF(10 + dx, 22 + dx), f"DALGA {eng.wave}     ÖLDÜRME {eng.kills}")
        # köşede oyun adı + alt başlık
        tf, sf = QFont("Sans", 10), QFont("Sans", 8)
        tf.setBold(True)
        for dx, c1, c2 in ((1, QColor(0, 0, 0), QColor(0, 0, 0)), (0, QColor(255, 40, 200), QColor(120, 240, 255))):
            p.setFont(tf)
            p.setPen(c1)
            p.drawText(QRectF(0 + dx, 8 + dx, WIN_W - 10, 20), Qt.AlignmentFlag.AlignRight, TITLE.upper())
            p.setFont(sf)
            p.setPen(c2)
            p.drawText(QRectF(0 + dx, 24 + dx, WIN_W - 10, 16), Qt.AlignmentFlag.AlignRight, SUBTITLE.lower())
        if eng.notice_t > 0 and eng.state == "playing":
            nf = QFont("Sans", 15)
            nf.setBold(True)
            p.setFont(nf)
            warn = eng.notice.startswith("HACK")
            for dx, col in ((2, QColor(0, 0, 0)), (0, QColor(125, 240, 255) if warn else QColor(255, 224, 90))):
                p.setPen(col)
                p.drawText(QRectF(dx, VIEW_H * 0.27 + dx, WIN_W, 34), Qt.AlignmentFlag.AlignCenter, eng.notice)
        big = QFont("Sans", 28)
        big.setBold(True)
        p.setFont(big)
        if eng.state == "dead":
            p.fillRect(0, 0, WIN_W, VIEW_H, QColor(90, 0, 0, 150))
            p.setPen(QColor(255, 220, 200))
            p.drawText(QRectF(0, VIEW_H * 0.3, WIN_W, 60), Qt.AlignmentFlag.AlignCenter, "BAĞLANTI KESİLDİ")
            p.setFont(QFont("Sans", 12))
            p.drawText(QRectF(0, VIEW_H * 0.3 + 60, WIN_W, 30), Qt.AlignmentFlag.AlignCenter,
                       f"{eng.kills} düşman devirdin · Enter: çık · R: tekrar dene")
        elif eng.banner > 0:
            if eng.wave == 1:  # açılış: oyun adı + alt başlık
                p.setPen(QColor(255, 40, 200))
                p.drawText(QRectF(0, VIEW_H * 0.12, WIN_W, 60), Qt.AlignmentFlag.AlignCenter, TITLE.upper())
                p.setFont(QFont("Sans", 14))
                p.setPen(QColor(120, 240, 255))
                p.drawText(QRectF(0, VIEW_H * 0.12 + 58, WIN_W, 30), Qt.AlignmentFlag.AlignCenter, SUBTITLE.lower())
            else:
                p.setPen(QColor(120, 240, 255))
                p.drawText(QRectF(0, VIEW_H * 0.15, WIN_W, 60), Qt.AlignmentFlag.AlignCenter, f"DALGA {eng.wave}")
