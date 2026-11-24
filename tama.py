"""Tamagotchi (sanal bebek) modu: açlık, mutluluk, temizlik, enerji ve oyundan / çalışmadan kazanılan jeton.

Durum, pet'in config sözlüğündeki "tama" anahtarında saklanır (pet_core'a dokunmaya gerek yok).
Evrim / büyüme yok: pet hep aynı pet, sadece bakımı gerekiyor.
"""
import random
import time

from PyQt6.QtCore import Qt, QTimer
import hud
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton,
                             QVBoxLayout, QWidget)

DEFAULTS = {
    "food": 80.0, "fun": 80.0, "clean": 90.0, "energy": 90.0,
    "coins": 3,
    "best_wave": 0, "best_kills": 0, "games": 0, "last_ts": 0.0,
}

# (anahtar, etiket, renk)
STATS = (
    ("food", "🍖 Tokluk", "#E8A33D"),
    ("fun", "🎮 Mutluluk", "#E86A8A"),
    ("clean", "🫧 Temizlik", "#4FB3D9"),
    ("energy", "🔋 Enerji", "#7BC74D"),
)

MOOD_ICON = {"hungry": "🍖", "dirty": "🫧", "tired": "🥱", "sad": "😿", "sleep": "", "happy": "", "ok": ""}
MOOD_TEXT = {"hungry": "karnı aç", "dirty": "kirli", "tired": "yorgun", "sad": "canı sıkkın",
             "sleep": "uyuyor", "happy": "mutlu", "ok": "idare eder"}

# --- yiyecek / içecek kataloğu: jetonla alınır. fx: durumlara etkisi (puan). Fiyat, etkilerin değerinden hesaplanır.
STAT_NAMES = {"food": "tokluk", "fun": "mutluluk", "energy": "enerji"}
STAT_WEIGHT = {"food": 1.0, "fun": 1.1, "energy": 1.2}  # enerji sadece uyuyarak dolduğu için biraz daha değerli
PRICE_PER = 10                                           # yaklaşık 10 değer puanı = 1 jeton

FOODS = {
    "biskuvi": {"name": "Bisküvi", "icon": "🍪", "fx": {"fun": 22, "food": 8},
                "msg": "Mermi bisküvisi! Çıtır çıtır."},
    "kahve": {"name": "Kahve", "icon": "☕", "fx": {"energy": 30},
              "msg": "Kahve… Gözlerim açıldı."},
    "enerji": {"name": "Enerji içeceği", "icon": "🥤", "fx": {"energy": 60, "fun": 12, "food": -10},
               "msg": "Enerji içeceği! Kalbim hızlandı, midem biraz boşaldı."},
    "baklava": {"name": "Baklava", "icon": "🍯", "fx": {"fun": 30, "food": 25},
                "msg": "Baklava! Şerbet damlıyor, mutluluk tavan."},
    "makarna": {"name": "Makarna", "icon": "🍝", "fx": {"food": 40},
                "msg": "Makarna. Klasik, güvenilir, doyurucu."},
    "pizza": {"name": "Pizza", "icon": "🍕", "fx": {"food": 55},
              "msg": "Pizza! Kenarını bile bırakmayacağım."},
    "hamburger": {"name": "Hamburger", "icon": "🍔", "fx": {"food": 70},
                  "msg": "Hamburger. Tokluk modu tam kapasite."},
}


def price(key):
    """Fiyat = etkilerin ağırlıklı toplamı / PRICE_PER (en az 1 jeton). Bisküvi 3, kahve 4, makarna 4, baklava 6, pizza 6,
    hamburger 7, enerji içeceği 8."""
    net = sum(STAT_WEIGHT[s] * v for s, v in FOODS[key]["fx"].items())
    return max(1, int(net / PRICE_PER + 0.5))


def effect_text(key):
    """'tokluk +8, mutluluk +22' biçiminde etki özeti (artanlar önce)."""
    fx = sorted(FOODS[key]["fx"].items(), key=lambda kv: -kv[1])
    return ", ".join(f"{STAT_NAMES[s]} {v:+d}" for s, v in fx)


def food_label(key):
    f = FOODS[key]
    return f"{f['icon']}  {f['name']}  ·  {price(key)} jeton  ·  {effect_text(key)}"


def min_price():
    return min(price(k) for k in FOODS)


ALERTS = {
    "hungry": ["Karnım zil çalıyor.", "Acıktım. Yiyecekler menüsüne bakar mısın?", "Biraz bir şey yesek?"],
    "dirty": ["Üstüm başım pis 🫧 Temizlesene…", "Biraz yıkanmam lazım 🫧"],
    "sad": ["Canım sıkıldı 😿 Bir tur oyun oynasak?", "Sıkılıyorum… mini oyun? 🎯"],
    "tired": ["Çok yoruldum 🥱 Uyutur musun?", "Gözlerim kapanıyor… 😴"],
    "rested": ["Günaydın! Enerjim doldu 😸"],
}
ALERT_COOLDOWN = 25 * 60  # aynı uyarı en erken 25 dakikada bir


def _clamp(v):
    return max(0.0, min(100.0, v))


class Tama:
    def __init__(self, cfg, save):
        self.save = save
        d = cfg.setdefault("tama", {})
        for k, v in DEFAULTS.items():
            d.setdefault(k, v)
        if not d["last_ts"]:
            d["last_ts"] = time.time()
        self.d = d
        now = time.time()
        self.alert_ts = {k: now for k in ALERTS}  # açılışta hemen uyarı yağmasın

    # --- zaman akışı
    def tick(self, sleeping=False, now=None):
        """Süreyi işler; dikkat çekmesi gereken olayların listesini döndürür."""
        d = self.d
        now = now or time.time()
        sec = now - d["last_ts"]
        d["last_ts"] = now
        if sec <= 0:
            return []
        if sec > 600:  # bilgisayar kapalıydı: etkisi yavaşlatılmış sayılır
            hours, sleeping = min(sec / 3600 * 0.3, 6.0), False
        else:
            hours = sec / 3600

        d["food"] = _clamp(d["food"] - 7 * hours)
        d["fun"] = _clamp(d["fun"] - (5 + (3 if d["food"] < 15 else 0)) * hours)
        d["clean"] = _clamp(d["clean"] - 3 * hours)
        d["energy"] = _clamp(d["energy"] + (25 if sleeping else -3.5) * hours)

        events = []
        if sleeping and d["energy"] >= 99.5:
            events.append("rested")
        elif not sleeping:
            for ev, bad in (("hungry", d["food"] < 25), ("dirty", d["clean"] < 30),
                            ("tired", d["energy"] < 20), ("sad", d["fun"] < 25)):
                if bad:
                    events.append(ev)
        events = [e for e in events if e == "rested" or now - self.alert_ts[e] >= ALERT_COOLDOWN]
        for e in events:
            self.alert_ts[e] = now
        self.save()
        return events

    # --- bakım
    def feed(self, key):
        """Katalogdaki bir şeyi jetonla alır: (mesaj, başarılı mı). İhtiyaç yoksa ya da jeton yetmezse jeton harcanmaz."""
        item = FOODS.get(key)
        if item is None:
            return "Bunu tanımıyorum.", False
        d = self.d
        gains = [st for st, v in item["fx"].items() if v > 0]
        if all(d[st] >= 95 for st in gains):  # yükselteceği hiçbir şeye ihtiyaç yok
            if gains == ["food"]:
                return "Çok tokum, şimdi sığmaz.", False
            return "Şu an buna ihtiyacım yok.", False
        cost = price(key)
        if d["coins"] < cost:
            return f"{item['name']} için {cost} jeton lazım. Oyun oyna ya da çalışarak jeton kazan.", False
        d["coins"] -= cost
        for st, v in item["fx"].items():
            d[st] = _clamp(d[st] + v)
        self.save()
        return item["msg"], True

    def menu_text(self):
        """Sohbette 'menü' denince söylenecek fiyat listesi."""
        items = ", ".join(f"{f['name']} {price(k)}" for k, f in FOODS.items())
        return f"Menü (jeton): {items}. Cebimde {self.d['coins']} jeton var."

    def add_coins(self, n):
        self.d["coins"] += int(n)
        self.save()

    def clean_up(self):
        d = self.d
        if d["clean"] >= 90:
            return "Zaten pırıl pırılım ✨", False
        d["clean"] = _clamp(d["clean"] + 45)
        d["fun"] = _clamp(d["fun"] + 3)
        self.save()
        return "Tertemiz oldum! 🫧", True

    def can_play(self):
        d = self.d
        if d["energy"] < 15:
            return False, "Çok yorgunum… önce biraz uyutsan? 😴"
        if d["food"] < 10 and d["coins"] >= min_price():  # parası varsa önce yesin; yoksa oyun jeton kazanmanın yolu
            return False, "Karnım zil çalıyor, önce bir şeyler yesek."
        return True, ""

    def play_result(self, kills, wave):
        d = self.d
        d["games"] += 1
        d["best_wave"] = max(d["best_wave"], wave)
        d["best_kills"] = max(d["best_kills"], kills)
        earned = kills // 3 + max(0, wave - 1)
        d["coins"] += earned
        d["fun"] = _clamp(d["fun"] + (min(55, 12 + kills * 3) if kills else 8))
        d["energy"] = _clamp(d["energy"] - 10)
        d["food"] = _clamp(d["food"] - 8)
        d["clean"] = _clamp(d["clean"] - 6)
        self.save()
        if not kills:
            return "Hiç vuramadım ama olsun, eğlendim 😼"
        return f"{kills} düşman devirdim! {earned} jeton kazandım."

    # --- durum
    def mood(self, sleeping=False):
        d = self.d
        if sleeping:
            return "sleep"
        if d["food"] < 25:
            return "hungry"
        if d["clean"] < 30:
            return "dirty"
        if d["energy"] < 20:
            return "tired"
        if d["fun"] < 25:
            return "sad"
        avg = (d["food"] + d["fun"] + d["clean"] + d["energy"]) / 4
        return "happy" if avg >= 70 else "ok"

    def summary(self, name, sleeping=False):
        d = self.d
        return (f"{name} şu an {MOOD_TEXT[self.mood(sleeping)]}. Tokluk %{int(d['food'])}, "
                f"mutluluk %{int(d['fun'])}, temizlik %{int(d['clean'])}, enerji %{int(d['energy'])}. "
                f"Cebimde {d['coins']} jeton var.")


FOOD_WORDS = {
    "enerji": ("enerji içeceği", "enerji icecegi", "enerji içecek", "enerji icecek", "energy drink"),
    "biskuvi": ("bisküvi", "biskuvi", "atıştır", "biscuit", "cookie"),
    "kahve": ("kahve", "coffee"),
    "baklava": ("baklava",),
    "makarna": ("makarna", "pasta"),
    "pizza": ("pizza",),
    "hamburger": ("hamburger", "burger"),
}


def parse_command(text):
    """Sohbetten gelen kısa Tamagotchi komutları: play / clean / food:<anahtar> / menu / status."""
    t = text.replace("İ", "i").replace("I", "ı").lower().strip()
    if len(t) > 40:
        return None
    if any(w in t for w in ("oyun", "oyna", "shooter", "play", "game")):
        return "play"
    if any(w in t for w in ("temizle", "yıka", "clean", "wash", "bath")):
        return "clean"
    for key, words in FOOD_WORDS.items():
        if any(w in t for w in words):
            return "food:" + key
    if any(w in t for w in ("menü", "menu", "mama", "yemek", "yiyecek", "doyur", "besle", "feed", "food")):
        return "menu"
    if any(w in t for w in ("durum", "tokluk", "kaç jeton", "status", "how many coins")):
        return "status"
    return None


# ------------------------------------------------------------------ panel
BAR_STYLE = ("QProgressBar{border:1px solid #5B3A1E;border-radius:6px;text-align:center;"
             "height:16px;background:#FFF6E8;color:#222;}"
             "QProgressBar::chunk{background:COLOR;border-radius:5px;}")


class TamaPanel(hud.GlitchWindow, QWidget):
    def __init__(self, pet):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.pet = pet
        self.setWindowTitle("Tamagotchi")
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setStyleSheet("font-size:14px; font-weight:bold;")
        lay.addWidget(self.head)

        self.bars = {}
        for key, label, color in STATS:
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setFixedWidth(100)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setStyleSheet(BAR_STYLE.replace("COLOR", color))
            row.addWidget(lab)
            row.addWidget(bar)
            lay.addLayout(row)
            self.bars[key] = bar

        self.info = QLabel()
        lay.addWidget(self.info)

        grid = QGridLayout()
        food_btn = QPushButton("🍽 Yiyecekler")  # bisküvi dahil tüm yiyecek / içecekler tek menüde
        self.food_menu = QMenu(self)
        self.food_menu.aboutToShow.connect(lambda: self.pet.fill_food_menu(self.food_menu))
        food_btn.setMenu(self.food_menu)
        grid.addWidget(food_btn, 0, 0, 1, 2)
        for i, (text, cmd) in enumerate((("🧼 Temizle", "clean"), ("🎯 Oyna", "play"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, c=cmd: self.pet.tama_action(c))
            grid.addWidget(b, 1, i)
        sleep = QPushButton("😴 Uyut / uyandır")
        sleep.clicked.connect(lambda _=False: self.pet.toggle_sleep())
        grid.addWidget(sleep, 2, 0, 1, 2)
        lay.addLayout(grid)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        t = self.pet.tama
        d = t.d
        mood = t.mood(self.pet.state == "sleep")
        self.head.setText(f"{self.pet.cfg['name']} · {MOOD_TEXT[mood]} · 🪙 {d['coins']}")
        for key, bar in self.bars.items():
            bar.setValue(int(d[key]))
        self.info.setText(f"🏆 En iyi: dalga {d['best_wave']}, {d['best_kills']} düşman    "
                          f"🎮 {d['games']} oyun")

    def showEvent(self, e):
        self.refresh()
        self.timer.start(1000)
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)
