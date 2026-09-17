#!/bin/bash
# Включает вечерний порядок: каждый день в 22:00 офис прибирается и сохраняет копию.
# Ставится один раз на этом компьютере. Выключить - vecher-postavit.sh vyklyuchit
set -e
KOREN="$(cd "$(dirname "$0")/.." && pwd)"
IMYA="local.ofis.vecher"
PLIST="$HOME/Library/LaunchAgents/$IMYA.plist"

if [ "${1:-}" = "vyklyuchit" ]; then
  launchctl bootout "gui/$(id -u)/$IMYA" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Вечерний порядок выключен."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$KOREN/team/ops"
cat > "$PLIST" <<PLI
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$IMYA</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$KOREN/scripts/vecher.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>22</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$KOREN/team/ops/vecher.log</string>
  <key>StandardErrorPath</key><string>$KOREN/team/ops/vecher.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLI

launchctl bootout "gui/$(id -u)/$IMYA" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Готово: каждый день в 22:00 офис прибирается и сохраняет копию."
echo "Проверить прямо сейчас: bash scripts/vecher.sh"
