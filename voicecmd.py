"""Sesli komut: mikrofonu dinler, "Skippy ... aç" gibi komutları anlar, uygulama açar / pet özelliklerini çalıştırır.

Tanıma motorları (cfg["voicecmd"]):
  template — "Kendi sesim": indirme yok; komutları sen öğretirsin (voiceprint.py). Varsayılan.
  vosk   — çevrimdışı Vosk (pip install vosk + Türkçe model klasörü). Mikrofon parec / arecord / pw-record ile okunur.
  custom — kendi komutun: her tanınan cümleyi stdout'a satır satır yazan herhangi bir program (whisper vb.).
Ses HİÇBİR YERE gönderilmez (vosk çevrimdışı). Sadece sen açarsan dinler. Pet konuşurken mikrofon yok sayılır.
Güvenlik: yalnızca kurulu uygulamalar (.desktop kayıtları) ve senin eklediğin takma adlar açılır; keyfi komut çalıştırılmaz.
Qt'ye bağımlı değildir (iş parçacığı + kuyruk); pet kuyruğu bir QTimer ile okur.
"""
import difflib
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

DEFAULTS = {"on": False, "engine": "template", "sens": 1.0, "model": "", "wake": "skippy", "listen_cmd": ""}
WAKE_VARIANTS = ["skippy", "skipi", "iskipi", "iskippi", "skipy", "iskibi", "skibi", "skip"]
AWAKE_S = 7.0  # sadece "Skippy" dedikten sonra komutu bekleme süresi
OPEN_VERBS = ("ac", "baslat", "calistir", "goster", "getir", "open", "launch", "start", "run")
CLOSE_VERBS = ("kapat", "durdur", "close", "stop", "disable")
HELP = """"Kendi sesim" motorunda önce Sesli komut → Komut öğret ile her komutu 3 kez söyleyerek öğret.

Önce uyandırma kelimesini söyle (varsayılan: Skippy), sonra komutu:

• "Skippy Firefox aç" / "Steam aç" — kurulu herhangi bir uygulamayı açar
• "Skippy not defterini aç"
• "Skippy hatırlatıcıları göster" / "hatırlatıcı ekle"
• "Skippy 25 dakika sonra çayı demle diye hatırlat"
• "Skippy su hatırlatmasını aç / kapat", "göz molasını aç / kapat"
• "Skippy sayacı aç / kapat"
• "Skippy tamagotchi paneli", "oyun aç", "şehir aç", "sohbet aç"
• "Skippy pizza ver", "temizle"
• "Skippy otur" / "kalk" · "Skippy sus"
• Sadece "Skippy" dersen komutu 7 saniye bekler."""

_FOLD = str.maketrans("ıİşŞçÇğĞöÖüÜâî", "iissccggoouuai")
UNITS = {"sifir": 0, "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
TENS = {"on": 10, "yirmi": 20, "otuz": 30, "kirk": 40, "elli": 50, "altmis": 60, "yetmis": 70, "seksen": 80, "doksan": 90}


# ------------------------------------------------------------ metin yardımcıları
def lower_tr(s):
    return s.replace("İ", "i").replace("I", "ı").lower()


def fold(s):
    """Küçük harf + Türkçe karakterleri ASCII'ye indir + noktalamayı at."""
    s = lower_tr(s).translate(_FOLD)
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def tokens(text):
    return [t for t in re.split(r"\s+", lower_tr(text).strip()) if t]


EN_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
            "seventeen": 17, "eighteen": 18, "nineteen": 19}
EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def words_to_digits_en(toks):
    out, i = [], 0
    while i < len(toks):
        f = toks[i].lower()
        if f in EN_UNITS or f in EN_TENS or f == "hundred":
            cur, used = 0, False
            while i < len(toks):
                f = toks[i].lower()
                if f in EN_UNITS:
                    cur += EN_UNITS[f]
                elif f in EN_TENS:
                    cur += EN_TENS[f]
                elif f == "hundred":
                    cur = (cur or 1) * 100
                else:
                    break
                used = True
                i += 1
            if used:
                out.append(str(cur))
            continue
        out.append(toks[i])
        i += 1
    return out


def words_to_digits(toks):
    import i18n
    if i18n.is_en():
        return words_to_digits_en(toks)
    return _words_to_digits_tr(toks)


def _words_to_digits_tr(toks):
    """['yirmi','beş','dakika'] -> ['25','dakika']  (sayı sözcükleri rakama; diğerleri aynen)."""
    out, i = [], 0
    while i < len(toks):
        f = fold(toks[i])
        if f in UNITS or f in TENS or f in ("yuz", "bin"):
            total = cur = 0
            used = False
            while i < len(toks):
                f = fold(toks[i])
                if f in UNITS:
                    cur += UNITS[f]
                elif f in TENS:
                    cur += TENS[f]
                elif f == "yuz":
                    cur = (cur or 1) * 100
                elif f == "bin":
                    total += (cur or 1) * 1000
                    cur = 0
                else:
                    break
                used = True
                i += 1
            if used:
                out.append(str(total + cur))
            continue
        out.append(toks[i])
        i += 1
    return out


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def strip_wake(toks, wake, name=""):
    """Baştaki 3 sözcük içinde uyandırma kelimesi (bulanık eşleşmeyle) varsa sonrasını döndürür, yoksa None."""
    aliases = set(WAKE_VARIANTS) | {fold(wake)} | ({fold(name)} if name else set())
    aliases.discard("")
    head = [fold(t) for t in toks[:3]]
    for i in range(len(head)):
        for span in (1, 2):  # "skip pi" gibi bölünmüş tanımalar
            cand = "".join(head[i:i + span])
            if cand and any(cand == a or (len(cand) >= 4 and similar(cand, a) >= 0.75) for a in aliases):
                return toks[i + span:]
    return None


# ------------------------------------------------------------ uygulama dizini
def desktop_dirs():
    home = Path.home()
    return [Path("/usr/share/applications"), Path("/usr/local/share/applications"), home / ".local/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"), home / ".local/share/flatpak/exports/share/applications"]


def parse_desktop(path):
    """(adlar, argv) ya da None. Gizli / terminal / uygulama olmayan kayıtlar atlanır."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    sect, kv = False, {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            sect = line == "[Desktop Entry]"
        elif sect and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            kv.setdefault(k.strip(), v.strip())
    if kv.get("Type") != "Application" or kv.get("NoDisplay", "").lower() == "true" or kv.get("Terminal", "").lower() == "true":
        return None
    exe = re.sub(r"%[fFuUdDnNickvm]", "", kv.get("Exec", "")).replace("%%", "%")
    try:
        argv = shlex.split(exe)
    except ValueError:
        return None
    if not argv:
        return None
    names = [kv[k] for k in ("Name[tr]", "Name", "GenericName[tr]") if kv.get(k)]
    names.append(os.path.basename(argv[0]))
    return names, argv


def build_index(dirs=None):
    """{katlanmış ad: (görünen ad, argv)} — kurulu tüm uygulamalar."""
    idx = {}
    for d in (dirs if dirs is not None else desktop_dirs()):
        try:
            files = sorted(Path(d).glob("*.desktop"))
        except OSError:
            continue
        for f in files:
            r = parse_desktop(f)
            if not r:
                continue
            names, argv = r
            for n in names:
                idx.setdefault(fold(n), (names[0], argv))
    idx.pop("", None)
    return idx


def match_app(query, index):
    """Söylenen ada en yakın uygulama: (görünen ad, argv) ya da None."""
    q = fold(query)
    if not q:
        return None
    if q in index:
        return index[q]
    qc = q.replace(" ", "")
    best, score = None, 0.0
    for name, val in index.items():
        nc = name.replace(" ", "")
        s = 1.0 if nc == qc else (0.9 if len(qc) >= 4 and (nc.startswith(qc) or qc.startswith(nc)) else similar(qc, nc))
        if s > score:
            best, score = val, s
    return best if score >= 0.74 else None


def launch(argv):
    """Uygulamayı bağımsız süreçte başlatır. (başarılı mı, hata)"""
    if not argv or not shutil.which(argv[0]):
        return False, "komut bulunamadı"
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True, ""
    except OSError as ex:
        return False, str(ex)[:60]


# ------------------------------------------------------------ komut yorumlama
class Interpreter:
    def __init__(self, cfg, name="", index=None):
        self.cfg, self.name = cfg, name
        self._index = index
        self.awake_until = 0.0

    @property
    def v(self):
        return settings(self.cfg)

    @property
    def index(self):
        if self._index is None:
            self._index = build_index()
        return self._index

    def resolve_app(self, query):
        """Önce senin takma adların, sonra kurulu uygulamalar."""
        q = fold(query)
        for spoken, target in (self.cfg.get("voice_apps") or {}).items():
            if fold(spoken) == q and str(target).strip():
                try:
                    argv = shlex.split(str(target))
                except ValueError:
                    continue
                if argv and shutil.which(argv[0]):
                    return target, argv
                hit = match_app(target, self.index)
                if hit:
                    return hit
        return match_app(query, self.index)

    def parse(self, text, now=None):
        """-> None (yok say) | ("wake",) | ("action", ad, açık/kapalı/None) | ("reminder", metin) | ("food", komut)
        | ("app", ad, argv) | ("noapp", sorgu) | ("unknown", metin)"""
        now = now if now is not None else time.time()
        toks = tokens(text)
        rest = strip_wake(toks, self.v["wake"], self.name)
        if rest is None:
            if now > self.awake_until:
                return None
            rest = toks  # "Skippy" dedikten sonra gelen komut
        self.awake_until = 0.0
        if not rest:
            self.awake_until = now + AWAKE_S
            return ("wake",)
        return self.command(rest)

    def command(self, rest):
        T = [fold(t) for t in rest]
        T = [t for t in T if t]
        J = " ".join(T)

        def has(*ws, exact=False):
            return any((t == w) if exact else t.startswith(w) for t in T for w in ws)

        opening = has(*OPEN_VERBS) or ("ac" in T)
        closing = has(*CLOSE_VERBS)
        state = False if closing else (True if opening or not closing else None)
        if opening:  # senin takma adın yerleşik komutlardan önce gelir ("oyun kütüphanesi aç" -> steam)
            q = " ".join(t for t in T if t not in OPEN_VERBS and t != "ac")
            for spoken in (self.cfg.get("voice_apps") or {}):
                if q and fold(spoken) == q:
                    hit = self.resolve_app(q)
                    if hit:
                        return ("app", hit[0], hit[1])
        en = self.command_en(T, rest, state, has)
        if en:
            return en
        if has("sustur") or "sus" in T or has("sessiz"):
            return ("action", "hush", None)
        if (has("su", exact=True) or has("goz", exact=True)) and (has("hatirlat") or has("mola")):
            return ("action", "water" if "su" in T else "eye", state)
        if has("hatirlatici") or (has("hatirlat") and "ekle" in T):
            return ("action", "reminders_add", None) if has("ekle") else ("action", "reminders_show", None)
        if has("hatirlat"):
            drop = ("diye", "bana", "lutfen", "mi", "misin", "musun", "mu")
            kept = [t for t in rest if not fold(t).startswith("hatirlat") and fold(t) not in drop]
            return ("reminder", " ".join(words_to_digits(kept)))
        if has("not", "defter"):
            return ("action", "notes", None)
        if has("sayac", "kronometre") or "geri sayim" in J:
            return ("action", "countdown", state)
        if has("tamagotchi", "tamagoci", "tamagochi") or ("durum" in T and has("panel")):
            return ("action", "tama_panel", None)
        if has("sehir", "neon"):
            return ("action", "city", None)
        if has("shooter", "slaughter") or (has("oyun") and not has("oyna")):
            return ("action", "game", None)
        if has("sohbet"):
            return ("action", "chat", None)
        if "otur" in T or has("oturt"):
            return ("action", "sit", None)
        if "kalk" in T or "ayaga" in T:
            return ("action", "stand", None)
        import tama  # tembel: yalnızca yemek / temizlik komutları için
        cmd = tama.parse_command(" ".join(rest))
        if cmd and (cmd.startswith("food:") or cmd == "clean") and not opening:
            return ("food", cmd)
        if opening:
            query = " ".join(t for t in T if t not in OPEN_VERBS and t != "ac")
            hit = self.resolve_app(query) if query else None
            return ("app", hit[0], hit[1]) if hit else ("noapp", query)
        return ("unknown", " ".join(rest))


def _command_en(self, T, rest, state, has):
    """İngilizce komutlar (Türkçe ile birlikte her zaman anlaşılır)."""
    if has("hush", "quiet", "silence", "mute") or ("shut" in T and "up" in T):
        return ("action", "hush", None)
    on = "off" not in T and not any(t in ("close", "stop", "disable") for t in T)
    if ("water" in T or "eye" in T) and (has("remind") or has("break")):
        return ("action", "water" if "water" in T else "eye", on)
    if has("reminders") or (("reminder" in T) and any(w in T for w in ("add", "new", "create", "set"))):
        return ("action", "reminders_add", None) if any(w in T for w in ("add", "new", "create", "set")) else ("action", "reminders_show", None)
    if has("remind"):
        drop = ("me", "to", "please", "that", "about", "can", "you", "could")
        kept = [t for t in rest if t.lower().rstrip(".,!?") not in drop and not t.lower().startswith("remind")]
        return ("reminder", " ".join(words_to_digits(kept)))
    if has("notes", "notepad", "note") and "reminder" not in T:
        return ("action", "notes", None)
    if has("timer", "countdown", "stopwatch"):
        return ("action", "countdown", on)
    if has("tamagotchi") or ("status" in T and "panel" in T):
        return ("action", "tama_panel", None)
    if "city" in T or has("neon"):
        return ("action", "city", None)
    if has("shooter", "slaughter") or ("game" in T and "open" in T) or ("play" in T and "game" in T):
        return ("action", "game", None)
    if "chat" in T:
        return ("action", "chat", None)
    if "sit" in T:
        return ("action", "sit", None)
    if "stand" in T or ("get" in T and "up" in T):
        return ("action", "stand", None)
    return None


Interpreter.command_en = _command_en


def settings(cfg):
    v = cfg.setdefault("voicecmd", {})
    for k, d in DEFAULTS.items():
        v.setdefault(k, d)
    if v["engine"] not in ("template", "vosk", "custom"):
        v["engine"] = "template"
    return v


# ------------------------------------------------------------ mikrofon dinleyici
def capture_cmd():
    if shutil.which("parec"):
        return ["parec", "--format=s16le", "--rate=16000", "--channels=1"]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", "16000", "-c", "1"]
    if shutil.which("pw-record"):
        return ["pw-record", "--format", "s16", "--rate", "16000", "--channels", "1", "-"]
    return None


def problem(v):
    """Dinleme başlatılamayacaksa nedenini söyler, sorun yoksa None."""
    if v["engine"] == "template":
        return None if capture_cmd() else "Mikrofonu okuyacak program yok. Kur: sudo pacman -S alsa-utils (ya da pulseaudio-utils / pipewire)."
    if v["engine"] == "custom":
        return None if v["listen_cmd"].strip() else "Dinleme komutu boş. Her tanınan cümleyi satır satır yazdıran bir komut gir."
    try:
        import vosk  # noqa: F401
    except Exception:
        return "Vosk kurulu değil. Kurmak için: pip install vosk (Manjaro'da: python -m venv ya da --break-system-packages)."
    if not v["model"] or not os.path.isdir(v["model"]):
        return "Vosk için bir Türkçe model klasörü seçmelisin (vosk-model-small-tr gibi; alphacephei.com/vosk/models)."
    if capture_cmd() is None:
        return "Mikrofonu okuyacak program yok. Kur: sudo pacman -S alsa-utils (ya da pulseaudio-utils / pipewire)."
    return None


class Listener:
    def __init__(self, cfg, muted=lambda: False):
        self.cfg, self.muted = cfg, muted
        self.q = queue.Queue()
        self.proc = None
        self.thread = None
        self.stopping = threading.Event()
        self.error = None

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        """Hata varsa metnini döndürür; başladıysa None."""
        if self.running():
            return None
        why = problem(settings(self.cfg))
        if why:
            return why
        self.stopping.clear()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return None

    def stop(self):
        self.stopping.set()
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def poll(self):
        """(tanınan cümleler, hata ya da None)"""
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                break
        err, self.error = self.error, None
        return out, err

    def _spawn(self, argv, shell=False):
        self.proc = subprocess.Popen(["sh", "-c", argv] if shell else argv, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        return self.proc

    def _run(self):
        v = settings(self.cfg)
        try:
            if v["engine"] == "custom":
                p = self._spawn(v["listen_cmd"], shell=True)
                for raw in iter(p.stdout.readline, b""):
                    if self.stopping.is_set():
                        break
                    text = raw.decode("utf-8", "replace").strip()
                    if text and not self.muted():
                        self.q.put(text)
            else:
                import vosk
                vosk.SetLogLevel(-1)
                rec = vosk.KaldiRecognizer(vosk.Model(v["model"]), 16000)
                p = self._spawn(capture_cmd())
                while not self.stopping.is_set():
                    data = p.stdout.read(4000)
                    if not data:
                        break
                    if self.muted():  # pet konuşurken kendi sesini duymasın
                        rec.Reset()
                        continue
                    if rec.AcceptWaveform(data):
                        text = json.loads(rec.Result()).get("text", "").strip()
                        if text:
                            self.q.put(text)
            if not self.stopping.is_set():
                self.error = "Mikrofon akışı kapandı, dinleme durdu."
        except Exception as ex:
            self.error = f"Dinleme hatası: {str(ex)[:80]}"
        finally:
            self.stop()
