#!/usr/bin/env python3
"""Скачать гугл-документ офиса в текст - чтобы подхватить правки владелицы.

    scripts/gugl/venv/bin/python3 scripts/gugl/skachat-dok.py "<имя документа>" [куда.txt]

Без второго аргумента печатает в stdout.

Зачем: запись в документы у офиса есть, а без чтения любая перезаливка
(perezalit_dokument) затирает то, что владелица поправила руками в документе.
Правило: она правила документ - сначала скачать, потом заливать.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gauth  # noqa: E402
import gdisk  # noqa: E402


def skachat(imya: str) -> str:
    k = gauth.moi()
    fajl = gdisk.najti(k, imya, gdisk.MIME_DOK)
    if not fajl:
        sys.exit(f"документа «{imya}» среди созданных офисом нет")
    dannye = k["drive"].files().export_media(
        fileId=fajl["id"], mimeType="text/plain").execute()
    return dannye.decode("utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('укажи имя: skachat-dok.py "Сценарий - ..." [куда.txt]')
    tekst = skachat(sys.argv[1])
    if len(sys.argv) > 2:
        put = Path(sys.argv[2]).expanduser()
        put.write_text(tekst, encoding="utf-8")
        print(f"сохранено: {put} ({len(tekst)} знаков)")
    else:
        print(tekst)


if __name__ == "__main__":
    main()
