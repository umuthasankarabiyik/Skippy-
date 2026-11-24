"""Kullanıcı bilgileri ("Hakkımda"): ad, doğum günü, uyku saatleri.

- Ad: pet ara sıra adınla hitap eder, doğum gününde de kullanır.
- Doğum günü: o gün pet bir kez sürpriz yapar (balon, bildirim, hediye jeton) ve gün boyu parti şapkası takar.
- Uyku saatleri: bu aralıkta pet kendiliğinden konuşmaz (fun fact, laf atma, akşam hatırlatması).
  Kendi kurduğun hatırlatıcılar ve geri sayım bildirimleri etkilenmez.
Veriler ayar dosyasından bağımsız, `userdata.json` içinde tutulur.
"""
import calendar
import datetime as dt
import json
import re
from pathlib import Path

from streak import parse_clock

MAX_NAME = 30
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
          "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
BIRTHDAY_GIFT = 10  # doğum günü hediyesi (Tamagotchi jetonu)


def default_path(base_dir):
    """userdata.json: pet'in veri klasörünün yanına; klasör yoksa/yazılamazsa ev dizinine düşer."""
    try:
        d = Path(base_dir).parent
        d.mkdir(parents=True, exist_ok=True)
        return d / "userdata.json"
    except Exception:
        return Path.home() / ".pet-userdata.json"


def parse_birthday(text, today=None):
    """'14.03', '14.03.1998', '14/3/1998' -> (gün, ay, yıl|None). Geçersizse None.
    29 Şubat yılsız yazılabilir; yıl verilirse gerçek bir tarih ve gelecekte olmayan bir tarih olmalı."""
    today = today or dt.date.today()
    m = re.fullmatch(r"\s*(\d{1,2})[./\- ](\d{1,2})(?:[./\- ](\d{4}))?\s*", text or "")
    if not m:
        return None
    d, mo = int(m[1]), int(m[2])
    y = int(m[3]) if m[3] else None
    try:
        born = dt.date(y or 2000, mo, d)  # 2000 artık yıl: yılsız 29 Şubat geçerli
    except ValueError:
        return None
    if y is not None and (y < 1900 or born > today):
        return None
    return d, mo, y


def parse_sleep(text):
    """'00:00-08:00', '23.30 - 7.15', '0-8' -> ('00:00', '08:00'). Geçersizse None."""
    parts = re.split(r"\s*[-–—]\s*", (text or "").strip())
    if len(parts) != 2:
        return None
    a, b = parse_clock(parts[0]), parse_clock(parts[1])
    return (a, b) if a and b and a != b else None


class UserData:
    def __init__(self, path):
        self.path = Path(path)
        self.preview = False        # --preview-birthday: bu çalıştırmada doğum günü gibi davran (kaydetmez)
        self._preview_fired = False
        self.data = {"name": "", "bday": None, "sleep": None, "bday_year": 0}
        self.load()

    # --- dosya
    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        if isinstance(raw.get("name"), str):
            self.data["name"] = raw["name"].strip()[:MAX_NAME]
        b = raw.get("bday")
        if isinstance(b, list) and len(b) == 3 and parse_birthday(f"{b[0]}.{b[1]}" + (f".{b[2]}" if b[2] else "")):
            self.data["bday"] = [b[0], b[1], b[2] or None]
        s = raw.get("sleep")
        if isinstance(s, list) and len(s) == 2 and parse_sleep(f"{s[0]}-{s[1]}"):
            self.data["sleep"] = list(parse_sleep(f"{s[0]}-{s[1]}"))
        if isinstance(raw.get("bday_year"), int):
            self.data["bday_year"] = raw["bday_year"]

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except OSError:
            return False

    # --- ad
    @property
    def name(self):
        return self.data["name"]

    def set_name(self, text):
        self.data["name"] = re.sub(r"\s+", " ", text or "").strip()[:MAX_NAME]
        self.save()
        return self.data["name"]

    # --- doğum günü
    def set_birthday(self, text, today=None):
        """'ok' / 'cleared' / 'bad'. Boş metin kaydı siler."""
        if not (text or "").strip():
            self.data["bday"], self.data["bday_year"] = None, 0
            self.save()
            return "cleared"
        b = parse_birthday(text, today)
        if b is None:
            return "bad"
        if self.data["bday"] != list(b):
            self.data["bday_year"] = 0  # tarih değişti: o yılki sürpriz yeniden yapılabilir
        self.data["bday"] = list(b)
        self.save()
        return "ok"

    def birthday_input(self):
        """Dialogda gösterilecek düzenlenebilir biçim: 14.03.1998 / 14.03"""
        b = self.data["bday"]
        return f"{b[0]:02d}.{b[1]:02d}" + (f".{b[2]}" if b[2] else "") if b else ""

    def birthday_label(self):
        b = self.data["bday"]
        if not b:
            return ""
        return f"{b[0]} {MONTHS[b[1] - 1]}" + (f" {b[2]}" if b[2] else "")

    def is_birthday(self, today=None):
        if self.preview:
            return True
        b = self.data["bday"]
        if not b:
            return False
        today = today or dt.date.today()
        if (today.month, today.day) == (b[1], b[0]):
            return True
        # 29 Şubat doğumlular artık olmayan yıllarda 28 Şubat'ta kutlar
        return (b[1], b[0]) == (2, 29) and not calendar.isleap(today.year) and (today.month, today.day) == (2, 28)

    def birthday_due(self, today=None):
        """Bugün doğum günü ve bu yılki sürpriz henüz yapılmadı mı?"""
        if self.preview:
            return not self._preview_fired
        today = today or dt.date.today()
        return self.is_birthday(today) and self.data["bday_year"] != today.year

    def mark_birthday_done(self, today=None):
        if self.preview:
            self._preview_fired = True  # deneme: dosyaya yazılmaz
            return
        self.data["bday_year"] = (today or dt.date.today()).year
        self.save()

    def age(self, today=None):
        b = self.data["bday"]
        return (today or dt.date.today()).year - b[2] if b and b[2] else None

    # --- uyku saatleri
    def set_sleep(self, text):
        """'ok' / 'cleared' / 'bad'. Boş metin, 'yok', 'kapat' kaydı siler."""
        t = (text or "").strip().lower()
        if t in ("", "yok", "kapat", "-"):
            self.data["sleep"] = None
            self.save()
            return "cleared"
        s = parse_sleep(t)
        if s is None:
            return "bad"
        self.data["sleep"] = list(s)
        self.save()
        return "ok"

    def sleep_label(self):
        s = self.data["sleep"]
        return f"{s[0]}–{s[1]}" if s else ""

    def in_sleep_hours(self, now=None):
        s = self.data["sleep"]
        if not s:
            return False
        t = (now or dt.datetime.now()).strftime("%H:%M")
        a, b = s
        return a <= t < b if a < b else (t >= a or t < b)  # a > b: gece yarısını aşan aralık
