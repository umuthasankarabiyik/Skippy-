"""Masaüstü Pet — çekirdek mantık (arayüzden bağımsız).

Ayarlar, hatırlatıcılar, sohbet "beyni" ve isteğe bağlı Claude bağlantısı burada.
"""
import json
import os
import random
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG_DIR = CONFIG_HOME / "masaustu-pet"
CONFIG_FILE = CONFIG_DIR / "config.json"
REMINDER_FILE = CONFIG_DIR / "reminders.json"
API_URL = "http://localhost:11434/api/generate"

DEFAULTS = {
    "name": "Skibi",
    "water_on": True,
    "water_every_min": 45,
    "eye_on": False,
    "eye_every_min": 30,
    "api_key": "",
    "model": "qwen3.5",
    "skin": "",          # boş = yerleşik kedi
    "size": 120,
    "mirror": True,      # sola yürürken resmi çevir
    "sound_on": True,
    "sit": False,        # True = pet oturur, gezmez
}

DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
          "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


# ----------------------------------------------------------------- ayarlar
def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)  # API anahtarı içerebilir
    except OSError:
        pass


def install_autostart(script_path):
    """Oturum açılınca peti otomatik başlatan .desktop dosyası yazar."""
    d = CONFIG_HOME / "autostart"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "skibi.desktop"
    f.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Skibi\n"
        "Comment=Masaüstü arkadaşın\n"
        f'Exec={sys.executable} "{script_path}"\n'
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    return f


# --------------------------------------------------- Türkçe yardımcılar
def fold(s):
    """Küçük harfe çevir ve Türkçe karakterleri ASCII'ye indir (eşleştirme için)."""
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return s.translate(str.maketrans("ışğüöç", "isguoc"))


# -------------------------------------------------------- hatırlatıcılar
_UNITS = {"saniye": 1, "sn": 1, "dakika": 60, "dk": 60, "saat": 3600}
_REL = re.compile(r"(\d+)\s*(saniye|sn|dakika|dk|saat)\s*(?:sonra|içinde|icinde)", re.IGNORECASE)
_ABS = re.compile(r"(?<![\d.:])(?:saat\s*)?(\d{1,2})[:.](\d{2})(?!\d)(?:['’]?(?:de|da|te|ta)\b)?",
                  re.IGNORECASE)
_STOP = {"hatirlat", "hatirlatir", "misin", "bana", "beni", "lutfen", "diye", "yarin", "rica", "ederim"}


def _clean(text):
    words = []
    for w in text.split():
        f = fold(w.strip("?.,!:;'’\""))
        if f in _STOP or f.startswith("hatirlat"):
            continue
        words.append(w)
    out = " ".join(words).strip(" ,.;:-")
    return out or "Zamanı geldi!"


def parse_reminder(text, now=None):
    """'10 dakika sonra su iç' veya 'yarın 09:30 toplantı' -> (zaman, metin) ya da None."""
    now = now or datetime.now()
    m = _REL.search(text)
    if m:
        seconds = int(m.group(1)) * _UNITS[fold(m.group(2))]
        due = (now + timedelta(seconds=seconds)).replace(microsecond=0)
        return due, _clean(text[:m.start()] + " " + text[m.end():])
    m = _ABS.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        due = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if "yarin" in fold(text) or due <= now:
            due += timedelta(days=1)
        return due, _clean(text[:m.start()] + " " + text[m.end():])
    return None


def fmt_due(due, now=None):
    now = now or datetime.now()
    days = (due.date() - now.date()).days
    hhmm = due.strftime("%H:%M")
    if days == 0:
        return f"bugün {hhmm}"
    if days == 1:
        return f"yarın {hhmm}"
    return f"{due.day} {MONTHS[due.month - 1]} {hhmm}"


class ReminderStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else REMINDER_FILE
        self.items = self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return sorted(({"due": datetime.fromisoformat(r["due"]), "text": r["text"]} for r in raw),
                          key=lambda r: r["due"])
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = [{"due": r["due"].isoformat(), "text": r["text"]} for r in self.items]
        self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, due, text):
        self.items.append({"due": due, "text": text})
        self.items.sort(key=lambda r: r["due"])
        self._save()

    def pop_due(self, now=None):
        """Zamanı gelenleri çıkarır; [(metin, gecikme_saniye), ...] döner."""
        now = now or datetime.now()
        due = [r for r in self.items if r["due"] <= now]
        if due:
            self.items = [r for r in self.items if r["due"] > now]
            self._save()
        return [(r["text"], (now - r["due"]).total_seconds()) for r in due]

    def upcoming(self):
        return list(self.items)


# ------------------------------------------------------------- Claude API
def claude_chat(api_key, messages, system, model, timeout=30):
    body = json.dumps({"model": model, "max_tokens": 300, "system": system,
                       "messages": messages}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


# ------------------------------------------------------------ metin havuzu
JOKES = [
    "Bir programcıya demişler ki: 'Markete git, 1 ekmek al, yumurta varsa 6 tane al.' "
    "Eve 6 ekmekle dönmüş: 'Yumurta vardı!' 😹",
    "Java programcıları neden gözlük takar? Çünkü C# göremezler! 🤓",
    "Linux'ta 'Bana sandviç yap' dersen 'Olmaz' der. 'sudo bana sandviç yap' dersen yapar 🥪",
    "Bilgisayar neden üşümüş? Çünkü Windows'u açık unutmuş! 🪟",
]
CLICK_LINES = ["Bam bam bida bam", "Basma la", "Tebrikler bedava iphone 17 kazandınız"]
WATER_LINES = ["Su vakti! 💧 Bir bardak iç, ben beklerim.", "Hey, son ne zaman su içtin? 💧",
               "Bardağı doldur, kafa açılır 😸💧"]
EYE_LINES = ["20-20-20: 20 saniye boyunca 20 adım ötedeki bir şeye bak 👀",
             "Gözlerini dinlendir! Pencereden dışarı bakmaya ne dersin? 🪟",
             "Mola! Ekrandan bir an kafanı kaldır 😺"]
IDLE_LINES = ["Bam bam bida bam", "Birşey unuttun , ne mi hatırlasana direkt",
              "Fun fact: Eğer fransızca paketini kaldırırsan linuxun hızlanır",]
FALLBACKS = ["Ne istiyon nereden bilem ben"]

HELP = ("Şunları yapabilirim:\n"
        "• Sohbet etmek, şaka yapmak\n"
        "• Hatırlatıcı: '25 dakika sonra çayı demle' ya da 'yarın 09:30 toplantı' yaz\n"
        "• Düzenli su ve göz molası hatırlatması (sağ tık menüsünden aç/kapa)\n"
        "• Komutlar: 'otur', 'kalk', 'uyu', 'uyan'\n"
        "• Kendi resimlerini ve seslerini eklemek: sağ tık → Görünüm / Sesler 🐾")

# (anahtar kelimeler, yanıtlar) — sıra önemli
RULES = [
    (("yardim", "ne yapabilirsin", "neler yapabilirsin", "komut"), [HELP]),
    (("gule gule", "hosca kal", "gorusuruz", "bay bay", "iyi geceler", "kendine iyi bak"),
     ["Görüşürüz! Ben buradayım 🐾", "Hoşça kal! Dönünce beni okşamayı unutma 😺"]),
    (("merhaba", "selam", "slm", "hey", "gunaydin", "iyi aksamlar"),
     ["Selam! Ben de tam seni bekliyordum 😸", "Merhaba merhaba! Bugün neler yapıyoruz?",
      "Hey! {name} burada, emrindeyim 🐾"]),
    (("nasilsin", "naber", "ne haber", "nasil gidiyor", "iyi misin"),
     ["Bomba gibiyim! Masaüstün çok rahat 😺 Sen nasılsın?",
      "İyiyim, az önce kuyruğumu kovaladım. Sen?", "Harikayım! Ama su içtin mi acaba? 💧"]),
    (("adin ne", "ismin ne", "kimsin"),
     ["Ben {name}! Masaüstünde yaşayan küçük bir dostum. Sağ tık → 'Adını değiştir' ile bana yeni isim koyabilirsin."]),
    (("saat kac", "saati soyle"), ["Saat şu an {time} ⏰"]),
    (("bugun gunlerden", "tarih", "hangi gun", "bugun ayin"), ["Bugün {date}."]),
    (("saka", "fikra", "komik", "guldur"), JOKES),
    (("sikildi", "sikici", "canim sikkin"),
     ["Hadi 5 dakika kalk, biraz esne, su iç. Dönünce sana bir şaka anlatırım!",
      "Sıkıldıysan 'şaka yap' de, bir tane patlatayım 😹",
      "Yeni bir fikir bulalım mı? Kafanda dönenlerden birini anlat!"]),
    (("yorgun", "yoruldum", "uykum"),
     ["Bir mola ver, ekrandan uzaklaş. Ben nöbet tutarım 😴",
      "Biraz su iç, gözlerini dinlendir. Gerçekten işe yarıyor!"]),
    (("uzgunum", "mutsuzum", "moralim", "kotu hissediyorum", "motivasyon"),
     ["Yanındayım. Derin bir nefes al; küçük bir adım at, gerisi gelir 💛",
      "Zor günler geçiyor olabilir ama sen düşündüğünden güçlüsün. Ben de buradayım 🐾"]),
    (("tesekkur", "sagol", "eyvallah", "tsk"), ["Rica ederim! 😸", "Ne demek, her zaman! 🐾"]),
    (("su ictim",), ["Aferin! 💧 Böyle devam.", "Süper! Vücudun sana teşekkür ediyor."]),
    (("seviyorum", "tatlisin"), ["Ben de seni seviyorum 😻"]),
    (("python", "linux", "manjaro", "kod", "yazilim", "bug", "hata"),
     ["Yazılım mı dedin? Bayılırım! Bir fikrin varsa söyle, beraber geliştirelim 🛠️",
      "Hata varsa panik yok: hata mesajını kopyalayıp bir yapay zekâ dostuna yapıştır, genelde çözülür 😉"]),
]


def greeting(name, now=None):
    h = (now or datetime.now()).hour
    if h < 5:
        return f"Bu saatte ayakta mısın? {name} de uyanık 🌙"
    if h < 12:
        return f"Günaydın! {name} göreve hazır ☀️"
    if h < 18:
        return f"Merhaba! {name} burada, bugün neler yapıyoruz? 🐾"
    return f"İyi akşamlar! {name} seninle 🌆"


def _matches(tokens, folded, kw):
    if " " in kw:
        return kw in folded
    return any(t == kw or (len(kw) >= 5 and t.startswith(kw)) for t in tokens)


class Brain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.history = []

    @property
    def name(self):
        return self.cfg.get("name", "Pati")

    @property
    def api_key(self):
        return self.cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def has_api(self):
        return bool(self.api_key)

    def system_prompt(self):
        return (f"Sen {self.name} adında, kullanıcının masaüstünde yaşayan sevimli bir pet'sin (küçük bir kedi). "
                "Türkçe konuş; kısa (1-3 cümle), samimi ve neşeli ol. Kullanıcı Manjaro Linux kullanıyor ve "
                "yazılıma yeni; teknik şeyleri sade anlat. Hatırlatıcıyı sen kuramazsın ama kullanıcı sohbete "
                "'10 dakika sonra su iç' ya da 'yarın 09:30 toplantı' yazarsa pet bunu otomatik kurar; "
                "gerekirse bunu hatırlat.")

    def _window(self):
        h = self.history[-20:]
        while h and h[0]["role"] != "user":
            h.pop(0)
        return h

    def ask_claude(self, text):
        self.history.append({"role": "user", "content": text})
        try:
            reply = claude_chat(self.api_key, self._window(), self.system_prompt(),
                                self.cfg.get("model") or DEFAULTS["model"])
            if not reply:
                raise RuntimeError("boş yanıt")
        except Exception:
            self.history.pop()
            raise
        self.history.append({"role": "assistant", "content": reply})
        self.history = self._window()
        return reply

    def local_reply(self, text, api=False):
        """İnternetsiz hazır yanıt; eşleşme yoksa None.

        api=True iken (Claude anahtarı varken) yalnızca kısa ve net komutlara
        bakar, esnek konuşmaları Claude'a bırakır.
        """
        folded = fold(text)
        tokens = re.findall(r"\w+", folded)
        if api and len(tokens) > 4:
            return None
        now = datetime.now()
        ctx = {"name": self.name, "time": now.strftime("%H:%M"),
               "date": f"{now.day} {MONTHS[now.month - 1]} {now.year}, {DAYS[now.weekday()]}"}
        for keywords, replies in RULES:
            if api and keywords[0] in _SOFT:
                continue
            if any(_matches(tokens, folded, kw) for kw in keywords):
                return random.choice(replies).format(**ctx)
        return None

    def offline_reply(self, text):
        return self.local_reply(text) or random.choice(FALLBACKS)


# API varken Claude'a bırakılan esnek konuların ilk anahtar kelimeleri
_SOFT = {"sikildi", "yorgun", "uzgunum", "python"}


# ------------------------------------------------ komutlar (otur, kalk, ...)
COMMAND_REPLIES = {
    "sit": "Tamam, oturuyorum 🪑 ('kalk' dersen yine gezerim)",
    "stand": "Kalktım! Biraz gezineyim 🐾",
    "sleep": "İyi geceler… 😴 ('uyan' demen yeter)",
    "wake": "Uyandım! 😸",
}


def parse_command(text):
    """'otur', 'kalk', 'uyu', 'uyan' gibi kısa komutları tanır (en çok 4 kelime)."""
    tokens = re.findall(r"\w+", fold(text))
    if not tokens or len(tokens) > 4:
        return None

    def starts(*stems):
        return any(t.startswith(s) for t in tokens for s in stems)

    def has(*words):
        return any(t in words for t in tokens)

    if starts("otur", "gezme", "gezinme", "kipirda") or has("dur"):
        return "sit"
    if starts("uyan"):
        return "wake"
    if starts("uyu") or has("yat"):
        return "sleep"
    if starts("kalk", "gezin", "gezs", "gezeb", "dolas", "yuru") or has("gez"):
        return "stand"
    return None


# ------------------------------------------------- görünüm (skin) ve sesler
SKINS_DIR = CONFIG_DIR / "skins"
SOUNDS_DIR = CONFIG_DIR / "sounds"
IMG_EXTS = (".gif", ".png", ".webp", ".jpg", ".jpeg")  # tercih sırası
SND_EXTS = (".wav", ".ogg", ".mp3", ".flac")

ASSET_ALIASES = {
    "idle": ("idle", "bekle"),
    "walk": ("walk", "yürü"),
    "walk_left": ("walk_left", "sola"),
    "sit": ("sit", "otur"),
    "sleep": ("sleep", "uyu"),
    "happy": ("happy", "mutlu"),
    "drag": ("drag", "tut"),
}
SOUND_ALIASES = {
    "greeting": ("greeting", "merhaba"),
    "click": ("click", "tıkla"),
    "reminder": ("reminder", "hatırlatıcı"),
    "water": ("water", "su"),
    "eye": ("eye", "göz"),
    "sleep": ("sleep", "uyu"),
    "wake": ("wake", "uyan"),
    "sit": ("sit", "otur"),
    "stand": ("stand", "kalk"),
    "chat": ("chat", "sohbet"),
}

SKIN_README = """PETİN GÖRÜNÜMÜNÜ KENDİN YAP
==========================

1) Bu klasörün (skins) içine yeni bir klasör aç. Klasörün adı görünümün adı olur.
   Örnek: "Kara Kedi"

2) O klasöre .png veya .gif resimler koy. Dosya adı durumu belirler
   (İngilizce ya da Türkçe adı kullanabilirsin):

   idle  (veya: bekle)   → pet beklerken        ← BU ZORUNLU
   walk  (veya: yürü)    → yürürken
   sit   (veya: otur)    → otururken
   sleep (veya: uyu)     → uyurken
   happy (veya: mutlu)   → mutluyken / hatırlatıcı gelince
   drag  (veya: tut)     → fareyle tutulunca
   walk_left (veya: sola) → sola yürürken (yoksa walk resmi otomatik çevrilir)

   Örnek: idle.png, walk.gif, sleep.png

3) Eksik bıraktığın durumlarda "idle" resmi kullanılır.
   Aynı isimde hem .gif hem .png varsa .gif kullanılır.

4) Peti sağ tıkla → Görünüm → klasörünün adını seç.

İPUÇLARI
- Arka planı şeffaf olan PNG/GIF kullan, yoksa resim kutu içinde görünür.
- Resim büyük olabilir, pet küçültür. Boyutu sağ tık → Boyut'tan ayarla.
- Aynı klasöre ses dosyaları da koyabilirsin (sounds klasöründeki NASIL YAPILIR.txt'ye bak).
"""

SOUND_README = """PETE SES EKLEME
===============

Ses dosyalarını (.wav veya .ogg en sorunsuzu, .mp3 de olur) bu klasöre koy.
Dosya adı sesin ne zaman çalacağını belirler:

   greeting (veya: merhaba)     → pet açılınca
   click    (veya: tıkla)       → ona tıklayınca
   reminder (veya: hatırlatıcı) → hatırlatıcının zamanı gelince
   water    (veya: su)          → su içme hatırlatmasında
   eye      (veya: göz)         → göz molası hatırlatmasında
   sleep    (veya: uyu)         → uykuya dalınca
   wake     (veya: uyan)        → uyanınca
   sit      (veya: otur)        → "otur" komutunda
   stand    (veya: kalk)        → "kalk" komutunda
   chat     (veya: sohbet)      → sohbette cevap verince

Örnek: click.wav, reminder.ogg

Sesi bir görünüm klasörüne de koyabilirsin; o zaman sadece o görünümde çalar.
Sağ tık → Sesler menüsünden sesleri kapatabilir ve hatırlatma sesini deneyebilirsin.
"""


def ensure_dirs():
    """skins ve sounds klasörlerini (açıklama dosyalarıyla) oluşturur."""
    for d, text in ((SKINS_DIR, SKIN_README), (SOUNDS_DIR, SOUND_README)):
        d.mkdir(parents=True, exist_ok=True)
        f = d / "NASIL YAPILIR.txt"
        if not f.exists():
            f.write_text(text, encoding="utf-8")


def _norm(s):
    return fold(s).strip().replace("-", "_").replace(" ", "_")


def _index(directory, exts, aliases):
    """Klasördeki dosyaları {durum_adı: yol} olarak verir.

    Büyük/küçük harf ve Türkçe karakter fark etmez; aynı durum için .gif .png'ye tercih edilir.
    """
    found = {}
    try:
        files = sorted(Path(directory).iterdir())
    except OSError:
        return found
    lookup = {_norm(a): canon for canon, names in aliases.items() for a in names}
    for f in files:
        ext = f.suffix.lower()
        if ext not in exts or not f.is_file():
            continue
        canon = lookup.get(_norm(f.stem))
        if canon is None:
            continue
        cur = found.get(canon)
        if cur is None or exts.index(ext) < exts.index(cur.suffix.lower()):
            found[canon] = f
    return found


def list_skins():
    """İçinde en az bir tanınan resim olan görünüm klasörlerinin adları."""
    try:
        dirs = sorted(p for p in SKINS_DIR.iterdir() if p.is_dir())
    except OSError:
        return []
    return [d.name for d in dirs if _index(d, IMG_EXTS, ASSET_ALIASES)]


def find_asset(skin, state, direction=1):
    """(yol, anahtar) ya da None. Eksik durum için 'idle' kullanılır."""
    if not skin:
        return None
    idx = _index(SKINS_DIR / skin, IMG_EXTS, ASSET_ALIASES)
    order = (["walk_left"] if state == "walk" and direction < 0 else []) + [state, "idle"]
    for key in order:
        if key in idx:
            return idx[key], key
    return None


def find_sound(skin, event):
    """Önce görünüm klasöründe, sonra genel sounds klasöründe ara."""
    dirs = ([SKINS_DIR / skin] if skin else []) + [SOUNDS_DIR]
    for d in dirs:
        idx = _index(d, SND_EXTS, SOUND_ALIASES)
        if event in idx:
            return idx[event]
    return None
