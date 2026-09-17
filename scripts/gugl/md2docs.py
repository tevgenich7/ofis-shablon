"""
Markdown офиса → блоки Google-документа.

Вынесено из zalit-dok.py, чтобы конвертером мог пользоваться и MCP-сервер:
источник правды остаётся в файлах results/, документ каждый раз пересобирается.
"""

from __future__ import annotations

import re

from docs import BODY, BODY_BOLD, H1, H2, H3, H4

# markdown-шум, который в документе не нужен
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITAL = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
CODE = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")

# блок раскадровки: «**0-5 сек**» - заголовок плана, под ним поля отдельными
# абзацами. Реплику выделяем жирным: на съёмке её читают вслух с телефона.
TIME = re.compile(r"^\*\*\d+[-–]\d+\s*сек\*\*$")
LINE_REPLIKA = re.compile(r"^\*\*Реплика[^*]*:\*\*")


def plain(s: str) -> str:
    s = BOLD.sub(r"\1", s)
    s = ITAL.sub(r"\1", s)
    s = CODE.sub(r"\1", s)
    s = LINK.sub(r"\1", s)
    return s.strip()


def md_to_blocks(md: str) -> list[tuple[str, str]]:
    """Markdown → список (текст, стиль). Таблицы разворачиваются в читаемые строки."""
    blocks: list[tuple[str, str]] = []
    lines = md.splitlines()
    i = 0
    head: list[str] = []          # шапка текущей таблицы
    buf: list[str] = []           # копим строки абзаца: markdown переносит их мягко

    def flush() -> None:
        if buf:
            blocks.append((" ".join(buf), BODY))
            buf.clear()

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        i += 1

        if not line.strip():
            flush()
            head = []
            continue

        # цитата-врезка: убираем «> » и печатаем как обычный абзац
        if line.startswith(">"):
            line = line.lstrip(">").strip()
            if not line:
                continue

        # заголовки
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush()
            level = len(m.group(1))
            style = {1: H1, 2: H1, 3: H2}.get(level, H3)
            blocks.append((plain(m.group(2)), style))
            head = []
            continue

        # горизонтальная линейка
        if re.match(r"^-{3,}$", line.strip()):
            flush()
            blocks.append(("- - -", BODY))
            head = []
            continue

        # таблица
        if line.strip().startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                continue                      # строка-разделитель шапки
            if not head:
                head = [plain(c) for c in cells]
                continue
            parts = []
            for name, val in zip(head, cells):
                val = plain(val)
                if val and val != "-":
                    parts.append(f"{name}: {val}" if name else val)
            if parts:
                blocks.append(("  ·  ".join(parts), BODY))
            continue

        head = []

        # обёртки кодовых блоков выкидываем, содержимое оставляем как текст
        if line.strip().startswith("```"):
            flush()
            continue

        # тайм раскадровки - заголовок плана, глубже подзаголовков блока,
        # чтобы в навигации документа таймы лежали внутри «Раскадровки»
        if TIME.match(line.strip()):
            flush()
            blocks.append((plain(line), H4))
            continue

        # реплика - свой абзац и жирным: её читают вслух прямо на съёмке
        if LINE_REPLIKA.match(line.strip()):
            flush()
            blocks.append((plain(line), BODY_BOLD))
            continue

        # строка целиком жирная («**Под суфлёр**») - это подзаголовок блока,
        # на съёмке по ним и ориентируешься
        if re.fullmatch(r"\*\*[^*]+\*\*:?", line.strip()):
            flush()
            blocks.append((plain(line).rstrip(":"), H3))
            continue

        # пункт списка - всегда отдельный абзац, склеивать нельзя
        if re.match(r"^\s*([-•*]|\d+\.)\s+", line):
            flush()
            blocks.append((plain(line), BODY))
            continue

        buf.append(plain(line))

    flush()
    return blocks
