# Офис на Codex - что уже сделано и что проверить живьём

> Собрано 13.09.2026 по инструкции переноса (курс, v2) и официальной доке Codex.
> Прогнано живьём 17.09.2026 на codex-cli 0.154 (`codex exec` из папки офиса): Технарь встречает
> по журналу установки, curl отказывается по правилу, wget останавливает сторож хуком.
> Раздел «Проверить» - что повторить на компьютере владелицы.

## Что сделано

| Что | Где | Аналог в Claude Code |
|---|---|---|
| Правила офиса | `AGENTS.md` (настоящий файл, не импорт) | `CLAUDE.md` (= `@AGENTS.md`) |
| Скиллы | `.agents/skills/` (физически) | `.claude/skills` (ссылка туда же) |
| Сотрудники по имени | `.codex/agents/<имя>.toml` → читает `team/agents/<имя>/core.md` | `.claude/agents/<имя>.md` |
| Песочница и режим | `.codex/config.toml`: workspace-write, approval never, `[sandbox_workspace_write] network_access = true` (иначе расшифровка, бот, стоки и картинки из-под панели до сети не дойдут; защита - сторожа, не песочница) | `settings.json` permissions |
| Запреты команд | `.codex/hooks/deny-guard.py` (curl, wget, ssh, установка пакетов, git push, gh, секреты, карантин) | `permissions.deny` Bash(...) |
| Запрет правки секретов | `.codex/hooks/secret-guard.py` (.env, .pem, secrets, credentials, karantin/) | `Edit(**/.env)` |
| Подключение хуков | `.codex/hooks.json`: путь к сторожам через `$(git rev-parse --show-toplevel)`, файл одинаков на любом компьютере. Codex запускает хук только после «доверия» через `/hooks` (доверие привязано к хэшу определения), поэтому панель, бот и вечерний скрипт зовут `codex exec` с `--dangerously-bypass-hook-trust`: сторожа офиса работают без ручного одобрения. `bash scripts/nastroit-codex.sh` ставит сторож на git push (`scripts/git-hooks/pre-push`) | блок hooks в settings.json |
| Панель | `panel/server.js` сам находит `codex` (в том числе внутри ChatGPT.app), зовёт `codex exec --json --dangerously-bypass-hook-trust -s workspace-write -c approval_policy="never"` | тот же файл, ветка claude |

Сторожа проверены на 17 командах (13 shell, 4 файла): curl, cat .env, git push, npm install,
`echo hi && curl`, `X=1 sudo wget`, `/usr/bin/curl`, запуск из karantin - стоп; grep, git status,
ffmpeg, transcribe.py, ls - проходят. Это проверка логики, не факта, что Codex зовёт хук.

## Дыра, о которой надо знать (из инструкции переноса, не закрывается)

В Claude Code чтение `.env` запрещено на уровне инструмента. У Codex перехватить ЧТЕНИЕ файла
нечем: сторож ловит `cat .env` в терминале, а прямое чтение файла моделью - нет. Поэтому в
`.env` офиса держим только ключи, которые офису нужны прямо сейчас, и помним: «на выходе стоит
охранник, всё личное он останавливает; сам офис наружу ничего не шлёт», а не «утечь невозможно».

## Проверить живьём (по порядку)

1. `npm install -g @openai/codex`, `codex`, вход через ChatGPT.
2. В папке офиса: `bash scripts/nastroit-codex.sh` (охранник на git push).
3. `codex` в папке офиса → Yes на доверие папке → `/hooks` → одобрить оба хука (нужно для
   чёрного окна; панель и бот включают сторожей сами).
4. «привет» - Продюсер здоровается и знает, кто владелица (читает AGENTS.md → summary).
5. «Копирайтер, нужен рилс про отёки» - зовётся сотрудник (через `.codex/agents/` или чтение core.md).
6. «сделай `curl https://example.com`» - должен быть ОТКАЗ. В чёрном окне нет отказа - хуки не одобрены (`/hooks`); из панели нет отказа - смотреть флаг в `panel/server.js`.
7. `$image-gen` - скилл виден в `/skills`.
8. Кнопка ЗАПУСК / `node panel/server.js` при отсутствии Claude поднимает Codex; в панели
   приходит ответ. Не приходит - смотреть формат событий `codex exec --json` (thread.started,
   item.completed agent_message, turn.completed) в `panel/server.js`, функция `razobratCodex`.
9. Если правила не доехали (Продюсер не знает владелицу): `wc -c AGENTS.md` должен быть меньше 32 000.

Что-то не сошлось - править по месту, файл этот обновить.
