"""Kendi sesinle sesli komut: hiçbir şey indirmeden çalışır.

Genel konuşma tanıma yapmaz; senin söylediğin kısa komutları SENİN SESİNDEN öğrenir (komut başına ~3 kayıt) ve
sonra aynı cümleyi söylediğinde eşleştirir (MFCC özellikleri + DTW). Sadece Python standart kütüphanesi ve mikrofon
okuyan bir program (parec / arecord / pw-record) gerekir. Tek kişiye özeldir, küçük bir komut listesiyle iyi çalışır.
Öğretilen komutlar voiceprints.json dosyasında tutulur. Tanınan komutun metni normal sesli komut hattına girer."""
import array
import cmath
import json
import math
import os
import threading
import time
from pathlib import Path

try:  # isteğe bağlı hızlandırma: numpy varsa özellik çıkarımı ~50 kat hızlanır; yoksa saf Python
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

import voicecmd

RATE = 16000
FRAME_BYTES = 960           # 30 ms (480 örnek)
WIN, NFFT, HOP = 480, 512, 480
N_MEL, N_CEP = 20, 12
TRAIN_SAMPLES = 3
SENS = {"Sıkı": 0.8, "Normal": 1.0, "Rahat": 1.3}


# ------------------------------------------------------------ özellik çıkarımı (MFCC, saf Python)
def _mel(f):
    return 2595 * math.log10(1 + f / 700)


def _imel(m):
    return 700 * (10 ** (m / 2595) - 1)


def _build_tables():
    rev, bits = [], NFFT.bit_length() - 1
    for i in range(NFFT):
        rev.append(int(format(i, f"0{bits}b")[::-1], 2))
    tw = [cmath.exp(-2j * math.pi * k / NFFT) for k in range(NFFT // 2)]
    ham = [0.54 - 0.46 * math.cos(2 * math.pi * i / (WIN - 1)) for i in range(WIN)]
    edges = [_imel(_mel(100) + (_mel(7000) - _mel(100)) * i / (N_MEL + 1)) for i in range(N_MEL + 2)]
    bin_hz = RATE / NFFT
    bank = []
    for m in range(1, N_MEL + 1):
        lo, mid, hi = edges[m - 1], edges[m], edges[m + 1]
        ws = []
        for b in range(int(lo / bin_hz), int(hi / bin_hz) + 2):
            f = b * bin_hz
            w = (f - lo) / (mid - lo) if lo < f <= mid else ((hi - f) / (hi - mid) if mid < f < hi else 0.0)
            ws.append((b, w)) if w > 0 else None
        bank.append(ws)
    dct = [[math.cos(math.pi * k * (m + 0.5) / N_MEL) for m in range(N_MEL)] for k in range(1, N_CEP + 1)]
    return rev, tw, ham, bank, dct


_T = None


def _tables():
    global _T
    if _T is None:
        _T = _build_tables()
    return _T


def _fft_power(frame):
    rev, tw, _, _, _ = _tables()
    x = [complex(frame[rev[i]], 0) for i in range(NFFT)]
    size = 2
    while size <= NFFT:
        half, step = size // 2, NFFT // size
        for start in range(0, NFFT, size):
            for k in range(half):
                a, b = x[start + k], x[start + k + half] * tw[k * step]
                x[start + k], x[start + k + half] = a + b, a - b
        size *= 2
    return [abs(c) ** 2 for c in x[:NFFT // 2 + 1]]


def features(samples):
    """int16 örnek listesi -> [kare][12] kepstrum özellikleri (klip ortalaması çıkarılmış, ses seviyesinden bağımsız).
    Çok kısaysa None."""
    n = len(samples)
    if n < WIN * 3:
        return None
    _, _, ham, bank, dct = _tables()
    if _np is not None:
        return _features_np(samples, ham, bank, dct)
    x = [s / 32768.0 for s in samples]
    x = [x[0]] + [x[i] - 0.97 * x[i - 1] for i in range(1, n)]  # ön vurgu
    feats = []
    for start in range(0, n - WIN + 1, HOP):
        fr = [x[start + i] * ham[i] for i in range(WIN)] + [0.0] * (NFFT - WIN)
        pw = _fft_power(fr)
        logmel = [math.log(sum(pw[b] * w for b, w in ws if b < len(pw)) + 1e-10) for ws in bank]
        feats.append([sum(c * l for c, l in zip(row, logmel)) for row in dct])
        time.sleep(0.0005)  # arayüz iş parçacığına GIL bırak (konuşma anında pet donmasın)
    mean = [sum(f[i] for f in feats) / len(feats) for i in range(N_CEP)]
    return [[f[i] - mean[i] for i in range(N_CEP)] for f in feats]


_NP = {}


def _features_np(samples, ham, bank, dct):
    n = len(samples)
    x = _np.asarray(samples, dtype=_np.float64) / 32768.0
    x = _np.concatenate(([x[0]], x[1:] - 0.97 * x[:-1]))
    if not _NP:
        fb = _np.zeros((N_MEL, NFFT // 2 + 1))
        for m, ws in enumerate(bank):
            for b, w in ws:
                if b < fb.shape[1]:
                    fb[m, b] = w
        _NP["ham"], _NP["fb"], _NP["dct"] = _np.asarray(ham), fb, _np.asarray(dct)
    starts = range(0, n - WIN + 1, HOP)
    frames = _np.stack([x[s0:s0 + WIN] * _NP["ham"] for s0 in starts])
    pw = _np.abs(_np.fft.rfft(frames, n=NFFT, axis=1)) ** 2
    logmel = _np.log(pw @ _NP["fb"].T + 1e-10)
    feats = logmel @ _NP["dct"].T
    feats = feats - feats.mean(axis=0)
    return feats.tolist()


def dtw(a, b):
    """İki özellik dizisi arasındaki normalize DTW uzaklığı (dar bantlı)."""
    n, m = len(a), len(b)
    if n == 0 or m == 0 or max(n, m) > 2.2 * min(n, m):  # süreleri çok farklı: aynı cümle olamaz
        return float("inf")
    band = int(0.35 * max(n, m)) + abs(n - m)
    inf = float("inf")
    prev = [inf] * (m + 1)
    prev[0] = 0.0
    for i in range(1, n + 1):
        cur = [inf] * (m + 1)
        for j in range(max(1, i - band), min(m, i + band) + 1):
            d = math.dist(a[i - 1], b[j - 1])
            cur[j] = d + min(prev[j], cur[j - 1], prev[j - 1])
        prev = cur
        if i % 8 == 0:
            time.sleep(0.0002)  # GIL'i arayüze bırak
    return prev[m] / (n + m)


def threshold(sample_feats):
    """Aynı komutun kayıtları arası en büyük uzaklığın 1.5 katı: bunun altı 'aynı komut' sayılır."""
    ds = [dtw(sample_feats[i], sample_feats[j]) for i in range(len(sample_feats)) for j in range(i + 1, len(sample_feats))]
    ds = [d for d in ds if d != float("inf")]
    return max(ds) * 1.5 if ds else 0.0


def label_distance(f, samples):
    ds = sorted(dtw(f, s) for s in samples)
    return sum(ds[:2]) / len(ds[:2])  # en iyi iki kaydın ortalaması


def match(f, items, sens=1.0):
    """En uygun öğretilmiş komutun etiketi; yeterince benzemiyorsa ya da iki komut arasında kararsızsa None."""
    scored = sorted((label_distance(f, it["samples"]), it) for it in items if it["samples"])
    if not scored:
        return None
    d1, it1 = scored[0]
    if d1 > it1["thr"] * sens or d1 == float("inf"):
        return None
    if len(scored) > 1 and scored[1][0] < d1 * 1.12:  # iki komuta da yakın: tahmin etme
        return None
    return it1["label"]


# ------------------------------------------------------------ öğretilen komutların deposu
def default_path(base_dir):
    try:
        d = Path(base_dir).parent
        d.mkdir(parents=True, exist_ok=True)
        return d / "voiceprints.json"
    except Exception:
        return Path.home() / ".pet-voiceprints.json"


class PrintStore:
    def __init__(self, path):
        self.path = Path(path)
        self.items = []
        self.stale = []  # (artık kullanılmıyor; pet.py uyumu için duruyor)
        try:
            for it in json.loads(self.path.read_text(encoding="utf-8")).get("items", []):
                if it["label"] and it["samples"] and float(it["thr"]) > 0:
                    self.items.append({"label": str(it["label"]), "thr": float(it["thr"]),
                                       "samples": [[list(map(float, fr)) for fr in s] for s in it["samples"]]})
        except (OSError, ValueError, KeyError, TypeError):
            self.items = []

    def labels(self):
        return [it["label"] for it in self.items]

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"items": [{"label": it["label"], "thr": round(it["thr"], 4),
                                                  "samples": [[[round(v, 3) for v in fr] for fr in s] for s in it["samples"]]}
                                                 for it in self.items]}), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except OSError:
            return False

    def add(self, label, samples, thr):
        """Aynı etiket varsa değiştirir. Yeni liste atanır (dinleyici iş parçacığı eskisini güvenle okur)."""
        items = [it for it in self.items if it["label"] != label]
        items.append({"label": label, "thr": thr, "samples": samples})
        self.items = items
        return self.save()

    def remove(self, label):
        self.items = [it for it in self.items if it["label"] != label]
        return self.save()


# ------------------------------------------------------------ konuşma başı / sonu algılama
class Vad:
    """30 ms'lik karelerden cümle keser: ortam gürültüsüne uyum sağlar, kısa tıkırtıları atar."""
    START_FRAMES, END_FRAMES, MIN_FRAMES, MAX_FRAMES, PRE = 3, 20, 10, 150, 8

    def __init__(self):
        self.reset()

    def reset(self):
        self.noise = 150.0
        self.hot = self.cold = 0
        self.active = False
        self.buf = []
        self.pre = []

    def feed(self, data):
        a = array.array("h")
        a.frombytes(data[:len(data) // 2 * 2])
        if not a:
            return None
        rms = math.sqrt(sum(s * s for s in a) / len(a))
        thr = max(450.0, self.noise * 3.5)
        loud = rms > thr
        if not self.active:
            if not loud:
                self.noise = 0.97 * self.noise + 0.03 * min(rms, 2000)
            self.pre.append(a)
            self.pre = self.pre[-self.PRE:]
            self.hot = self.hot + 1 if loud else 0
            if self.hot >= self.START_FRAMES:
                self.active, self.cold = True, 0
                self.buf = list(self.pre)
                self.pre = []
            return None
        self.buf.append(a)
        self.cold = 0 if loud else self.cold + 1
        if self.cold >= self.END_FRAMES or len(self.buf) >= self.MAX_FRAMES:
            frames = self.buf[:len(self.buf) - self.cold] if self.cold else self.buf
            self.active, self.hot, self.cold, self.buf = False, 0, 0, []
            if len(frames) < self.MIN_FRAMES:
                return None
            out = []
            for fr in frames:
                out.extend(fr)
            return out
        return None


# ------------------------------------------------------------ dinleyici
class TemplateListener(voicecmd.Listener):
    """voicecmd.Listener ile aynı arayüz. train = {"label", "need", "samples": []} ise eşleştirme yerine kayıt alır."""

    def __init__(self, cfg, store, muted=lambda: False):
        super().__init__(cfg, muted)
        self.store = store
        self.train = None
        self.events = []
        self._lock = threading.Lock()

    def start(self, force=False):
        if self.running():
            return None
        if voicecmd.capture_cmd() is None:
            return "Mikrofonu okuyacak program yok. Kur: sudo pacman -S alsa-utils (ya da pulseaudio-utils / pipewire)."
        if not force and not self.store.items:
            return "Önce en az bir komut öğretmelisin: Sesli komut → ➕ Komut öğret."
        self.stopping.clear()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return None

    def pop_events(self):
        with self._lock:
            ev, self.events = self.events, []
        return ev

    def _event(self, *e):
        with self._lock:
            self.events.append(e)

    def _run(self):
        try:
            p = self._spawn(voicecmd.capture_cmd())
            vad = Vad()
            while not self.stopping.is_set():
                data = p.stdout.read(FRAME_BYTES)
                if not data:
                    break
                if self.muted():  # pet konuşurken kendi sesini duymasın
                    vad.reset()
                    continue
                utt = vad.feed(data)
                if utt is not None:
                    self._handle(utt)
            if not self.stopping.is_set():
                self.error = "Mikrofon akışı kapandı, dinleme durdu."
        except Exception as ex:
            self.error = f"Dinleme hatası: {str(ex)[:80]}"
        finally:
            self.stop()

    def _handle(self, samples):
        f = features(samples)
        if f is None:
            return
        tr = self.train
        if tr is not None:
            tr["samples"].append(f)
            n = len(tr["samples"])
            if n >= tr["need"]:
                self.train = None
                self._event("trained", tr["label"], tr["samples"], threshold(tr["samples"]))
            else:
                self._event("sample", n)
            return
        sens = float(voicecmd.settings(self.cfg).get("sens", 1.0))
        label = match(f, self.store.items, sens)
        if label:
            self.q.put(label)
