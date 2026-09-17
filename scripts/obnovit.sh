#!/bin/bash
# Обновить офис из репозитория продукта.
#
#   bash scripts/obnovit.sh            - показать, что изменится (ничего не трогает)
#   bash scripts/obnovit.sh --primenit - применить обновление
#
# Обновляются ТОЛЬКО служебные файлы офиса: панель, скрипты, характеры сотрудников,
# охрана, инструкции. Работа владелицы не трогается никогда: её файлы, ключи,
# память сотрудников, журналы и разговоры остаются как есть.
set -e
KOREN="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${OFIS_REPO:-https://github.com/tevgenich7/ofis-shablon.git}"

# ── что считается служебным (обновляется) ────────────────────────────────────
SLUZHEBNOE=(
  "panel/index.html" "panel/server.js"
  "scripts" ".codex" ".claude" ".agents"
  "CLAUDE.md" "AGENTS.md" "УСТАНОВКА.md" "НАЧНИ ОТСЮДА.html" "ЗАПУСК.command" ".gitignore"
  "team/map.md" "team/hiring.md" "team/agents/_memory-template.md"
)
# Внутри папок сотрудников обновляем всё, КРОМЕ памяти - там их работа с владелицей.
LICHNOE_VNUTRI=("memory.md")

soobshit() { printf '%s\n' "$1"; }

# ── забираем свежую версию во временную папку ────────────────────────────────
VREMENNAYA="$(mktemp -d)"
trap 'rm -rf "$VREMENNAYA"' EXIT

soobshit ""
soobshit "  Смотрю, что нового…"
if ! git clone --quiet --depth 1 "$REPO" "$VREMENNAYA/svezhee" 2>/dev/null; then
  soobshit ""
  soobshit "  Не получилось забрать обновления."
  soobshit "  Скорее всего нет интернета - проверь связь и попробуй ещё раз."
  soobshit ""
  exit 1
fi
SVEZHEE="$VREMENNAYA/svezhee"

# ── собираем список файлов к обновлению ──────────────────────────────────────
SPISOK="$VREMENNAYA/spisok"
: > "$SPISOK"

dobavit_fajl() {
  local otn="$1"
  case " ${LICHNOE_VNUTRI[*]} " in *" $(basename "$otn") "*) return;; esac
  [ -f "$SVEZHEE/$otn" ] || return
  if [ ! -f "$KOREN/$otn" ]; then
    printf 'новый\t%s\n' "$otn" >> "$SPISOK"
  elif ! cmp -s "$SVEZHEE/$otn" "$KOREN/$otn"; then
    printf 'изменён\t%s\n' "$otn" >> "$SPISOK"
  fi
}

for put in "${SLUZHEBNOE[@]}"; do
  if [ -d "$SVEZHEE/$put" ]; then
    while IFS= read -r f; do dobavit_fajl "${f#"$SVEZHEE/"}"; done \
      < <(find "$SVEZHEE/$put" -type f ! -name '*.log' ! -name 'razgovory.json')
  else
    dobavit_fajl "$put"
  fi
done

# Папки сотрудников: всё кроме памяти.
if [ -d "$SVEZHEE/team/agents" ]; then
  while IFS= read -r f; do dobavit_fajl "${f#"$SVEZHEE/"}"; done \
    < <(find "$SVEZHEE/team/agents" -type f ! -name 'memory.md')
fi

if [ ! -s "$SPISOK" ]; then
  soobshit ""
  soobshit "  Офис уже свежий, обновлять нечего."
  soobshit ""
  exit 0
fi

KOLICHESTVO="$(wc -l < "$SPISOK" | tr -d ' ')"
soobshit ""
soobshit "  Есть обновление: файлов - $KOLICHESTVO"
soobshit ""
sort -k2 "$SPISOK" | while IFS=$'\t' read -r sostoyanie put; do
  printf '    %-8s %s\n' "$sostoyanie" "$put"
done
soobshit ""

# ── что нового, словами ──────────────────────────────────────────────────────
if [ -f "$SVEZHEE/team/ops/obnovleniya.md" ]; then
  soobshit "  Что изменилось:"
  soobshit ""
  sed -n '/^## /,$p' "$SVEZHEE/team/ops/obnovleniya.md" | head -30 | sed 's/^/    /'
  soobshit ""
fi

if [ "$1" != "--primenit" ]; then
  soobshit "  Это был просмотр, ничего не тронуто."
  soobshit "  Применить:  bash scripts/obnovit.sh --primenit"
  soobshit ""
  exit 0
fi

# ── применяем, сохранив старое ───────────────────────────────────────────────
SHTAMP="$(date +%Y-%m-%d-%H%M%S)"
ZAPAS="$KOREN/karantin/do-obnovleniya-$SHTAMP"
mkdir -p "$ZAPAS"

# Одна упрямая строка не должна бросать офис наполовину обновлённым:
# что не вышло - запоминаем и говорим в конце, остальное доделываем.
NE_VYSHLO="$VREMENNAYA/ne-vyshlo"
: > "$NE_VYSHLO"
SDELANO=0

set +e
while IFS=$'\t' read -r sostoyanie put; do
  if [ -f "$KOREN/$put" ]; then
    mkdir -p "$ZAPAS/$(dirname "$put")" 2>/dev/null
    cp -p "$KOREN/$put" "$ZAPAS/$put" 2>/dev/null
  fi
  mkdir -p "$KOREN/$(dirname "$put")" 2>/dev/null
  oshibka="$(cp -p "$SVEZHEE/$put" "$KOREN/$put" 2>&1)"
  if [ $? -ne 0 ]; then
    # Файл мог быть защищён от записи - пробуем снять защиту и повторить.
    chmod u+w "$KOREN/$put" 2>/dev/null
    oshibka="$(cp -p "$SVEZHEE/$put" "$KOREN/$put" 2>&1)"
    if [ $? -ne 0 ]; then
      printf '%s\t%s\n' "$put" "${oshibka:-причина не названа}" >> "$NE_VYSHLO"
      continue
    fi
  fi
  SDELANO=$((SDELANO + 1))
done < "$SPISOK"
set -e

chmod +x "$KOREN/ЗАПУСК.command" 2>/dev/null || true
find "$KOREN/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
find "$KOREN/.codex/hooks" -name '*.py' -exec chmod +x {} \; 2>/dev/null || true

if [ -s "$NE_VYSHLO" ]; then
  soobshit "  Обновлено файлов: $SDELANO из $KOLICHESTVO"
  soobshit ""
  soobshit "  Эти заменить не удалось - офис работает, но они остались прежними:"
  soobshit ""
  while IFS=$'\t' read -r put prichina; do
    printf '    %s\n      %s\n' "$put" "$prichina"
  done < "$NE_VYSHLO"
  soobshit ""
  soobshit "  Покажи эти строки тому, кто ставил офис - причина обычно в правах на файл."
  soobshit ""
else
  soobshit "  Готово: обновлено файлов - $SDELANO"
fi
soobshit "  Прежние версии лежат тут, если что-то пойдёт не так:"
soobshit "      karantin/do-obnovleniya-$SHTAMP"
soobshit ""
soobshit "  Закрой офис и открой заново значком - обновление вступит в силу."
soobshit ""
