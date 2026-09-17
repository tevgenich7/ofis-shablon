#!/bin/bash
# Вечерний порядок офиса. Запускается сам раз в день (см. vecher-postavit.sh).
#
# Три шага, всегда в этом порядке:
#   1. Уборщик приводит папки в порядок и пишет короткий отчёт
#   2. Отчёт уходит ей в телеграм - чтобы копия не уезжала молча
#   3. Копия офиса уходит в её приватный репозиторий
#
# Ничего не удаляет само: спорное Уборщик выносит в отчёт и оставляет на месте.

set -u
KOREN="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KOREN"

DATA="$(date +%Y-%m-%d)"
OTCHET="team/ops/uborka-$DATA.md"

# ── 1. уборка ────────────────────────────────────────────────────────────────
AGENT=""
for k in "${CODEX_BIN:-}" "$HOME/.local/bin/codex" /opt/homebrew/bin/codex /usr/local/bin/codex; do
  [ -n "$k" ] && [ -x "$k" ] && AGENT="$k" && break
done
[ -z "$AGENT" ] && AGENT="$(command -v codex || true)"

if [ -n "$AGENT" ]; then
  ZADANIE="Прочитай team/agents/uborshik/core.md и team/agents/uborshik/memory.md и работай по ним.
Ты Уборщик офиса. Вечерний обход, работай экономно: кроме этих двух файлов лишнего не читай,
в интернет не ходи. Что делаешь: разложи по местам всё, что лежит не там, проверь, что карты
и индексы сходятся с диском, найди мусор и дубли. САМ УДАЛЯЙ только заведомо временное
(кэш, .DS_Store, пустые папки). Всё спорное не трогай, а перечисли. Итог запиши в файл
$OTCHET: пять строк максимум, человеческим языком, без путей к файлам. Первой строкой -
одно предложение: что сделано. Если спорного нет, так и напиши."
  printf '%s' "$ZADANIE" | "$AGENT" exec --json --skip-git-repo-check --dangerously-bypass-hook-trust -s workspace-write -c approval_policy="never" -C "$KOREN" >/dev/null 2>&1
fi

# ── 2. сказать ей ────────────────────────────────────────────────────────────
if [ -f "$OTCHET" ]; then
  KRATKO="$(head -c 900 "$OTCHET")"
  python3 scripts/tg/skazat.py "Вечерний порядок в офисе.

$KRATKO

Копию за сегодня сохранил. Если что-то из этого трогать было нельзя - скажи утром, верну." >/dev/null 2>&1 || true
fi

# ── 3. копия в репозиторий ───────────────────────────────────────────────────
if [ -z "$(git status --porcelain)" ]; then
  echo "$(date '+%F %T') нечего сохранять"
  exit 0
fi

git add -A
git commit -q -m "офис: копия за $DATA" || true

# Наружу копия едет только если стоит охранник (.git/hooks/pre-push) и у него есть
# разрешённый адрес (team/ops/push-razreshen.txt, пишет Тарас на этапе 7). Иначе остаёмся
# на компьютере: без гейта офис ничего наружу не отправляет.
if git remote | grep -q . && [ -x .git/hooks/pre-push ] && [ -s team/ops/push-razreshen.txt ]; then
  if git push -q 2>/dev/null; then
    echo "$(date '+%F %T') копия уехала в репозиторий"
  else
    python3 scripts/tg/skazat.py "Копия офиса за сегодня сохранилась на компьютере, но в облако не уехала. Напиши Тарасу, он посмотрит." >/dev/null 2>&1 || true
    echo "$(date '+%F %T') push не прошёл"
  fi
else
  echo "$(date '+%F %T') копия сохранена на компьютере (облако не подключено или нет разрешения на отправку)"
fi
