@AGENTS.md

## Только для Claude Code

- Помощники по имени зовутся как субагенты через `.claude/agents/<имя>.md`; обёртка сама
  читает `team/agents/<имя>/core.md` и память.
- Скиллы лежат в `.agents/skills/` (общая папка для всех программ), `.claude/skills` - ссылка на неё.
- Права и запреты - `.claude/settings.json`.
