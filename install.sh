#!/usr/bin/env bash
# Skippy kullanıcı seviyesinde kurulum (root gerekmez). / User-level install (no root needed).
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/.local/share/skippy"
[ -f "$SRC/pet.py" ] || { echo "pet.py bulunamadı / not found"; exit 1; }
[ -f "$SRC/pet_core.py" ] || { echo "pet_core.py $SRC içinde olmalı / must be in $SRC"; exit 1; }
python3 -c "import PyQt6" 2>/dev/null || echo "UYARI/WARNING: PyQt6 yok / missing → sudo pacman -S python-pyqt6"

mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
cp "$SRC"/*.py "$DEST"/
for d in skins sounds; do [ -d "$SRC/$d" ] && cp -r "$SRC/$d" "$DEST"/ || true; done
cp "$SRC/packaging/skippy.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/skippy.svg"
cat > "$HOME/.local/bin/skippy" <<EOS
#!/bin/sh
exec python3 "$DEST/pet.py" "\$@"
EOS
chmod +x "$HOME/.local/bin/skippy"
sed "s|^Exec=skippy|Exec=$HOME/.local/bin/skippy|" "$SRC/packaging/skippy.desktop" > "$HOME/.local/share/applications/skippy.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Kuruldu / Installed. Uygulama menüsünden 'Skippy' ya da terminalde: skippy   (English: skippy --lang en)"
echo "Opsiyonel / Optional: sudo pacman -S qt6-multimedia espeak-ng python-numpy"
