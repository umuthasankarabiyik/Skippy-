"""Not defteri: ufak notlar için basit, otomatik kaydedilen düz metin penceresi.

Notlar `notes.txt` dosyasında tutulur (ses klasörünün bulunduğu klasörde). Yazdıkça kısa bir gecikmeyle kaydedilir;
pencere kapanınca ya da pet kapanınca da kaydedilir.
"""
import datetime as dt
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

import hud

SAVE_DELAY_MS = 700


# ------------------------------------------------------------ Qt'siz yardımcılar
def default_path(base_dir):
    """notes.txt: pet'in veri klasörünün yanına; klasör yoksa/yazılamazsa ev dizinine düşer."""
    try:
        d = Path(base_dir).parent
        d.mkdir(parents=True, exist_ok=True)
        return d / "notes.txt"
    except Exception:
        return Path.home() / ".pet-notes.txt"


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def write_text(path, text):
    """Önce geçici dosyaya yazıp yerine koyar; yazma yarıda kesilse bile eski not bozulmaz."""
    try:
        p = Path(path)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------- pencere
class NotesWindow(hud.GlitchWindow, QWidget):
    def __init__(self, path):
        super().__init__(None, Qt.WindowType.Tool)
        self.path = Path(path)
        self.dirty = False
        self.setWindowTitle("Not Defteri")
        self.resize(420, 480)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)  # yapıştırılan metin düz metin olsun
        self.editor.setPlaceholderText("Küçük notlar, yapılacaklar, geçici bilgiler…\nYazdıkların otomatik kaydedilir.")
        self.editor.setPlainText(read_text(self.path))
        self.status = QLabel()
        date_btn = QPushButton("📅 Tarih ekle")
        date_btn.clicked.connect(self.insert_date)

        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(date_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.editor)
        lay.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.save_now)
        self.editor.textChanged.connect(self.on_change)  # yüklemeden sonra bağlanır: açılışta "değişti" sayılmaz
        QApplication.instance().aboutToQuit.connect(self.save_now)
        self.show_status(True)

    def show_status(self, ok):
        if ok:
            n = len(self.editor.toPlainText())
            self.status.setStyleSheet("")
            self.status.setText(f"Kaydedildi · {n} karakter")
        else:
            self.status.setStyleSheet("color:#C0392B; font-weight:bold;")
            self.status.setText("Kaydedilemedi! Klasöre yazma izni var mı?")

    def on_change(self):
        self.dirty = True
        self.status.setStyleSheet("")
        self.status.setText("Yazıyor…")
        self.timer.start(SAVE_DELAY_MS)

    def save_now(self):
        if not self.dirty:
            return True
        self.timer.stop()
        ok = write_text(self.path, self.editor.toPlainText())
        self.dirty = not ok  # yazılamadıysa bir sonraki değişiklikte / kapanışta tekrar dener
        self.show_status(ok)
        return ok

    def insert_date(self):
        self.editor.insertPlainText(dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
        self.editor.setFocus()

    def closeEvent(self, e):
        self.save_now()
        hud.GlitchWindow.closeEvent(self, e)  # glitch ile kapanır
