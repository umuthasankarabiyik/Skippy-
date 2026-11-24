"""Sesli konuşma: Pet'in replikleri bir ses motoruyla yüksek sesle okunur.

Motorlar (ayarlar cfg["voice"] içinde):
  espeak  — espeak-ng (robotik ama her yerde kurulu; sudo pacman -S espeak-ng).
  piper   — Piper nöral TTS; kendi .onnx ses modelini seçersin (doğal Türkçe sesler var).
  custom  — Kendi komutun: istediğin sesli asistan / API / program. Komutta {text} yazılan yere replik gelir
            (kabuk güvenli: metin ortam değişkeniyle geçer). {text} yoksa metin komutun stdin'ine verilir.
Konuşma arka planda ayrı süreçte çalışır; yeni replik gelince önceki susturulur. Qt'ye bağımlı değildir.
"""
import json
import os
import re

import i18n
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

ENGINES = {"espeak": "eSpeak NG", "piper": "Piper (kendi ses modelin)", "custom": "Özel komut"}
DEFAULTS = {"on": False, "engine": "espeak", "espeak_voice": "tr", "speed": 150, "pitch": 50,
            "piper_model": "", "custom_cmd": ""}
MAX_CHARS = 400
HINTS = {
    "espeak": "espeak-ng kurulu değil. Kurmak için: sudo pacman -S espeak-ng",
    "piper": "piper bulunamadı. Kurmak için: yay -S piper-tts-bin (ya da pip install piper-tts), "
             "sonra bir .onnx ses modeli indirip menüden seç.",
}
EXAMPLE_CMD = 'edge-tts --voice tr-TR-AhmetNeural --text {text} --write-media /tmp/mermi.mp3 && mpv --no-video /tmp/mermi.mp3'


# ------------------------------------------------------------ Qt'siz yardımcılar
def settings(cfg):
    v = cfg.setdefault("voice", {})
    for k, d in DEFAULTS.items():
        v.setdefault(k, d)
    if v["engine"] not in ENGINES:
        v["engine"] = "espeak"
    return v


def clean_text(text):
    """Okunmayacak şeyleri ayıkla: harf içermeyen / çok kısa replikler None döner."""
    t = re.sub(r"[·•—–|/\\*_#<>~^]+", " ", text.replace("…", ". "))
    t = re.sub(r"\s+", " ", t).strip()
    if len(re.findall(r"[^\W\d_]", t)) < 2 or re.fullmatch(r"[zZ\s.…!]+", t):  # "Zzz..." gibi sesler okunmaz
        return None
    return t[:MAX_CHARS]


def clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def piper_rate(model):
    """Modelin yanındaki .onnx.json'dan örnekleme hızı (yoksa 22050)."""
    for cand in (Path(str(model) + ".json"), Path(model).with_suffix(".json")):
        try:
            return int(json.loads(cand.read_text(encoding="utf-8"))["audio"]["sample_rate"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return 22050


def player_cmd(rate):
    """Ham 16-bit mono PCM okuyan oynatıcı komutu (paplay > aplay > pw-play)."""
    if shutil.which("paplay"):
        return f"paplay --raw --rate={rate} --format=s16le --channels=1"
    if shutil.which("aplay"):
        return f"aplay -q -r {rate} -f S16_LE -t raw -"
    if shutil.which("pw-play"):
        return f"pw-play --rate {rate} --format s16 --channels 1 -"
    return None


def problem(v):
    """Seçili motor çalışmayacaksa nedenini söyler, sorun yoksa None."""
    e = v["engine"]
    if e == "espeak":
        return None if shutil.which("espeak-ng") or shutil.which("espeak") else HINTS["espeak"]
    if e == "piper":
        if not shutil.which("piper"):
            return HINTS["piper"]
        if not v["piper_model"] or not os.path.isfile(v["piper_model"]):
            return "Piper için bir .onnx ses modeli seçmelisin (menü: Ses modelini seç)."
        if player_cmd(22050) is None:
            return "Ses çalacak program yok (paplay, aplay ya da pw-play kurulu olmalı)."
        return None
    if not v["custom_cmd"].strip():
        return "Özel komut boş. Örnek: " + EXAMPLE_CMD
    return None


def build(v, text):
    """(argv, env, stdin_verisi) — kabuğa metin gömülmez, ortam değişkeniyle geçer."""
    e = v["engine"]
    env = dict(os.environ, MERMI_TEXT=text)
    if e == "espeak":
        exe = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak-ng"
        voice = re.sub(r"[^\w+\-]", "", v["espeak_voice"]) or "tr"
        if voice == "tr" and i18n.is_en():
            voice = "en"  # İngilizce modda varsayılan eSpeak sesi İngilizce
        return [exe, "-v", voice, "-s", str(clamp(v["speed"], 80, 400, 150)),
                "-p", str(clamp(v["pitch"], 0, 99, 50)), "--", text], env, None
    if e == "piper":
        model = v["piper_model"]
        script = ('printf %s "$MERMI_TEXT" | piper --model ' + shlex.quote(model) + " --output-raw 2>/dev/null | "
                  + player_cmd(piper_rate(model)))
        return ["sh", "-c", script], env, None
    cmd = v["custom_cmd"].strip()
    if "{text}" in cmd:
        return ["sh", "-c", cmd.replace("{text}", '"$MERMI_TEXT"')], env, None
    return ["sh", "-c", cmd], env, text


class Speaker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None

    @property
    def v(self):
        return settings(self.cfg)

    def enabled(self):
        return bool(self.v["on"])

    def busy(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        p, self.proc = self.proc, None
        if p is None:
            return
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)  # sh + piper + oynatıcı birlikte susar
            except OSError:
                pass
        try:
            p.wait(timeout=0.5)
        except Exception:
            pass

    def speak(self, text, force=False):
        """Okur; başlatılamazsa nedenini döndürür, olduysa (ya da kapalıysa / okunmayacaksa) None."""
        if not (force or self.enabled()):
            return None
        t = clean_text(text)
        if t is None:
            return None
        why = problem(self.v)
        if why:
            return why
        self.stop()
        argv, env, data = build(self.v, t)
        try:
            self.proc = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE if data else subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            if data:
                try:
                    self.proc.stdin.write(data.encode("utf-8"))
                    self.proc.stdin.close()
                except OSError:
                    pass
        except OSError as ex:
            self.proc = None
            return f"Ses motoru başlatılamadı: {str(ex)[:60]}"
        return None
