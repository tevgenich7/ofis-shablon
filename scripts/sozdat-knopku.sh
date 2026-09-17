#!/bin/bash
# Создаёт настоящую иконку «Офис» на рабочем столе (macOS).
# Двойной клик по ней открывает офис в браузере, без терминала и без команд.
# Запускается один раз при установке.

set -e
KOREN="$(cd "$(dirname "$0")/.." && pwd)"
STOL="$HOME/Desktop"
APP="$STOL/Офис.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Офис</string>
  <key>CFBundleDisplayName</key><string>Офис</string>
  <key>CFBundleIdentifier</key><string>local.office.panel</string>
  <key>CFBundleExecutable</key><string>zapusk</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>ikonka</string>
  <key>LSUIElement</key><true/>
  <key>CFBundleShortVersionString</key><string>1.0</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/zapusk" <<LAUNCH
#!/bin/bash
# Если офис уже открыт - просто показываем вкладку, второй раз не поднимаем.
if curl -s -o /dev/null --max-time 1 http://localhost:4477 2>/dev/null; then
  open http://localhost:4477
  exit 0
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:\$HOME/.local/bin:\$PATH"
cd "$KOREN"
exec node panel/server.js >> "$KOREN/panel/zhurnal.log" 2>&1
LAUNCH

chmod +x "$APP/Contents/MacOS/zapusk"

# Иконка: рисуем средствами системы, ничего не скачиваем.
ISET="$(mktemp -d)/ikonka.iconset"
mkdir -p "$ISET"
PNG="$(mktemp -d)/znak.png"
/usr/bin/python3 - "$PNG" <<'PY' 2>/dev/null || true
import sys, zlib, struct
razmer = 1024
piksely = bytearray()
for y in range(razmer):
    piksely.append(0)
    for x in range(razmer):
        # мягкий градиент по диагонали
        t = (x + y) / (2 * razmer)
        piksely += bytes((int(120 + 80 * t), int(70 + 90 * t), int(210 + 40 * t), 255))
def chunk(tip, dannye):
    c = tip + dannye
    return struct.pack('>I', len(dannye)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
png = (b'\x89PNG\r\n\x1a\n'
       + chunk(b'IHDR', struct.pack('>IIBBBBB', razmer, razmer, 8, 6, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(bytes(piksely), 9))
       + chunk(b'IEND', b''))
open(sys.argv[1], 'wb').write(png)
PY

if [ -f "$PNG" ]; then
  for r in 16 32 64 128 256 512; do
    sips -z $r $r "$PNG" --out "$ISET/icon_${r}x${r}.png" >/dev/null 2>&1 || true
  done
  cp "$PNG" "$ISET/icon_512x512@2x.png" 2>/dev/null || true
  iconutil -c icns "$ISET" -o "$APP/Contents/Resources/ikonka.icns" >/dev/null 2>&1 || true
fi

touch "$APP"
echo "Готово. На рабочем столе появилась иконка «Офис» - открывай двойным кликом."
