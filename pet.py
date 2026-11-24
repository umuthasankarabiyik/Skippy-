#!/usr/bin/env python3
"""Masaüstü Pet — Manjaro / Linux için küçük bir masaüstü arkadaşı.

Çalıştır:   python3 pet.py
Otomatik başlatma:   python3 pet.py --install-autostart
Doğum günü sürprizini denemek (kaydetmez):   python3 pet.py --preview-birthday
"""
import html
import math
import os
import random
import shutil
import subprocess
import sys
import time

# Wayland'de uygulamalar pencere konumunu kendileri belirleyemez; bu yüzden
# varsayılan olarak XWayland (xcb) kullanıyoruz. İstersen QT_QPA_PLATFORM=wayland ile değiştir.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import i18n

i18n.install_qt()  # İngilizce modda Qt metinlerini çevirir (Türkçede hiçbir şey yapmaz)
T = i18n.T

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QUrl
from PyQt6.QtGui import (QAction, QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QIcon,
                         QMovie, QPainter, QPen, QPixmap, QPolygonF, QTextDocument)
from PyQt6.QtWidgets import (QApplication, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                             QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget, QFileDialog)

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    HAVE_QT_AUDIO = True
except Exception:  # qt6-multimedia kurulu değilse harici oynatıcıya düşeriz
    HAVE_QT_AUDIO = False

import countdown
import gametalk
import hud
import lines
import notes
import corex as core
import streak
import tama
import bullet
import tts
import userdata
import voicecmd
import voiceprint

FOREVER = 10 ** 9  # "bu durumda sonsuza kadar kal" için kare sayısı

FUR = QColor("#F2A65A")
FUR_DARK = QColor("#D9822B")
BELLY = QColor("#FFE3C2")
LINE = QColor("#5B3A1E")
PINK = QColor("#F5A3B5")


# ------------------------------------------------------------------ çizim
draw_cat = bullet.draw_bullet  # varsayılan karakter: kırmızı güneş gözlüklü, mavi kollu mermi


def draw_zzz(p, t):
    f = QFont("Sans", 12)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#6B7FD7"))
    p.drawText(QPointF(88, 24 - (t // 12 % 3) * 3), "z")
    p.drawText(QPointF(99, 12 - (t // 12 % 3) * 3), "Z")


def make_icon():
    pm = QPixmap(120, 120)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_cat(p, 0, "idle", False)
    p.end()
    return QIcon(pm)


# ------------------------------------------------- kullanıcı resimleri (png/gif)
class Asset:
    """Bir PNG (sabit) ya da GIF (hareketli) görsel; kutuya sığacak şekilde küçültülür."""

    def __init__(self, path, key, px):
        self.key = key
        self.movie = None
        self.pixmap = None
        if str(path).lower().endswith(".gif"):
            m = QMovie(str(path))
            if m.isValid() and m.jumpToFrame(0):
                first = m.currentPixmap()
                if not first.isNull():
                    m.setScaledSize(first.size().scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio))
                    self.movie = m
        else:
            pm = QPixmap(str(path))
            if not pm.isNull():
                self.pixmap = pm.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)

    @property
    def ok(self):
        return self.movie is not None or self.pixmap is not None

    def frame(self):
        return self.movie.currentPixmap() if self.movie is not None else self.pixmap

    def start(self):
        if self.movie is not None:
            self.movie.start()

    def stop(self):
        if self.movie is not None:
            self.movie.stop()

    def tick(self):
        # tek seferlik GIF'ler bitince tekrar başlasın
        if self.movie is not None and self.movie.state() == QMovie.MovieState.NotRunning:
            self.movie.start()


# --------------------------------------------------------------------- ses
EXTERNAL_PLAYERS = (
    ("paplay", []),
    ("pw-play", []),
    ("mpv", ["--no-video", "--really-quiet"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("aplay", ["-q"]),
)


class Sounds:
    """Önce Qt ses motoru, çalışmazsa sistemdeki oynatıcılardan biri (paplay, mpv...)."""

    def __init__(self):
        self.player = None
        self.out = None
        self.last = None
        self.warned = False
        self._old = None
        if HAVE_QT_AUDIO:
            try:
                self.player = QMediaPlayer()
                self.out = QAudioOutput()
                self.out.setVolume(0.8)
                self.player.setAudioOutput(self.out)
                self.player.errorOccurred.connect(self.on_error)
            except Exception:
                self.player = None

    def on_error(self, *_):
        self._old, self.player = self.player, None  # nesneyi hemen silme
        if self.last:
            self.external(self.last)

    def play(self, path):
        self.last = str(path)
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(self.last))
            self.player.play()
        else:
            self.external(self.last)

    def external(self, path):
        for tool, args in EXTERNAL_PLAYERS:
            exe = shutil.which(tool)
            if exe:
                try:
                    subprocess.Popen([exe, *args, path], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                    return
                except OSError:
                    continue
        if not self.warned:
            self.warned = True
            print("Ses çalınamadı. Çözüm: sudo pacman -S qt6-multimedia qt6-multimedia-ffmpeg")


# ------------------------------------------------------------ konuşma balonu
class Bubble(hud.HudWidget):
    """Pet'in üstünde çıkan, tıklamaları engellemeyen HUD çerçeveli konuşma balonu / bildirim.
    kind="say": konuşma balonu · kind="alert": "BİLDİRİM" etiketli bildirim çerçevesi.
    Açılırken ve kapanırken glitch yapar; görünürken metin değişirse kısa titrer."""
    MAX_TEXT_W = 250
    TEXT_COLOR = "#FFD6D6"
    PAD = {"say": (16, 17, 16, 12), "alert": (16, 24, 16, 12)}  # sol, üst, sağ, alt (çerçeve içi boşluk)

    def __init__(self):
        super().__init__()
        self.kind = "say"
        self.doc = QTextDocument()
        self.inner = (0, 0)
        self.anchor = QPoint()
        f = QFont("Sans")
        f.setPixelSize(13)
        self.doc.setDefaultFont(f)
        self.doc.setDocumentMargin(0)
        self.tag_font = QFont("Sans")
        self.tag_font.setPixelSize(9)
        self.tag_font.setBold(True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.glitch_hide)

    def say(self, text, anchor, ms, kind="say"):
        self.kind = kind
        self.layout_text(text)
        self.reposition(anchor)
        if self.isVisible() and self._gl.mode != "out":
            self.glitch_pulse()  # görünürken metin değişti: kısa titreme
        else:
            self.glitch_show()   # kapalıysa aç; kapanma sürüyorsa iptal edip yeniden aç
        self.raise_()
        self.timer.start(ms)

    def layout_text(self, text):
        self.doc.setHtml(f'<span style="color:{self.TEXT_COLOR}">{html.escape(text).replace(chr(10), "<br>")}</span>')
        self.doc.setTextWidth(-1)
        tw = min(self.MAX_TEXT_W, max(48, math.ceil(self.doc.idealWidth()) + 2))
        self.doc.setTextWidth(tw)
        left, top, right, bottom = self.PAD[self.kind]
        iw = max(tw + left + right, 110 if self.kind == "alert" else 96)
        ih = math.ceil(self.doc.size().height()) + top + bottom
        self.inner = (iw, ih)
        self.setFixedSize(iw + 2 * hud.MARGIN, ih + 2 * hud.MARGIN)

    def reposition(self, anchor=None):
        if anchor is not None:
            self.anchor = anchor
        scr = QApplication.primaryScreen().availableGeometry()
        m = hud.MARGIN
        x = self.anchor.x() - self.width() // 2
        y = self.anchor.y() - self.height() + m  # çerçevenin alt kenarı anchor'da dursun
        x = max(scr.x() - m, min(x, scr.x() + scr.width() - self.width() + m))
        self.move(x, max(scr.y() - m, y))

    def draw(self, p):
        m = hud.MARGIN
        iw, ih = self.inner
        alert = self.kind == "alert"
        tag = "BİLDİRİM"
        tag_w = QFontMetrics(self.tag_font).horizontalAdvance(tag) + 14 if alert else 0
        hud.paint_frame(p, m, m, iw, ih, hud.RED, 1 if alert else 0, tag_w)
        if alert:
            p.setFont(self.tag_font)
            p.setPen(QColor(*hud.PANEL_BG[:3]))
            p.drawText(QPointF(m + 7, m + 11), tag)
        left, top = self.PAD[self.kind][:2]
        p.save()
        p.translate(m + left, m + top)
        self.doc.drawContents(p)
        p.restore()


# ---------------------------------------------------------------- sohbet
class ChatWindow(hud.GlitchWindow, QWidget):
    def __init__(self, pet):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.pet = pet
        self.last = ""
        self.setWindowTitle(pet.cfg["name"])
        self.resize(330, 400)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Bir şey yaz… (örn: 25 dakika sonra çayı demle)")
        self.input.returnPressed.connect(self.send)
        lay = QVBoxLayout(self)
        lay.addWidget(self.log)
        lay.addWidget(self.input)
        self.add(pet.cfg["name"], "Selam! Benimle sohbet edebilir, hatırlatıcı kurdurabilirsin. "
                                  "'otur', 'kalk', 'uyu' diyebilirsin. 'yardım' yaz, neler yapabildiğimi anlatayım.")

    def add(self, who, text):
        who, text = T(who), T(text)
        self.log.append(f"<b>{html.escape(who)}:</b> {html.escape(text).replace(chr(10), '<br>')}")

    def reply(self, text):
        text = lines.strip_emoji(T(text))
        self.add(self.pet.cfg["name"], text)
        self.pet.say(text)
        self.pet.sound("chat")

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.add("Sen", text)

        # 1) hatırlatıcı  2) komut (otur/kalk/uyu/uyan)  3) internetsiz hazır yanıt  4) Claude
        parsed = core.parse_reminder(text)
        if parsed:
            due, what = parsed
            self.pet.store.add(due, what)
            self.reply(f"Tamam! {core.fmt_due(due)} hatırlatacağım: {what}")
            return

        cmd = core.parse_command(text)
        if cmd:
            self.reply(self.pet.do_command(cmd))
            return

        tcmd = tama.parse_command(text)
        if tcmd:
            self.reply(self.pet.do_tama(tcmd))
            self.pet.refresh_tama_panel()
            return

        ans = self.pet.chat_command(text)  # "steam aç", "not defterini aç" gibi uygulama / arayüz komutları
        if ans:
            self.reply(ans)
            return

        brain = self.pet.brain  # yalnızca yerel sohbet (internet / API yok)
        self.reply(brain.local_reply(text, api=False) or brain.offline_reply(text))


# ------------------------------------------------------------------- pet
def make_action(menu, text, fn, checked=None):
    a = QAction(text, menu)
    if checked is None:
        a.triggered.connect(lambda _=False: fn())
    else:
        a.setCheckable(True)
        a.setChecked(checked)
        a.triggered.connect(lambda c=False: fn(c))
    menu.addAction(a)
    return a


class Pet(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Pet")

        core.ensure_dirs()
        self.cfg = core.load_config()
        self.cfg.pop("api_key", None)  # Claude API özelliği kaldırıldı
        self.px = max(60, min(400, int(self.cfg.get("size", 120))))
        self.setFixedSize(self.px, self.px)
        self.store = core.ReminderStore()
        self.brain = core.Brain(self.cfg)
        self.bubble = Bubble()
        self.pill = countdown.Pill()  # otur/kalk geri sayım etiketi
        self.cd = countdown.Countdown()
        self.sounds = Sounds()
        self.chat = None
        self.last_line = {}
        self.reset_mode_timer()
        self.restart_countdown()
        self.streaks = streak.StreakStore(streak.default_path(core.SOUNDS_DIR))  # günlük alışkanlıklar
        self.tama = tama.Tama(self.cfg, lambda: core.save_config(self.cfg))
        if self.cfg.get("tama_on", True):
            self.tama.tick(False)  # kapalıyken geçen süreyi işle (sessizce)
        self.tama_panel = None
        self.game = None
        self.city_win = None
        self.voice = tts.Speaker(self.cfg)
        QApplication.instance().aboutToQuit.connect(self.voice.stop)
        self.notepad = None
        self.me = userdata.UserData(userdata.default_path(core.SOUNDS_DIR))  # Hakkımda: ad, doğum günü, uyku saatleri
        self.bday_today = self.me.is_birthday()

        self.asset = None
        self.asset_cache = {}
        self._asset_key = None

        self.t = 0
        self._last_pos = None
        self.state = "idle"
        self.state_frames = 60
        self.dir = 1
        self.blink_left = 0
        self.vy = 0
        self.press_global = None
        self.grab_offset = QPoint()
        self.moved = False
        self.dragging = False

        area = QApplication.primaryScreen().availableGeometry()
        pos = self.cfg.get("pos")  # son bırakılan yer
        if isinstance(pos, (list, tuple)) and len(pos) == 2 and area.x() - self.px // 2 <= pos[0] <= area.right() - self.px // 2 \
                and area.y() - self.px // 2 <= pos[1] <= area.bottom() - self.px // 2:
            self.move(int(pos[0]), int(pos[1]))
        else:
            self.move(area.x() + area.width() - self.px - 80, area.y() + area.height() - self.px)

        self.gt = gametalk.settings(self.cfg)  # oyun sohbeti
        self.x11 = gametalk.X11()
        self.gt_hold = gametalk.Hold(self.gt["hold_ms"], self.gt["cooldown_s"], self.gt["clicks"])
        self.gt_pick = gametalk.Picker()
        self.gt_detect = QTimer(self)
        self.gt_detect.timeout.connect(self.gt_detect_tick)
        self.gt_mouse = QTimer(self)
        self.gt_mouse.timeout.connect(self.gt_mouse_tick)

        self.build_menu()
        self.setup_tray()
        self.gt_reconfigure()

        self.tick = QTimer(self)
        self.tick.timeout.connect(self.step)
        self.tick.start(40)

        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.reminder_timer.start(10_000)

        self.water_timer = QTimer(self)
        self.water_timer.timeout.connect(lambda: self.alert(random.choice(core.WATER_LINES), "water"))
        self.eye_timer = QTimer(self)
        self.eye_timer.timeout.connect(lambda: self.alert(random.choice(core.EYE_LINES), "eye"))
        self.apply_timers()

        self.chatter_timer = QTimer(self)
        self.chatter_timer.setSingleShot(True)
        self.chatter_timer.timeout.connect(self.chatter)
        self.chatter_timer.start(random.randint(240, 600) * 1000)

        self.fact_timer = QTimer(self)  # rastgele bir vakitte fun fact
        self.fact_timer.setSingleShot(True)
        self.fact_timer.timeout.connect(self.fun_fact)
        self.schedule_fact()

        self.mode_timer = QTimer(self)  # çok oturma / çok ayakta durma kontrolü
        self.mode_timer.timeout.connect(self.check_long_mode)
        self.mode_timer.start(60_000)

        self.streak_timer = QTimer(self)  # akşam streak hatırlatması
        self.streak_timer.timeout.connect(self.streak_tick)
        self.streak_timer.start(60_000)
        self.prints = voiceprint.PrintStore(voiceprint.default_path(core.SOUNDS_DIR))  # öğretilen sesli komutlar
        self.train_state = None
        self.make_hear()  # sesli komut (mikrofon)
        self.interp = voicecmd.Interpreter(self.cfg)
        self.hear_timer = QTimer(self)
        self.hear_timer.timeout.connect(self.listen_poll)
        self.hear_timer.start(250)
        QApplication.instance().aboutToQuit.connect(lambda: self.hear.stop())
        if voicecmd.settings(self.cfg)["on"]:
            QTimer.singleShot(1500, self.start_listening)

        self.cd_timer = QTimer(self)
        self.cd_timer.timeout.connect(self.countdown_tick)
        self.cd_timer.start(1000)

        self.tama_timer = QTimer(self)
        self.tama_timer.timeout.connect(self.tama_tick)
        self.tama_timer.start(30_000)

        if self.cfg.get("sit"):
            self.set_state("sit", FOREVER)
        else:
            self.refresh_asset()
        self.birthday_timer = QTimer(self)
        self.birthday_timer.timeout.connect(self.birthday_tick)
        self.birthday_timer.start(60_000)
        QTimer.singleShot(7000, self.birthday_tick)  # açılışta selamlamadan sonra
        QTimer.singleShot(1200, self.greet)

    # --- yardımcılar
    def area(self):
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry()

    def floor_y(self):
        a = self.area()
        return a.y() + a.height() - self.px

    def rest_state(self):
        return ("sit", FOREVER) if self.cfg.get("sit") else ("idle", 40)

    def set_state(self, state, frames):
        prev = self.state
        self.state = state
        self.state_frames = frames
        if state == "sleep" and prev != "sleep":
            self.sound("sleep")
        elif prev == "sleep" and state != "sleep":
            self.sound("wake")
        self.refresh_asset()

    def say(self, text, ms=None, kind="say"):
        """kind: "say" = konuşma balonu, "alert" = bildirim (etiketli çerçeve)."""
        text = lines.strip_emoji(T(text))
        if ms is None:
            ms = min(15000, 3500 + len(text) * 55)
        self.bubble.say(text, self.anchor(), ms, kind)
        self.speak(text)

    def speak(self, text):
        """Sesli konuşma açıksa repliği okur (uyku saatlerinde ve uyurken susar)."""
        if not self.voice.enabled() or self.state == "sleep" or self.me.in_sleep_hours():
            return
        why = self.voice.speak(text)
        if why:  # motor çalışmıyorsa bir kez uyar, sonra sesli konuşmayı kapatır
            self.voice.v["on"] = False
            core.save_config(self.cfg)
            self.bubble.say(why, self.anchor(), 12000, "alert")

    # --- sesli komut (mikrofon): "Skippy ... aç"
    def make_hear(self):
        """Seçili tanıma motoruna göre dinleyiciyi kurar (eskisi durdurulur)."""
        old = getattr(self, "hear", None)
        if old is not None:
            old.stop()
        muted = lambda: self.voice.busy()
        if voicecmd.settings(self.cfg)["engine"] == "template":
            self.hear = voiceprint.TemplateListener(self.cfg, self.prints, muted=muted)
        else:
            self.hear = voicecmd.Listener(self.cfg, muted=muted)

    def start_listening(self):
        why = self.hear.start()
        if why:
            voicecmd.settings(self.cfg)["on"] = False
            core.save_config(self.cfg)
            self.say(why, 12000, "alert")
            return False
        return True

    def listen_poll(self):
        texts, err = self.hear.poll()
        for t in texts:
            self.handle_heard(t)
        for ev in (self.hear.pop_events() if hasattr(self.hear, "pop_events") else []):
            self.on_train_event(ev)
        if err:
            voicecmd.settings(self.cfg)["on"] = False
            core.save_config(self.cfg)
            self.say(err, 10000, "alert")

    def handle_heard(self, text):
        self.interp.name = self.cfg.get("name", "")
        v = voicecmd.settings(self.cfg)
        if v["engine"] == "template" and voicecmd.strip_wake(voicecmd.tokens(text), v["wake"], self.interp.name) is None:
            text = f"{v['wake']} {text}"  # öğretilen komut uyandırma kelimesi olmadan yazıldıysa ekle
        cmd = self.interp.parse(text)
        if cmd is not None:
            self.run_voice(cmd)

    def chat_command(self, text):
        """Sohbet kutusundan gelen komut (uygulama aç, not defteri, sayaç…). Komut değilse None döner ki normal sohbet sürsün.
        Sıradan cümleler yanlışlıkla komut sayılmasın diye kısa olmalı ve çoğunlukla 'aç' benzeri bir fiil içermeli."""
        toks = voicecmd.tokens(text)
        if not toks or len(toks) > 7:
            return None
        v = voicecmd.settings(self.cfg)
        self.interp.name = self.cfg.get("name", "")
        rest = voicecmd.strip_wake(toks, v["wake"], self.interp.name)
        rest = toks if rest is None else rest
        if not rest:
            return None
        folded = [voicecmd.fold(t) for t in rest]
        verb = any(t in voicecmd.OPEN_VERBS or t == "ac" or t in voicecmd.CLOSE_VERBS for t in folded)
        cmd = self.interp.command(rest)
        kind = cmd[0]
        if kind == "app":
            self.run_voice(cmd)
            return f"{cmd[1]} açılıyor."
        if kind == "noapp" and verb and len(rest) <= 4 and cmd[1]:
            return f"'{cmd[1]}' diye bir uygulama bulamadım. Ayarlar → Sesli komut → Uygulama takma adı ekle ile öğretebilirsin."
        if kind == "action" and (verb or cmd[1] in ("sit", "stand", "hush", "tama_panel")):
            if cmd[1] == "chat":
                return "Zaten buradayız."
            self.run_voice(cmd)
            return "Tamam."
        return None

    def run_voice(self, cmd):
        kind = cmd[0]
        if kind == "wake":
            self.say("Dinliyorum.", 2500)
        elif kind == "action":
            _, name, state = cmd
            acts = {
                "notes": self.open_notes, "reminders_show": self.show_reminders,
                "reminders_add": self.add_reminder_dialog, "tama_panel": self.open_tama_panel,
                "game": self.start_game, "city": self.start_city, "chat": self.open_chat,
                "hush": self.voice.stop,
                "water": lambda: self.toggle("water_on", bool(state)), "eye": lambda: self.toggle("eye_on", bool(state)),
                "countdown": lambda: self.toggle_countdown(bool(state)),
                "sit": lambda: self.say(self.do_command("sit")), "stand": lambda: self.say(self.do_command("stand")),
            }
            acts[name]()
        elif kind == "reminder":
            parsed = core.parse_reminder(cmd[1])
            if not parsed:
                self.say("Zamanı anlayamadım. '25 dakika sonra çayı demle diye hatırlat' gibi söyler misin?", 7000)
                return
            due, what = parsed
            self.store.add(due, what)
            self.say(f"Tamam. {core.fmt_due(due)} hatırlatacağım: {what}")
        elif kind == "food":
            self.tama_action(cmd[1])
        elif kind == "app":
            ok, err = voicecmd.launch(cmd[2])
            self.say(f"{cmd[1]} açılıyor." if ok else f"{cmd[1]} açılamadı: {err}", 4000)
        elif kind == "noapp":
            self.say(f"'{cmd[1]}' diye bir uygulama bulamadım. Menüden takma ad ekleyebilirsin." if cmd[1]
                     else "Neyi açayım?", 6000)
        else:
            self.say(f"Anlayamadım: {cmd[1][:60]}", 4000)

    def fill_listen_menu(self, menu):
        menu.clear()
        v = voicecmd.settings(self.cfg)
        make_action(menu, f"Beni dinle (uyandırma kelimesi: {v['wake']})", self.toggle_listening, v["on"])
        menu.addSeparator()
        make_action(menu, "Kendi sesim (indirme yok)", lambda c=None: self.set_listen_engine("template"), v["engine"] == "template")
        make_action(menu, "Vosk (çevrimdışı model)", lambda c=None: self.set_listen_engine("vosk"), v["engine"] == "vosk")
        make_action(menu, "Özel komut (whisper vb.)", lambda c=None: self.set_listen_engine("custom"), v["engine"] == "custom")
        if v["engine"] == "template":
            menu.addSeparator()
            make_action(menu, "➕ Komut öğret…", self.add_voice_command)
            lm = menu.addMenu(f"🗑 Öğretilen komutu sil ({len(self.prints.items)})")
            for lab in self.prints.labels():
                make_action(lm, lab.replace("&", "&&"), lambda c=None, x=lab: self.delete_voice_command(x))
            sm_ = menu.addMenu("🎚 Hassasiyet")
            for name, val in voiceprint.SENS.items():
                make_action(sm_, name, lambda c=None, n=val: self.set_sens(n), abs(float(v["sens"]) - val) < 0.01)
        elif v["engine"] == "vosk":
            make_action(menu, f"📁 Vosk model klasörünü seç ({os.path.basename(v['model']) or 'seçilmedi'})…", self.pick_vosk_model)
        else:
            make_action(menu, "⌨ Dinleme komutunu düzenle…", self.edit_listen_cmd)
        menu.addSeparator()
        make_action(menu, "🗣 Uyandırma kelimesini değiştir…", self.edit_wake)
        make_action(menu, "➕ Uygulama takma adı ekle…", self.add_app_alias)
        make_action(menu, "⌨ Komutu yazarak dene…", self.type_command)
        make_action(menu, "ℹ Neler diyebilirim?", lambda: QMessageBox.information(self, "Sesli komutlar", voicecmd.HELP))

    def toggle_listening(self, checked):
        v = voicecmd.settings(self.cfg)
        v["on"] = bool(checked)
        core.save_config(self.cfg)
        if checked:
            if self.start_listening():
                self.say("Dinliyorum. Mikrofon açık, bunu unutma.", 4000)
        else:
            self.hear.stop()
            self.say("Dinlemeyi bıraktım.", 2500)

    def set_listen_engine(self, key):
        v = voicecmd.settings(self.cfg)
        v["engine"] = key
        core.save_config(self.cfg)
        self.make_hear()
        why = voicecmd.problem(v)
        if why:
            self.say(why, 12000, "alert")
        elif v["on"]:
            self.start_listening()

    def set_sens(self, val):
        voicecmd.settings(self.cfg)["sens"] = val
        core.save_config(self.cfg)

    def add_voice_command(self):
        text, ok = QInputDialog.getText(
            self, "Komut öğret",
            "Hangi komutu öğreteyim? Normal bir komut gibi yaz:\n"
            "firefox aç  ·  steam aç  ·  not defterini aç  ·  sayacı aç  ·  hatırlatıcıları göster\n"
            "(Sonra bunu 3 kez, günlük konuşur gibi söyleyeceksin. İstersen başına 'Skippy' de söyle.)")
        label = text.strip()
        if not ok or not label:
            return
        v = voicecmd.settings(self.cfg)
        rest = voicecmd.strip_wake(voicecmd.tokens(label), v["wake"], self.cfg.get("name", ""))
        self.interp.name = self.cfg.get("name", "")
        cmd = self.interp.command(rest if rest is not None else voicecmd.tokens(label))
        if cmd[0] in ("unknown", "noapp"):
            self.say("Bu komutu ben bile anlamadım. Örnek: 'firefox aç' ya da 'not defterini aç'.", 7000)
            return
        if v["engine"] != "template":
            v["engine"] = "template"
            core.save_config(self.cfg)
            self.make_hear()
        self.train_state = {"label": label, "was_on": v["on"]}
        self.hear.train = {"label": label, "need": voiceprint.TRAIN_SAMPLES, "samples": []}
        why = self.hear.start(force=True)
        if why:
            self.train_state, self.hear.train = None, None
            self.say(why, 12000, "alert")
            return
        self.train_prompt(1)

    def train_prompt(self, n):
        self.say(f"Şimdi söyle: {self.train_state['label']} ({n}/{voiceprint.TRAIN_SAMPLES})", 9000)
        QTimer.singleShot(45_000, lambda s=self.train_state, k=n: self.train_timeout(s, k))

    def train_timeout(self, state, n):
        """45 saniyedir ses gelmediyse öğretmeyi bırakır."""
        cur = self.train_state
        if cur is state and cur is not None and self.hear.train is not None and len(self.hear.train["samples"]) == n - 1:
            self.hear.train, self.train_state = None, None
            if not voicecmd.settings(self.cfg)["on"]:
                self.hear.stop()
            self.say("Ses gelmedi, öğretmeyi bıraktım.", 4000)

    def on_train_event(self, ev):
        st = self.train_state
        if st is None:
            return
        if ev[0] == "sample":
            self.train_prompt(ev[1] + 1)
        elif ev[0] == "trained":
            _, label, samples, thr = ev
            self.train_state = None
            self.prints.add(label, samples, thr)
            if not st["was_on"]:
                self.hear.stop()
            self.say(f"Öğrendim: {label}. Dinlemeyi açıp dene.", 6000)

    def delete_voice_command(self, label):
        self.prints.remove(label)
        self.say(f"'{label}' komutunu sildim.", 3000)

    def pick_vosk_model(self):
        path = QFileDialog.getExistingDirectory(self, "Vosk model klasörü", os.path.expanduser("~"))
        if path:
            voicecmd.settings(self.cfg)["model"] = path
            core.save_config(self.cfg)

    def edit_listen_cmd(self):
        text, ok = QInputDialog.getText(self, "Dinleme komutu", "Her tanınan cümleyi satır satır yazdıran komut:",
                                        QLineEdit.EchoMode.Normal, voicecmd.settings(self.cfg)["listen_cmd"])
        if ok:
            voicecmd.settings(self.cfg)["listen_cmd"] = text.strip()
            core.save_config(self.cfg)

    def edit_wake(self):
        v = voicecmd.settings(self.cfg)
        text, ok = QInputDialog.getText(self, "Uyandırma kelimesi", "Komuttan önce söyleyeceğin kelime:",
                                        QLineEdit.EchoMode.Normal, v["wake"])
        if ok and text.strip():
            v["wake"] = text.strip()
            core.save_config(self.cfg)

    def add_app_alias(self):
        text, ok = QInputDialog.getText(
            self, "Uygulama takma adı",
            "söylediğin = açılacak uygulama\n(örn: fayerfoks = firefox   ·   oyun kütüphanesi = steam)")
        if not ok or "=" not in text:
            return
        spoken, target = (x.strip() for x in text.split("=", 1))
        if spoken and target:
            self.cfg.setdefault("voice_apps", {})[spoken] = target
            core.save_config(self.cfg)
            self.say(f"Tamam. '{spoken}' dersen {target} açarım.", 4000)

    def type_command(self):
        text, ok = QInputDialog.getText(self, "Komutu yazarak dene", "Söyleyeceğin komutu yaz (uyandırma kelimesi gerekmez):")
        if ok and text.strip():
            self.interp.name = self.cfg.get("name", "")
            self.run_voice(self.interp.command(voicecmd.tokens(text)))

    # --- sesli konuşma ayarları
    def fill_voice_menu(self, menu):
        menu.clear()
        v = self.voice.v
        make_action(menu, "Sesli konuş", self.toggle_voice, v["on"])
        menu.addSeparator()
        for key, name in tts.ENGINES.items():
            make_action(menu, name, lambda c=None, k=key: self.set_voice_engine(k), v["engine"] == key)
        menu.addSeparator()
        eng = v["engine"]
        if eng == "espeak":
            make_action(menu, f"⚙ Ses ve hız ayarı ({v['espeak_voice']}, {v['speed']})…", self.edit_espeak)
        elif eng == "piper":
            name = os.path.basename(v["piper_model"]) or "seçilmedi"
            make_action(menu, f"📁 Ses modelini seç ({name})…", self.pick_piper_model)
        else:
            make_action(menu, "⌨ Komutu düzenle…", self.edit_custom_cmd)
        make_action(menu, "▶ Sesi dene", self.test_voice)
        make_action(menu, "⏹ Sustur", self.voice.stop)

    def toggle_voice(self, checked):
        self.voice.v["on"] = bool(checked)
        core.save_config(self.cfg)
        if checked:
            why = tts.problem(self.voice.v)
            if why:
                self.voice.v["on"] = False
                core.save_config(self.cfg)
                self.say(why, 12000, "alert")
                return
            self.say("Sesli konuşma açık. Artık dinlemek zorundasın.", 4000)
        else:
            self.voice.stop()

    def set_voice_engine(self, key):
        self.voice.v["engine"] = key
        core.save_config(self.cfg)
        why = tts.problem(self.voice.v)
        if why:
            self.say(why, 12000, "alert")  # motor henüz hazır değil: nasıl hazırlanacağını söyler

    def edit_espeak(self):
        v = self.voice.v
        text, ok = QInputDialog.getText(self, "eSpeak sesi", "Ses kodu, hız, perde\n(örn: tr, 150, 50 · erkek için tr+m3, kadın için tr+f3)",
                                        QLineEdit.EchoMode.Normal, f"{v['espeak_voice']}, {v['speed']}, {v['pitch']}")
        if not ok:
            return
        parts = [x.strip() for x in text.split(",")]
        if parts and parts[0]:
            v["espeak_voice"] = parts[0]
        if len(parts) > 1:
            v["speed"] = tts.clamp(parts[1], 80, 400, v["speed"])
        if len(parts) > 2:
            v["pitch"] = tts.clamp(parts[2], 0, 99, v["pitch"])
        core.save_config(self.cfg)
        self.test_voice()

    def pick_piper_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Piper ses modeli (.onnx)", os.path.expanduser("~"), "Piper modeli (*.onnx)")
        if path:
            self.voice.v["piper_model"] = path
            core.save_config(self.cfg)
            self.test_voice()

    def edit_custom_cmd(self):
        text, ok = QInputDialog.getText(
            self, "Özel ses komutu",
            T("Repliği okuyacak komut. Replik {text} yerine konur.\n(Örnek: ") + tts.EXAMPLE_CMD + ")",
            QLineEdit.EchoMode.Normal, self.voice.v["custom_cmd"])
        if ok:
            self.voice.v["custom_cmd"] = text.strip()
            core.save_config(self.cfg)
            if text.strip():
                self.test_voice()

    def test_voice(self):
        line = "Merhaba, ben Mermi. Bu benim sesim. Beğenmediysen ayarlardan değiştirebilirsin."
        self.bubble.say(line, self.anchor(), 5000, "say")
        why = self.voice.speak(line, force=True)
        if why:
            self.say(why, 12000, "alert")

    def anchor(self):
        lift = self.pill.visual_height() + 6 if self.pill.isVisible() else 0  # sayaç etiketinin üstünde dursun
        return QPoint(self.x() + self.px // 2, self.y() + 14 - lift)

    def sound(self, event):
        """Olay için ses dosyası varsa çalar; çaldıysa True döner."""
        if not self.cfg.get("sound_on", True):
            return False
        path = core.find_sound(self.cfg.get("skin", ""), event)
        if not path:
            return False
        self.sounds.play(path)
        return True

    def greet(self):
        self.say(core.greeting(self.cfg["name"]), 6000)
        self.sound("greeting")

    def alert(self, text, event="reminder"):
        text = lines.strip_emoji(T(text))
        self.set_state("happy", 90)
        self.say(text, 15000, "alert")
        if self.cfg.get("sound_on", True) and not self.sound(event):
            QApplication.beep()

    # --- görünüm (resim / gif)
    def reset_assets(self):
        if self.asset is not None:
            self.asset.stop()
        self.asset = None
        self.asset_cache.clear()
        self._asset_key = None

    def refresh_asset(self):
        skin = self.cfg.get("skin", "")
        key = (self.state, self.dir if self.state == "walk" else 1, skin, self.px)
        if key == self._asset_key:
            return
        self._asset_key = key
        if self.asset is not None:
            self.asset.stop()
        self.asset = None
        if not skin:
            return
        found = core.find_asset(skin, self.state, self.dir)
        if not found:
            return
        path, akey = found
        ck = (str(path), self.px)
        asset = self.asset_cache.get(ck)
        if asset is None:
            asset = Asset(path, akey, self.px)
            self.asset_cache[ck] = asset
        if asset.ok:
            self.asset = asset
            asset.start()

    def set_skin(self, name):
        self.cfg["skin"] = name
        core.save_config(self.cfg)
        self.reset_assets()
        self.refresh_asset()
        self.update()
        self.say(f"Yeni görünümüm: {name} 😸" if name else "Yine ben oldum, mermi! 🔫", 3000)

    def set_size(self, px):
        self.px = px
        self.cfg["size"] = px
        core.save_config(self.cfg)
        self.setFixedSize(px, px)
        self.reset_assets()
        self.move(self.x(), min(self.y(), self.floor_y()))  # boyut büyürse ekran dışına taşmasın; yer çekimi yok
        self.refresh_asset()
        self.update()
        self.say("Boyum değişti! 😸", 2500)

    def toggle_mirror(self, checked):
        self.cfg["mirror"] = checked
        core.save_config(self.cfg)

    def toggle_sound(self, checked):
        self.cfg["sound_on"] = checked
        core.save_config(self.cfg)
        self.say("Sesler açık 🔊" if checked else "Sesler kapalı 🔇", 2500)

    def test_sound(self):
        if not self.cfg.get("sound_on", True):
            self.say("Sesler kapalı. Menüden açabilirsin 🔊", 4000)
        elif not self.sound("reminder"):
            self.say("Hatırlatma sesi bulamadım. Ses klasörüne reminder.wav koy 🔔", 7000)

    def open_folder(self, path):
        core.ensure_dirs()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.say(f"Klasör şurada: {path}", 12000)

    # --- komutlar
    def do_command(self, cmd):
        was_sit = self.cfg.get("sit")
        if cmd == "sit":
            self.cfg["sit"] = True
            core.save_config(self.cfg)
            self.set_state("sit", FOREVER)
            self.sound("sit")
        elif cmd == "stand":
            self.cfg["sit"] = False
            core.save_config(self.cfg)
            self.set_state("idle", 30)
            self.sound("stand")
        elif cmd == "sleep":
            self.cfg["sit"] = False
            core.save_config(self.cfg)
            self.set_state("sleep", FOREVER)
        elif cmd == "wake":
            self.set_state("happy", 40)
        if bool(self.cfg.get("sit")) != bool(was_sit):  # gerçek bir otur/kalk geçişi
            self.reset_mode_timer()
            self.restart_countdown()
        if cmd == "sit":
            return self.pick(lines.SIT_START)
        if cmd == "stand":
            return self.pick(lines.STAND_START)
        return core.COMMAND_REPLIES[cmd]

    def toggle_sit(self):
        self.say(self.do_command("stand" if self.state == "sit" else "sit"))

    def toggle_sleep(self):
        if self.state == "sleep":
            self.say(self.do_command("wake"), 3000)
        else:
            self.bubble.hide()
            self.do_command("sleep")

    # --- Tamagotchi (sanal bebek) modu
    def tama_on(self):
        return self.cfg.get("tama_on", True)

    def toggle_tama(self, checked):
        self.cfg["tama_on"] = checked
        if checked:
            self.tama.d["last_ts"] = tama.time.time()  # kapalıyken geçen süre sayılmasın
        core.save_config(self.cfg)
        self.update()
        self.say("Tamagotchi modu açık! Beni besle, temizle, oyun oyna 🥚" if checked
                 else "Tamagotchi modu kapalı, artık aç kalmam 😸", 4000)

    def tama_tick(self):
        if not self.tama_on():
            self.tama.d["last_ts"] = tama.time.time()
            return
        events = self.tama.tick(self.state == "sleep")
        if "rested" in events and self.state == "sleep":
            self.do_command("wake")
            self.say(random.choice(tama.ALERTS["rested"]), 5000)
        elif events and self.state != "sleep":
            ev = events[0]
            if ev in tama.ALERTS and ev != "rested":
                self.alert(random.choice(tama.ALERTS[ev]), "tama_" + ev)
        self.refresh_tama_panel()
        self.update()

    def do_tama(self, cmd):
        """Bir Tamagotchi komutunu uygular ve söylenecek cümleyi döndürür."""
        if cmd == "play":
            self.start_game()
            return "Hadi bir tur atalım! 🎯"
        if not self.tama_on():
            return "Tamagotchi modu kapalı. Menüden açabilirsin 🥚"
        if cmd == "status":
            return self.tama.summary(self.cfg["name"], self.state == "sleep")
        if cmd == "menu":
            return self.tama.menu_text()
        if self.state == "sleep":
            return "Zzz… uyuyorum 😴 (önce uyandır)"
        if cmd == "clean":
            msg, ok = self.tama.clean_up()
            if ok:
                self.sound("clean")
        elif cmd.startswith("food:"):
            msg, ok = self.tama.feed(cmd[5:])
            if ok:
                self.sound("eat")
        else:
            return "Bunu anlayamadım."
        if ok:
            self.set_state("happy", 50)
        self.update()
        return msg

    def fill_food_menu(self, menu):
        """Tüm yiyecek / içecekler: ad, fiyat ve etkileri. Jetonu yetmeyenler soluk (seçilemez) görünür."""
        menu.clear()
        coins = self.tama.d["coins"]
        for key in tama.FOODS:
            a = make_action(menu, tama.food_label(key), lambda k=key: self.tama_action("food:" + k))
            a.setEnabled(coins >= tama.price(key))
        menu.addSeparator()
        info = QAction(f"🪙  Cebimde {coins} jeton var", menu)
        info.setEnabled(False)
        menu.addAction(info)

    def tama_action(self, cmd):
        self.say(self.do_tama(cmd), 4000)
        self.refresh_tama_panel()

    def open_tama_panel(self):
        if self.tama_panel is None:
            self.tama_panel = tama.TamaPanel(self)
        a = self.area()
        x = max(a.x(), min(self.x() + self.px // 2 - 150, a.x() + a.width() - 320))
        y = self.y() - 280 if self.y() > a.y() + 300 else self.y() + self.px + 8
        self.tama_panel.move(x, y)
        self.tama_panel.glitch_show()

    def refresh_tama_panel(self):
        if self.tama_panel is not None and self.tama_panel.isVisible():
            self.tama_panel.refresh()

    def draw_tama_overlay(self, p):
        f = QFont("Sans")
        f.setPixelSize(max(12, int(self.px * 0.17)))
        p.setFont(f)
        icon = tama.MOOD_ICON.get(self.tama.mood(self.state == "sleep"), "")
        if icon:
            p.drawText(QPointF(4, self.px * 0.2), icon)

    # --- mini oyun (boomer shooter)
    def start_game(self):
        if self.game is not None and self.game.isVisible():
            self.game.raise_()
            self.game.activateWindow()
            return
        if self.tama_on():
            ok, msg = self.tama.can_play()
            if not ok:
                self.say(msg, 5000)
                return
        try:
            import shooter  # tembel içe aktarma: oyunda hata olsa bile pet çalışmaya devam eder
        except Exception as ex:
            self.say(f"Oyunu açamadım 😿 ({str(ex)[:60]})", 8000)
            return
        self.bubble.hide()
        self.game = shooter.GameWindow(self.cfg["name"], self.game_sound)
        self.game.finished.connect(self.on_game_over)
        a = self.area()
        self.game.move(a.x() + (a.width() - shooter.WIN_W) // 2, a.y() + (a.height() - shooter.WIN_H) // 2)
        self.game.show()
        self.game.raise_()
        self.game.activateWindow()
        self.game.setFocus()

    # --- mini oyun (Neon Şehir: jeton harcama / idle şehir kurucu)
    def start_city(self):
        try:
            import city  # tembel içe aktarma
        except Exception as ex:
            self.say(f"Şehri açamadım ({str(ex)[:60]})", 8000)
            return
        if self.city_win is None:
            self.city_win = city.CityWindow(self.cfg, self.tama.d, lambda: core.save_config(self.cfg),
                                            say=lambda t: self.say(t, 3500), on_change=self.refresh_tama_panel)
            a = self.area()
            self.city_win.move(a.x() + max(0, (a.width() - 620) // 2), a.y() + 30)
        self.city_win.glitch_show()

    def game_sound(self, event):
        if event in ("shoot", "kill", "hurt", "dead"):  # ses klasörüne game_shoot.wav vb. koyabilirsin
            self.sound("game_" + event)

    def on_game_over(self, kills, wave):
        if self.tama_on():
            msg = self.tama.play_result(kills, wave)
        else:
            msg = f"{kills} düşman devirdim! 😎"
        self.set_state("happy", 80)
        self.say(msg, 7000)
        self.refresh_tama_panel()

    # --- zamanlayıcılar
    def apply_timers(self):
        for timer, on, key in ((self.water_timer, "water_on", "water_every_min"),
                               (self.eye_timer, "eye_on", "eye_every_min")):
            timer.stop()
            if self.cfg.get(key) and self.cfg.get(on):
                timer.start(int(float(self.cfg[key]) * 60_000))

    def pick(self, pool):
        """Listeden bir replik seçer; mümkünse üst üste aynısını söylemez."""
        choices = [l for l in pool if l != self.last_line.get(id(pool))] or pool
        line = random.choice(choices)
        self.last_line[id(pool)] = line
        return line

    def quiet(self):
        """Pet şu an konuşmamalı mı? (uyuyor, sohbet ya da oyun açık, kullanıcının uyku saatleri)"""
        return (self.state == "sleep" or bool(self.chat and self.chat.isVisible())
                or bool(self.game and self.game.isVisible()) or self.me.in_sleep_hours())

    def chatter(self):
        if not self.quiet():
            if self.me.name and random.random() < 0.2:  # ara sıra adınla hitap eder
                text = self.pick(lines.NAMED).format(ad=self.me.name)
            else:
                text = self.pick(lines.SIT_WAIT if self.cfg.get("sit") else lines.STAND_MOVE)
            self.say(text)
        self.chatter_timer.start(random.randint(240, 600) * 1000)

    def schedule_fact(self):
        self.fact_timer.start(random.randint(15, 40) * 60_000)

    def fun_fact(self):
        if not self.quiet():
            self.say(self.pick(lines.FUN_FACTS), 12000)
        self.schedule_fact()

    # --- otur / kalk geri sayım sayacı
    def cd_seconds(self, sitting):
        key, default = ("cd_sit_s", countdown.DEFAULT_SIT_S) if sitting else ("cd_stand_s", countdown.DEFAULT_STAND_S)
        return int(self.cfg.get(key, default))

    def restart_countdown(self):
        """Mevcut mod için süreyi baştan başlatır (her otur/kalk geçişinde çağrılır)."""
        self.cd.start(self.cd_seconds(bool(self.cfg.get("sit"))))
        self.refresh_pill()

    def refresh_pill(self):
        if not self.cfg.get("cd_on", True):
            self.pill.glitch_hide()
            return
        if not self.isVisible():  # pet henüz görünmüyorsa etiket de gösterilmez
            return
        sitting = bool(self.cfg.get("sit"))
        left = self.cd.remaining()
        color = countdown.WARN_COLOR if left < 60 else (countdown.SIT_COLOR if sitting else countdown.STAND_COLOR)
        self.pill.set_text("DİNLENME" if sitting else "ÇALIŞMA", countdown.fmt_clock(left), color)
        self.pill.follow(self.x(), self.y(), self.px)
        self.pill.glitch_show()  # zaten açıksa bir şey yapmaz

    def countdown_tick(self):
        if not self.cfg.get("cd_on", True):
            self.pill.glitch_hide()
            return
        if self.cd.expired():
            self.countdown_expired()
        else:
            self.refresh_pill()

    def countdown_expired(self):
        """Süre doldu: çalışma (kalk) <-> dinlenme (otur) modunu kendisi değiştirir.
        Çalışma süresi tamamlandıysa süreye göre jeton ödülü verilir."""
        was_sitting = bool(self.cfg.get("sit"))
        text = T(self.pick(lines.TIMER_TO_STAND if was_sitting else lines.TIMER_TO_SIT))
        if not was_sitting and self.tama_on():
            earned = countdown.coins_for(self.cd.total)  # geçiş sayacı sıfırlamadan önce oku
            if earned:
                self.tama.add_coins(earned)
                text += " " + T(self.pick(lines.TIMER_REWARD).format(n=earned))
                self.refresh_tama_panel()
        self.do_command("stand" if was_sitting else "sit")  # geçiş sayacı da yeniden başlatır
        self.alert(text, "timer")

    def toggle_countdown(self, checked):
        self.cfg["cd_on"] = checked
        core.save_config(self.cfg)
        if checked:
            self.restart_countdown()
            self.say("Sayaç açık.", 2500)
        else:
            self.pill.glitch_hide()
            self.say("Sayaç kapalı.", 2500)

    def set_countdown(self, mode):
        sitting = mode == "sit"
        name = "Dinlenme" if sitting else "Çalışma"
        text, ok = QInputDialog.getText(
            self, T(f"{name} süresi"),
            T(f"{name} süresi ne kadar olsun?\nÖrn:  45   ·   45 dk   ·   1:30   ·   1.5 saat\n(en az 1 dakika, en fazla 12 saat)")
            + ("" if sitting else T(f"\nÇalışma süresi bitince her {countdown.COIN_EVERY_S // 60} dakika için 1 jeton kazanırsın.")),
            text=countdown.fmt_duration(self.cd_seconds(sitting)))
        if not ok:
            return
        secs = countdown.parse_duration(text)
        if secs is None:
            self.say("Süreyi anlayamadım. '45 dk', '1:30' ya da '1.5 saat' şeklinde yazar mısın?", 7000)
            return
        self.cfg["cd_sit_s" if sitting else "cd_stand_s"] = secs
        core.save_config(self.cfg)
        if sitting == bool(self.cfg.get("sit")):  # şu anki modun süresi değiştiyse hemen yeniden başlat
            self.restart_countdown()
        self.say(f"{name} süresi {countdown.fmt_duration(secs)} olarak ayarlandı.", 4000)

    def restart_countdown_now(self):
        self.restart_countdown()
        self.say("Sayaç baştan başladı.", 2500)

    def fill_countdown_menu(self, menu):
        menu.clear()
        make_action(menu, "Sayaç açık", self.toggle_countdown, self.cfg.get("cd_on", True))
        make_action(menu, f"Çalışma süresi: {countdown.fmt_duration(self.cd_seconds(False))}…",
                    lambda: self.set_countdown("stand"))
        make_action(menu, f"Dinlenme süresi: {countdown.fmt_duration(self.cd_seconds(True))}…",
                    lambda: self.set_countdown("sit"))
        menu.addSeparator()
        make_action(menu, "Sayacı baştan başlat", self.restart_countdown_now)

    # --- Hakkımda (kullanıcı bilgileri) ve doğum günü sürprizi
    def fill_profile_menu(self, menu):
        menu.clear()
        me = self.me
        make_action(menu, T("Adım: ") + (me.name.replace("&", "&&") or "—") + "…", self.set_user_name)
        make_action(menu, f"Doğum günüm: {me.birthday_label() or '—'}…", self.set_birthday)
        make_action(menu, f"Uyku saatlerim: {me.sleep_label() or '—'}…", self.set_sleep_hours)

    def set_user_name(self):
        text, ok = QInputDialog.getText(self, "Adım", "Sana nasıl hitap edeyim?\n(Boş bırakırsan kayıt silinir)",
                                        text=self.me.name)
        if not ok:
            return
        name = self.me.set_name(text)
        self.say(f"Kaydettim: {name}. Artık sana adınla hitap edebilirim." if name else "Adını sildim.", 4500)

    def set_birthday(self):
        text, ok = QInputDialog.getText(
            self, "Doğum günüm", "Doğum günün ne zaman?\nÖrn:  14.03   ·   14.03.1998\n(Yıl isteğe bağlı. Boş bırakırsan kayıt silinir)",
            text=self.me.birthday_input())
        if not ok:
            return
        result = self.me.set_birthday(text)
        self.bday_today = self.me.is_birthday()
        self.update()
        self.say({"ok": "Not aldım. Gerisi sürpriz.", "cleared": "Doğum günü kaydını sildim.",
                  "bad": "Tarihi anlayamadım. '14.03' ya da '14.03.1998' şeklinde yazar mısın?"}[result], 5000)

    def set_sleep_hours(self):
        text, ok = QInputDialog.getText(
            self, "Uyku saatlerim", "Uyku saatlerin? Bu aralıkta kendiliğinden konuşmam.\nÖrn:  00:00-08:00   ·   23.30-7\n"
            "(Boş bırakırsan kapanır. Kendi kurduğun hatırlatıcılar yine çalışır)",
            text=self.me.sleep_label().replace("–", "-"))
        if not ok:
            return
        result = self.me.set_sleep(text)
        self.say({"ok": f"Tamam, {self.me.sleep_label()} arasında sessiz kalacağım.", "cleared": "Sessiz saatleri kapattım.",
                  "bad": "Saatleri anlayamadım. '00:00-08:00' şeklinde yazar mısın?"}[result], 5000)

    def birthday_tick(self):
        """Doğum gününde gün boyu şapka takar; günün sürprizini (bir kez) uygun bir anda yapar."""
        self.bday_today = self.me.is_birthday()
        if not self.me.birthday_due() or self.quiet():  # uyuyorsa / uyku saatindeyse / oyundaysa sonra tekrar dener
            return
        age = self.me.age()
        text = T(self.pick(lines.BDAY_AGE if age else lines.BDAY).format(ad=self.me.name or "insan", yas=age))
        if self.tama_on():
            self.tama.add_coins(userdata.BIRTHDAY_GIFT)
            text += " " + T(self.pick(lines.BDAY_GIFT).format(n=userdata.BIRTHDAY_GIFT))
            self.refresh_tama_panel()
        self.me.mark_birthday_done()
        self.alert(text, "birthday")
        self.update()

    # --- Not defteri
    def open_notes(self):
        first = self.notepad is None
        if first:
            self.notepad = notes.NotesWindow(notes.default_path(core.SOUNDS_DIR))
        w = self.notepad
        if first:  # ilk açılışta pet'in yanına; sonra kullanıcının bıraktığı yerde açılır
            a = self.area()
            x = self.x() + self.px // 2 - w.width() // 2
            y = self.y() - w.height() - 8
            if y < a.y():
                y = self.y() + self.px + 8
            w.move(max(a.x(), min(x, a.x() + a.width() - w.width())),
                   max(a.y(), min(y, a.y() + a.height() - w.height())))
        w.glitch_show()
        w.editor.setFocus()

    # --- Streak (günlük alışkanlıklar)
    def fill_streak_menu(self, menu):
        menu.clear()
        make_action(menu, "➕ Yeni streak ekle…", self.add_streak)
        habits = self.streaks.habits()
        if habits:
            menu.addSeparator()
            for h in habits:
                n = self.streaks.current(h)
                icon = "✅" if self.streaks.is_done(h) else "⬜"
                label = f"{icon}  {h['name']}".replace("&", "&&") + (f"    🔥 {n}" if n else "")
                make_action(menu, label, lambda i=h["id"]: self.toggle_streak(i))
            menu.addSeparator()
            dm = menu.addMenu("🗑 Streak sil")
            for h in habits:
                make_action(dm, h["name"].replace("&", "&&"), lambda i=h["id"]: self.delete_streak(i))
        menu.addSeparator()
        make_action(menu, "Akşam hatırlatması", self.toggle_streak_nudge, self.streaks.data["nudge_on"])
        make_action(menu, f"Hatırlatma saati: {self.streaks.data['nudge_time']}…", self.set_streak_time)

    def add_streak(self):
        text, ok = QInputDialog.getText(
            self, "Yeni streak",
            "Her gün neyi yapmak istiyorsun?\nÖrn:  su iç   ·   kitap oku   ·   spor yap")
        if not ok:
            return
        h, err = self.streaks.add(text)
        self.say(err or self.pick(lines.STREAK_NEW).format(name=h["name"]), 5000)

    def toggle_streak(self, hid):
        h = self.streaks.get(hid)
        if h is None:
            return
        if self.streaks.toggle(hid):
            n = self.streaks.current(h)
            text = T(self.pick(lines.STREAK_FIRST if n == 1 else lines.STREAK_DONE).format(name=h["name"], n=n))
            if n in streak.MILESTONES:
                text += " " + T(lines.STREAK_MILESTONE.format(n=n))
            if not self.streaks.pending():
                text += " " + T(self.pick(lines.STREAK_ALL))
            if self.state != "sleep":
                self.set_state("happy", 40)
        else:
            text = self.pick(lines.STREAK_UNDO).format(name=h["name"])
        self.say(text, 7000)

    def delete_streak(self, hid):
        h = self.streaks.get(hid)
        if h is None:
            return
        yes = QMessageBox.StandardButton.Yes
        if QMessageBox.question(self, "Streak sil", f"'{h['name']}' ve tüm geçmişi silinsin mi?",
                                yes | QMessageBox.StandardButton.No) == yes:
            self.streaks.remove(hid)
            self.say(f"'{h['name']}' silindi.", 3500)

    def toggle_streak_nudge(self, checked):
        self.streaks.set_nudge_on(checked)
        self.say(f"Akşam hatırlatması açık, saat {self.streaks.data['nudge_time']}." if checked
                 else "Akşam hatırlatması kapalı.", 3500)

    def set_streak_time(self):
        text, ok = QInputDialog.getText(self, "Hatırlatma saati",
                                        "Yapılmayan streak'ler için günlük hatırlatma saati?\nÖrn:  20:00   ·   21.30   ·   22",
                                        text=self.streaks.data["nudge_time"])
        if not ok:
            return
        t = self.streaks.set_nudge_time(text)
        self.say(f"Hatırlatma saati {t}." if t else "Saati anlayamadım. '20:00' gibi yazar mısın?", 4000)

    def streak_tick(self):
        """Akşam hatırlatma saati geldiyse ve bugün yapılmayanlar varsa bir kez hatırlatır."""
        if not self.streaks.nudge_due() or self.quiet():  # uyuyorsa / sohbet ya da oyun açıksa bir dakika sonra yine dener
            return
        names = [h["name"] for h in self.streaks.pending()]
        shown = ", ".join(names[:3]) + (T(f" ve {len(names) - 3} tane daha") if len(names) > 3 else "")
        self.streaks.mark_nudged()
        self.alert(self.pick(lines.STREAK_NUDGE).format(list=shown), "streak")

    def reset_mode_timer(self):
        self.mode_since = time.time()
        self.next_long = self.mode_since + 3600

    def check_long_mode(self):
        """Aynı modda (oturma ya da ayakta) 1 saatten uzun kalındıysa söylenir; sonra her saat tekrarlar."""
        now = time.time()
        if now < self.next_long:
            return
        self.next_long = now + 3600
        if not self.quiet():
            self.say(self.pick(lines.SIT_LONG if self.cfg.get("sit") else lines.STAND_LONG), 10000)

    def check_reminders(self):
        for text, late in self.store.pop_due():
            prefix = T("Geç kaldım ama: ") if late > 120 else ""
            self.alert(f"⏰ {prefix}{text}")

    # --- davranış
    def pick_state(self):
        if self.cfg.get("sit"):
            self.set_state("sit", FOREVER)
            return
        # yürüyen görünümler yerinde yürümesin: 'süzülme' yalnızca varsayılan karakterde seçilir
        state = random.choices(["idle", "walk", "sleep"], [4, 5 if not self.cfg.get("skin") else 0, 1])[0]
        if state == "walk":
            self.set_state("walk", random.randint(60, 200))
        elif state == "sleep":
            self.set_state("sleep", random.randint(250, 500))
        else:
            self.set_state("idle", random.randint(50, 150))

    def step(self):
        self.t += 1
        if self.asset is not None:
            self.asset.tick()
        pos = (self.x(), self.y())
        if pos != self._last_pos:  # pencereler yalnızca pet gerçekten yer değiştirince taşınır
            self._last_pos = pos
            if self.bubble.isVisible():
                self.bubble.reposition(self.anchor())
            if self.pill.isVisible():
                self.pill.follow(self.x(), self.y(), self.px)
        if self.dragging:
            self.update()
            return

        self.state_frames -= 1
        if self.state_frames <= 0:
            self.pick_state()
        if self.blink_left > 0:
            self.blink_left -= 1
        elif random.random() < 0.012:
            self.blink_left = 5
        self.refresh_asset()
        # sakin durumlarda (bekle / otur / uyu, GIF yok) saniyede ~12 kare yeter: CPU ve kompozitör yükü azalır
        if self.asset is not None or self.state in ("walk", "happy") or self.t % 2 == 0:
            self.update()

    # --- çizim
    def paintEvent(self, _):
        p = QPainter(self)
        flip = False  # artık sağa sola gezinmiyor
        if flip:
            p.translate(self.px, 0)
            p.scale(-1, 1)
        top = self.px * 0.15  # görselin tepesi (doğum günü şapkası için)
        s = self.px / 120
        holo = self.cfg.get("holo", True)
        if self.asset is not None:
            pm = self.asset.frame()
            if pm is not None and not pm.isNull():
                # özel görünümler de süzülür; hologram altına gelir (kapatılabilir)
                room = 24 * s if holo else 10 * s
                if pm.width() > self.px or pm.height() > self.px - room:
                    pm = pm.scaled(self.px, int(self.px - room), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                b = bullet.float_offset(self.t, self.state) * s * 0.8
                if holo:
                    p.save()
                    p.scale(s, s)
                    bullet.hologram(p, self.t, b / s, self.state == "sleep")
                    p.restore()
                base = self.px - (14 * s if holo else 4 * s)
                y0 = int(base - pm.height() + b)
                p.drawPixmap((self.px - pm.width()) // 2, y0, pm)
                top = max(0, y0)
        else:
            p.scale(s, s)
            if holo:
                draw_cat(p, self.t, self.state, self.blink_left > 0)
            else:
                bullet.draw_bullet(p, self.t, self.state, self.blink_left > 0, holo=False)
            top = 18 * s
        p.resetTransform()
        if self.state == "sleep":
            s = self.px / 120
            p.scale(s, s)
            draw_zzz(p, self.t)
        if self.tama_on():
            self.draw_tama_overlay(p)
        if self.bday_today:
            self.draw_party_hat(p, top)
        p.end()

    def draw_party_hat(self, p, top):
        """Doğum gününde petin tepesine konan küçük parti şapkası."""
        w, h, r = self.px * 0.26, self.px * 0.28, self.px * 0.045
        cx = self.px / 2
        base = max(h + r + 1, top + h * 0.35)  # kafaya hafif otursun ama pencere dışına taşmasın
        p.setPen(QPen(QColor("#5B3A1E"), max(1.0, self.px / 60)))
        p.setBrush(QColor("#FF6FD8"))
        p.drawPolygon(QPolygonF([QPointF(cx - w / 2, base), QPointF(cx + w / 2, base), QPointF(cx, base - h)]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#7DF0FF"))
        for fx, fy in ((-0.17, 0.2), (0.12, 0.38), (-0.05, 0.62)):
            p.drawEllipse(QPointF(cx + w * fx, base - h * fy), r * 0.55, r * 0.55)
        p.setBrush(QColor("#FFD84A"))
        p.drawEllipse(QPointF(cx, base - h), r, r)

    # --- fare
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.press_global = e.globalPosition().toPoint()
            self.grab_offset = self.press_global - self.frameGeometry().topLeft()
            self.moved = False

    def mouseMoveEvent(self, e):
        if self.press_global is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        g = e.globalPosition().toPoint()
        if not self.moved and (g - self.press_global).manhattanLength() > 6:
            self.moved = True
            self.dragging = True
            self.set_state("drag", FOREVER)
        if self.moved:
            self.move(g - self.grab_offset)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.press_global is None:
            return
        was_drag = self.moved
        self.press_global = None
        self.dragging = False
        if was_drag:
            self.cfg["pos"] = [self.x(), self.y()]  # bırakılan yerde kalır (düşmez) ve hatırlanır
            core.save_config(self.cfg)
            self.set_state(*self.rest_state())
        else:
            self.on_click()

    def on_click(self):
        if self.state == "sleep":
            self.set_state("happy", 40)
        self.say(random.choice(core.CLICK_LINES), 2500)
        self.sound("click")
        self.open_chat()

    def contextMenuEvent(self, _):
        self.menu.exec(QCursor.pos())

    # --- sohbet penceresi
    def open_chat(self):
        if self.chat is None:
            self.chat = ChatWindow(self)
        if self.chat.isVisible():
            self.chat.glitch_hide()
            return
        a = self.area()
        x = self.x() + self.px // 2 - self.chat.width() // 2
        y = self.y() - self.chat.height() - 8
        if y < a.y():
            y = self.y() + self.px + 8
        x = max(a.x(), min(x, a.x() + a.width() - self.chat.width()))
        self.chat.move(x, y)
        self.chat.glitch_show()
        self.chat.input.setFocus()

    # --- menü & tepsi
    def build_menu(self):
        m = QMenu()
        self.menu = m

        make_action(m, "💬 Sohbet", self.open_chat)

        rm = m.addMenu("⏰ Hatırlatıcılar")
        make_action(rm, "➕ Hatırlatıcı ekle…", self.add_reminder_dialog)
        make_action(rm, "📋 Hatırlatıcılarım", self.show_reminders)
        sk = rm.addMenu("🔥 Streak (günlük)")
        sk.aboutToShow.connect(lambda: self.fill_streak_menu(sk))
        make_action(rm, "📝 Not defteri", self.open_notes)
        rm.addSeparator()
        make_action(rm, "💧 Su hatırlatması", lambda c: self.toggle("water_on", c), self.cfg["water_on"])
        make_action(rm, "👀 Göz molası hatırlatması", lambda c: self.toggle("eye_on", c), self.cfg["eye_on"])
        m.addSeparator()

        make_action(m, "🪑 Otur / kalk", self.toggle_sit)
        cm = m.addMenu("⏱ Sayaç")
        cm.aboutToShow.connect(lambda: self.fill_countdown_menu(cm))

        tm = m.addMenu("🥚 Tamagotchi")
        make_action(tm, "Tamagotchi modu", self.toggle_tama, self.tama_on())
        make_action(tm, "📊 Durum paneli", self.open_tama_panel)
        tm.addSeparator()
        fm = tm.addMenu("🍽 Yiyecekler")
        fm.aboutToShow.connect(lambda: self.fill_food_menu(fm))
        make_action(tm, "🧼 Temizle", lambda: self.tama_action("clean"))

        gm = m.addMenu("🎮 Mini oyunlar")
        make_action(gm, "🎯 Happy Slaughtering (Boomer Shooter)", self.start_game)
        make_action(gm, "🌆 Neon Şehir (Idle · jeton harcama)", self.start_city)
        m.addSeparator()

        sm = m.addMenu("⚙️ Ayarlar")
        skin_menu = sm.addMenu("🎨 Görünüm")
        skin_menu.aboutToShow.connect(lambda: self.fill_skin_menu(skin_menu))
        size_menu = sm.addMenu("📏 Boyut")
        size_menu.aboutToShow.connect(lambda: self.fill_size_menu(size_menu))
        listen_menu = sm.addMenu("🎤 Sesli komut")
        listen_menu.aboutToShow.connect(lambda: self.fill_listen_menu(listen_menu))
        voice_menu = sm.addMenu("🗣 Sesli konuşma")
        voice_menu.aboutToShow.connect(lambda: self.fill_voice_menu(voice_menu))
        sound_menu = sm.addMenu("🔊 Sesler")
        make_action(sm, "✨ Hologram", self.toggle_holo, self.cfg.get("holo", True))
        make_action(sound_menu, "Sesler açık", self.toggle_sound, self.cfg.get("sound_on", True))
        make_action(sound_menu, "🔔 Hatırlatma sesini dene", self.test_sound)
        make_action(sound_menu, "📁 Ses klasörünü aç", lambda: self.open_folder(core.SOUNDS_DIR))
        gt_menu = sm.addMenu("🎮 Oyun sohbeti (kışkırtma)")
        gt_menu.aboutToShow.connect(lambda: self.fill_gametalk_menu(gt_menu))
        lang_menu = sm.addMenu("🌐 Language / Dil")
        make_action(lang_menu, "Türkçe", lambda c=None: self.set_language("tr"), i18n.lang() == "tr")
        make_action(lang_menu, "English", lambda c=None: self.set_language("en"), i18n.lang() == "en")
        sm.addSeparator()
        me_menu = sm.addMenu("👤 Hakkımda")
        me_menu.aboutToShow.connect(lambda: self.fill_profile_menu(me_menu))
        make_action(sm, "✏️ Pet'in adını değiştir…", self.rename)

        m.addSeparator()
        make_action(m, "❌ Çıkış", QApplication.quit)

    # --- oyun sohbeti
    def gt_reconfigure(self):
        """Zamanlayıcıları ayara göre aç/kapat: liste boşsa ya da kapalıysa hiçbir şey çalışmaz (CPU harcamaz)."""
        self.gt_hold.hold_ms, self.gt_hold.cooldown_s, self.gt_hold.clicks = self.gt["hold_ms"], self.gt["cooldown_s"], self.gt["clicks"]
        self.gt_mouse.stop()
        self.gt_hold.since = None
        if self.gt["enabled"] and self.gt["games"] and self.x11.ok:
            if not self.gt_detect.isActive():
                self.gt_detect.start(1500)
            self.gt_detect_tick()
        else:
            self.gt_detect.stop()

    def gt_detect_tick(self):
        active = gametalk.matches(self.x11.info(), self.gt["games"]) is not None
        if active and not self.gt_mouse.isActive():
            self.gt_mouse.start(25)  # hızlı tıkları kaçırmamak için sık yokla (XQueryPointer çok ucuz)
        elif not active and self.gt_mouse.isActive():
            self.gt_mouse.stop()
            self.gt_hold.since = None

    def gt_mouse_tick(self):
        if self.gt_hold.update(self.x11.button1(), time.monotonic()):
            if not self.me.in_sleep_hours() and not (self.game and self.game.isVisible()):
                if self.state == "sleep":  # uyuyorsa uyan, yoksa ne balon ne ses çıkar
                    self.set_state("happy", 40)
                self.say(self.gt_pick.pick(lines.GAME_TAUNTS))  # süre metin uzunluğuna göre (okunabilsin)

    def fill_gametalk_menu(self, menu):
        menu.clear()
        make_action(menu, "Oyun sohbeti açık", self.gt_toggle, self.gt["enabled"])
        menu.addSeparator()
        make_action(menu, "➕ Şu an açık olan oyunu ekle (5 sn sonra)…", self.gt_add_game)
        rm = menu.addMenu("🗑 Oyunu listeden çıkar")
        if not self.gt["games"]:
            rm.addAction("(liste boş — sadece listedeki oyunlarda konuşurum)").setEnabled(False)
        for g in self.gt["games"]:
            make_action(rm, g.replace("&", "&&"), lambda c=None, x=g: self.gt_remove_game(x))
        menu.addSeparator()
        make_action(menu, f"⏱ Basılı tutma süresi: {self.gt['hold_ms']} ms…", self.gt_set_hold)
        make_action(menu, f"🔁 Laf atma aralığı: {self.gt['cooldown_s']} sn…", self.gt_set_cooldown)
        make_action(menu, f"🖱 Hızlı tıklama: {self.gt['clicks']} tık…", self.gt_set_clicks)
        make_action(menu, "ℹ Nasıl çalışır?", lambda: QMessageBox.information(self, "Oyun sohbeti", T(
            "Listedeki bir oyun açıkken (aktif pencere) sol fare tuşunu basılı tuttuğunda düşmanlara laf atarım.\n\n"
            "• Önce 'Şu an açık olan oyunu ekle' ile oyunu öğret: tıkla, 5 saniye içinde oyuna geç.\n"
            "• Listede olmayan oyunlarda (örn. Minecraft) hiç konuşmam.\n"
            "• Tek tek kısa tıklamalar sayılmaz; ama basılı tutarsan ya da fareye abanıp hızlı hızlı tıklarsan konuşurum (ikisi de ayarlanabilir), uzun süre sürekli ateşte daha sık.\n"
            "• Küfürler sadece oyundaki düşmanlara, kurgusal ve sansürlüdür.\n"
            "• X11 / XWayland gerekir (Steam / Proton oyunları normalde böyledir).")))

    def gt_save(self):
        core.save_config(self.cfg)
        self.gt_reconfigure()

    def gt_toggle(self, checked):
        self.gt["enabled"] = bool(checked)
        self.gt_save()

    def gt_add_game(self):
        self.say("5 saniye içinde oyuna geç, hangi pencere açıksa onu öğreneceğim.", 4500)
        QTimer.singleShot(5000, self.gt_capture_game)

    def gt_capture_game(self):
        name = gametalk.label(self.x11.info())
        if not name:
            self.say("Aktif pencereyi göremedim. Bu özellik X11 / XWayland ister; saf Wayland pencerelerini göremem.", 5000)
        elif name in self.gt["games"]:
            self.say(f"'{name}' zaten listede.", 3000)
        else:
            self.gt["games"].append(name)
            self.gt_save()
            self.say(f"'{name}' listeye eklendi. Bu oyunda fareyi basılı tuttukça laf atarım.", 5000)

    def gt_remove_game(self, name):
        if name in self.gt["games"]:
            self.gt["games"].remove(name)
            self.gt_save()
            self.say(f"'{name}' listeden çıkarıldı.", 3000)

    def gt_set_hold(self):
        v, ok = QInputDialog.getInt(self, "Basılı tutma süresi",
                                    "Fareyi kaç milisaniye basılı tutunca laf atayım? (kısa tıklamalar sayılmaz)",
                                    self.gt["hold_ms"], 150, 3000, 50)
        if ok:
            self.gt["hold_ms"] = v
            self.gt_save()

    def gt_set_clicks(self):
        v, ok = QInputDialog.getInt(self, "Hızlı tıklama",
                                    "Kaç hızlı tıkta (1,2 sn içinde) laf atayım? (0 = kapalı; tek basışta çalışan silahlara abanınca)",
                                    self.gt["clicks"], 0, 30, 1)
        if ok:
            self.gt["clicks"] = v
            self.gt_save()

    def gt_set_cooldown(self):
        v, ok = QInputDialog.getInt(self, "Laf atma aralığı", "İki laf arasında en az kaç saniye geçsin?",
                                    self.gt["cooldown_s"], 2, 120, 1)
        if ok:
            self.gt["cooldown_s"] = v
            self.gt_save()

    def toggle_holo(self, checked=None):
        self.cfg["holo"] = not self.cfg.get("holo", True)
        core.save_config(self.cfg)
        self.update()

    def set_language(self, code):
        """Dil değişince uygulama kendini yeniden başlatır (menüler / çeviri tablosu açılışta yüklenir)."""
        if code == i18n.lang():
            return
        i18n.set_lang(code)
        os.environ.pop("SKIPPY_LANG", None)
        v = self.cfg.get("voice")
        if isinstance(v, dict) and v.get("espeak_voice") in ("tr", "en"):
            v["espeak_voice"] = code
        core.save_config(self.cfg)
        self.say("Dil değişiyor, yeniden başlıyorum…" if code == "tr" else "Switching language, restarting…", 2500)
        QTimer.singleShot(1200, self.restart_app)

    def restart_app(self):
        try:
            self.hear.stop()
            self.voice.stop()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def fill_skin_menu(self, menu):
        menu.clear()
        cur = self.cfg.get("skin", "")
        make_action(menu, "🔫 Varsayılan mermi", lambda _c: self.set_skin(""), cur == "")
        skins = core.list_skins()
        for name in skins:
            make_action(menu, name, lambda _c, n=name: self.set_skin(n), cur == name)
        if not skins:
            a = QAction("(henüz görünüm yok — klasöre ekle)", menu)
            a.setEnabled(False)
            menu.addAction(a)
        menu.addSeparator()
        make_action(menu, "↔ Sola yürürken resmi çevir", self.toggle_mirror, self.cfg.get("mirror", True))
        make_action(menu, "📁 Görünüm klasörünü aç", lambda: self.open_folder(core.SKINS_DIR))

    def fill_size_menu(self, menu):
        menu.clear()
        for label, px in (("Küçük", 90), ("Orta", 120), ("Büyük", 180), ("Çok büyük", 260)):
            make_action(menu, f"{label} ({px})", lambda _c, v=px: self.set_size(v), self.px == px)

    def setup_tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_icon(), self)
            self.tray.setToolTip(self.cfg["name"])
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(
                lambda r: self.open_chat() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()

    def toggle(self, key, checked):
        self.cfg[key] = checked
        core.save_config(self.cfg)
        self.apply_timers()
        self.say("Tamam, açtım! 👍" if checked else "Tamam, kapattım.", 2500)

    def add_reminder_dialog(self):
        text, ok = QInputDialog.getText(
            self, "Hatırlatıcı ekle",
            "Ne zaman, ne için?\nÖrn:  25 dakika sonra çayı demle\n        yarın 09:30 toplantı")
        if not ok or not text.strip():
            return
        parsed = core.parse_reminder(text)
        if not parsed:
            self.say("Zamanı anlayamadım 😿 '10 dakika sonra …' ya da '14:30 …' şeklinde yazar mısın?", 7000)
            return
        due, what = parsed
        self.store.add(due, what)
        self.say(f"Tamam! {core.fmt_due(due)} hatırlatacağım: {what}")

    def show_reminders(self):
        items = self.store.upcoming()
        body = "\n".join(f"• {core.fmt_due(r['due'])} — {r['text']}" for r in items) or "Bekleyen hatırlatıcı yok."
        QMessageBox.information(self, "Hatırlatıcılarım", body)

    def rename(self):
        name, ok = QInputDialog.getText(self, "Adını değiştir", "Yeni adım ne olsun?", text=self.cfg["name"])
        if ok and name.strip():
            self.cfg["name"] = name.strip()
            core.save_config(self.cfg)
            if self.chat:
                self.chat.setWindowTitle(self.cfg["name"])
            if self.tray:
                self.tray.setToolTip(self.cfg["name"])
            self.say(f"Yeni adım {self.cfg['name']}! Çok beğendim 😸")


def main():
    if "--install-autostart" in sys.argv:
        print("Yazıldı:", core.install_autostart(os.path.abspath(__file__)))
        return
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Skippy")
    app.setDesktopFileName("skippy")
    pet = Pet()
    if "--preview-birthday" in sys.argv:  # sürprizi denemek için: kaydetmez, yalnızca bu çalıştırmada
        pet.me.preview = True
        pet.bday_today = True
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
