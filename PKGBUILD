# Maintainer: you
# Kaynak klasörü (pet.py, pet_core.py, ... ve packaging/) bu dosyanın iki üst dizinindedir: makepkg'i packaging/ içinde çalıştır.
pkgname=skippy
pkgver=1.0
pkgrel=1
pkgdesc="Sarcastic desktop pet bullet (reminders, mini games, voice commands)"
arch=('any')
license=('custom')
depends=('python' 'python-pyqt6')
optdepends=('qt6-multimedia: sound effects' 'espeak-ng: spoken lines' 'python-numpy: faster voice recognition'
            'alsa-utils: microphone for voice commands')
options=(!strip)

package() {
  local src="$startdir/.."
  install -d "$pkgdir/usr/share/skippy" "$pkgdir/usr/bin"
  install -m644 "$src"/*.py "$pkgdir/usr/share/skippy/"
  for d in skins sounds; do [ -d "$src/$d" ] && cp -r "$src/$d" "$pkgdir/usr/share/skippy/"; done
  printf '#!/bin/sh\nexec python3 /usr/share/skippy/pet.py "$@"\n' > "$pkgdir/usr/bin/skippy"
  chmod 755 "$pkgdir/usr/bin/skippy"
  install -Dm644 "$startdir/skippy.desktop" "$pkgdir/usr/share/applications/skippy.desktop"
  install -Dm644 "$startdir/skippy.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/skippy.svg"
}
