# Skippy – desktop pet / Masaüstü arkadaşı

**Kur / Install** (Manjaro / any Linux):

    sudo pacman -S python-pyqt6                       # gerekli / required
    sudo pacman -S qt6-multimedia espeak-ng python-numpy alsa-utils   # isteğe bağlı / optional
    cd packaging && ./install.sh

Sonra uygulama menüsünden **Skippy** ya da terminalde `skippy`. Kaldırmak için `./uninstall.sh`.
Pacman paketi için: `cd packaging && makepkg -si`.

**Dil / Language:** Ayarlar → 🌐 Language / Dil (uygulama yeniden başlar) ya da `skippy --lang en`.
İlk açılışta sistem diline göre seçilir.

Notlar: pencereler görev çubuğunda görünmez, sistem bildirimi gönderilmez, internet / API kullanılmaz (sohbet yereldir).
