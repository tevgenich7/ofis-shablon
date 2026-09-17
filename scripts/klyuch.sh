#!/bin/bash
# Положить пропуск (ключ от сервиса) в файл ключей офиса, не открывая редакторов.
#
#   bash scripts/klyuch.sh              - покажет список пропусков и что уже стоит
#   bash scripts/klyuch.sh DEEPGRAM_API_KEY   - спросит значение и запишет
#
# Значение вводится скрытно: на экране не видно и в историю команд не попадает.
set -e
KOREN="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$KOREN/.env"
touch "$ENV"; chmod 600 "$ENV"

pokazat() {
  echo ""
  echo "  Пропуска офиса:"
  echo ""
  for k in DEEPGRAM_API_KEY GEMINI_API_KEY FAL_KEY PEXELS_API_KEY UNSPLASH_API_KEY PIXABAY_API_KEY TELEGRAM_BOT_TOKEN; do
    case "$k" in
      DEEPGRAM_API_KEY)  o="расшифровка речи - офис слышит, что сказано в дублях";;
      GEMINI_API_KEY)    o="картинки: обложки, фоны, слайды";;
      FAL_KEY)           o="картинки посложнее, по кадру-образцу";;
      PEXELS_API_KEY)    o="стоки: перебивки и фоны";;
      UNSPLASH_API_KEY)  o="стоки: запасной";;
      PIXABAY_API_KEY)   o="стоки: запасной";;
      TELEGRAM_BOT_TOKEN) o="бот офиса в телеграме";;
    esac
    if grep -q "^$k=." "$ENV" 2>/dev/null; then echo "  [есть]  $k - $o"; else echo "  [нет ]  $k - $o"; fi
  done
  echo ""
  echo "  Поставить пропуск:  bash scripts/klyuch.sh ИМЯ"
  echo "  Например:           bash scripts/klyuch.sh DEEPGRAM_API_KEY"
  echo ""
}

[ -z "$1" ] && { pokazat; exit 0; }

IMYA="$1"
case "$IMYA" in
  *[!A-Z_0-9]*) echo "Имя пропуска пишется заглавными латинскими буквами, например DEEPGRAM_API_KEY"; exit 1;;
esac

echo ""
echo "Вставь значение пропуска $IMYA и нажми Enter."
echo "На экране оно не появится - так и задумано."
read -r -s ZNACHENIE
echo ""
[ -z "$ZNACHENIE" ] && { echo "Пусто, ничего не записал."; exit 1; }

case "$ZNACHENIE" in
  *[[:space:]]*) echo "В значении есть пробел - похоже, скопировалось лишнее. Скопируй ещё раз только сам ключ."; exit 1;;
esac

VREMENNYJ="$(mktemp)"
grep -v "^$IMYA=" "$ENV" > "$VREMENNYJ" 2>/dev/null || true
printf '%s=%s\n' "$IMYA" "$ZNACHENIE" >> "$VREMENNYJ"
mv "$VREMENNYJ" "$ENV"; chmod 600 "$ENV"

echo "Готово: пропуск $IMYA записан (${#ZNACHENIE} символов)."
echo "Открой панель офиса - точка напротив этого сервиса станет зелёной."
echo ""
