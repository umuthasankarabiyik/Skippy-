"""Streak: günlük alışkanlık / hatırlatıcı takibi.

Her streak için hangi günlerde yapıldığı saklanır. Seri (🔥) = bugüne (bugün yapılmadıysa dünden) kadar
art arda yapılan gün sayısı; gün bitmeden bozulmaz. Veri, ayar dosyasından bağımsız küçük bir JSON dosyasında durur.
"""
import datetime as dt
import json
import re
from pathlib import Path

MAX_HABITS = 12
MAX_NAME = 40
MAX_DAYS = 800            # her streak için saklanan en fazla gün
MILESTONES = (7, 30, 100, 365)
DEFAULT_TIME = "20:00"    # akşam hatırlatması


def default_path(base_dir):
    """Veri dosyası: pet'in veri klasörünün yanına; klasör yoksa/yazılamazsa ev dizinine düşer."""
    try:
        d = Path(base_dir).parent
        d.mkdir(parents=True, exist_ok=True)
        return d / "streaks.json"
    except Exception:
        return Path.home() / ".pet-streaks.json"


def parse_clock(text):
    """'20', '20:30', '8.15' -> '20:00' / '20:30' / '08:15'. Anlaşılmazsa None."""
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*", text or "")
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def _day(d):
    return d.isoformat()


def _key(name):
    """Türkçe'ye uygun büyük/küçük harf duyarsız karşılaştırma anahtarı (İ->i, I->ı)."""
    return name.replace("İ", "i").replace("I", "ı").lower()


class StreakStore:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"habits": [], "nudge_on": True, "nudge_time": DEFAULT_TIME, "nudged": ""}
        self.load()

    # --- dosya
    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for h in raw.get("habits", []):
            if isinstance(h, dict) and isinstance(h.get("id"), int) and isinstance(h.get("name"), str):
                days = [d for d in h.get("days", []) if isinstance(d, str)]
                self.data["habits"].append({"id": h["id"], "name": h["name"][:MAX_NAME], "days": days[-MAX_DAYS:]})
        if isinstance(raw.get("nudge_on"), bool):
            self.data["nudge_on"] = raw["nudge_on"]
        if parse_clock(str(raw.get("nudge_time", ""))):
            self.data["nudge_time"] = parse_clock(raw["nudge_time"])
        if isinstance(raw.get("nudged"), str):
            self.data["nudged"] = raw["nudged"]

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)  # yarım yazılmış dosya kalmasın
            return True
        except OSError:
            return False

    # --- streak'ler
    def habits(self):
        return self.data["habits"]

    def get(self, hid):
        return next((h for h in self.data["habits"] if h["id"] == hid), None)

    def add(self, name, now=None):
        """(streak, None) ya da (None, hata mesajı). Akşam hatırlatma saati geçmişse bugünkü hatırlatmayı atlar."""
        name = re.sub(r"\s+", " ", (name or "")).strip()
        if not name:
            return None, "Boş bir şeyi her gün yapamazsın. Bir isim yaz."
        if len(name) > MAX_NAME:
            return None, f"Çok uzun. En fazla {MAX_NAME} karakter."
        if len(self.habits()) >= MAX_HABITS:
            return None, f"En fazla {MAX_HABITS} streak tutabilirim. Önce birini sil."
        if any(_key(h["name"]) == _key(name) for h in self.habits()):
            return None, "Bu zaten listede."
        hid = max((h["id"] for h in self.habits()), default=0) + 1
        h = {"id": hid, "name": name, "days": []}
        self.data["habits"].append(h)
        now = now or dt.datetime.now()
        if now.strftime("%H:%M") >= self.data["nudge_time"]:  # akşam geçtiyse yeni eklenen için bugün hatırlatma yapma
            self.data["nudged"] = _day(now.date())
        self.save()
        return h, None

    def remove(self, hid):
        self.data["habits"] = [h for h in self.habits() if h["id"] != hid]
        self.save()

    # --- günlük işaretleme
    def is_done(self, h, today=None):
        return _day(today or dt.date.today()) in h["days"]

    def toggle(self, hid, today=None):
        """Bugünü işaretler / işareti geri alır. İşaretli olduysa True döner."""
        h = self.get(hid)
        key = _day(today or dt.date.today())
        if key in h["days"]:
            h["days"].remove(key)
            done = False
        else:
            h["days"] = sorted(set(h["days"]) | {key})[-MAX_DAYS:]
            done = True
        self.save()
        return done

    def current(self, h, today=None):
        """Güncel seri: bugün yapıldıysa bugünden, yapılmadıysa dünden geriye art arda gün sayısı."""
        today = today or dt.date.today()
        days = set(h["days"])
        d = today if _day(today) in days else today - dt.timedelta(days=1)
        n = 0
        while _day(d) in days:
            n += 1
            d -= dt.timedelta(days=1)
        return n

    def best(self, h):
        best = run = 0
        prev = None
        for s in sorted(h["days"]):
            d = dt.date.fromisoformat(s)
            run = run + 1 if prev is not None and d - prev == dt.timedelta(days=1) else 1
            best = max(best, run)
            prev = d
        return best

    def pending(self, today=None):
        return [h for h in self.habits() if not self.is_done(h, today)]

    # --- akşam hatırlatması
    def nudge_due(self, now=None):
        now = now or dt.datetime.now()
        d = self.data
        return (d["nudge_on"] and d["nudged"] != _day(now.date())
                and now.strftime("%H:%M") >= d["nudge_time"] and bool(self.pending(now.date())))

    def mark_nudged(self, now=None):
        self.data["nudged"] = _day((now or dt.datetime.now()).date())
        self.save()

    def set_nudge_on(self, on):
        self.data["nudge_on"] = bool(on)
        self.save()

    def set_nudge_time(self, text):
        t = parse_clock(text)
        if t:
            self.data["nudge_time"] = t
            self.save()
        return t
