"""
Залить markdown-файлы офиса в Google-документ на Диске владелицы.

Зачем: сценарии живут в results/ как markdown (их правит офис), а на съёмке
нужен читаемый документ в телефоне. Скрипт переносит одно в другое, документ
каждый раз перезаписывается целиком - источник правды остаётся в файлах.

Запуск:
  scripts/gugl/venv/bin/python3 scripts/gugl/zalit-dok.py "<имя дока>" файл1.md [файл2.md ...]

Документа с таким именем нет - офис создаст его сам в своей папке на её Диске.
Документ есть - сначала скачай его (skachat-dok.py): её правки внутри иначе затрутся.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gauth  # noqa: E402
import gdisk  # noqa: E402
from docs import BODY  # noqa: E402
from md2docs import md_to_blocks  # noqa: E402

OFFICE = Path(__file__).resolve().parents[2]


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    doc_name, files = sys.argv[1], sys.argv[2:]

    blocks: list[tuple[str, str]] = []
    for n, path in enumerate(files):
        p = Path(path)
        if not p.is_absolute():
            p = OFFICE / p
        if not p.exists():
            sys.exit(f"нет файла: {p}")
        if n:
            blocks.append(("- - -", BODY))
        blocks.extend(md_to_blocks(p.read_text(encoding="utf-8")))

    k = gauth.moi()
    doc = gdisk.najti(k, doc_name, gdisk.MIME_DOK)
    if doc:
        gdisk.perezalit_dokument(k, doc["id"], blocks)
        print(f"перезалито {len(blocks)} абзацев в «{doc['name']}»")
    else:
        doc = gdisk.novyy_dokument(k, doc_name, blocks)
        print(f"создан документ «{doc['name']}», залито {len(blocks)} абзацев")
    print(doc["webViewLink"])


if __name__ == "__main__":
    main()
