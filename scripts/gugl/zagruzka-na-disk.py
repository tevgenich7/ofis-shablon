#!/usr/bin/env python3
"""Загрузка файлов в папку офиса на Google Диске владелицы (OAuth, drive.file).

Папка офиса на её Диске («Офис - рабочие файлы») создаётся сама при первой загрузке.

    scripts/gugl/venv/bin/python3 scripts/gugl/zagruzka-na-disk.py <файл> [<файл> ...] [--papka ИМЯ]

--papka кладёт файлы в подпапку внутри папки офиса (создаст, если нет).
Печатает по строке на файл: имя, id и прямую ссылку на просмотр.

Файл с тем же именем в той же папке ПЕРЕЗАПИСЫВАЕТСЯ (обновляется содержимое,
ссылка сохраняется) - чтобы повторный прогон не плодил дубли.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gauth  # noqa: E402
import gdisk  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)

    papka_imya = ""
    if "--papka" in args:
        i = args.index("--papka")
        if i + 1 >= len(args):
            sys.exit("после --papka нужно имя подпапки")
        papka_imya = args[i + 1]
        args = args[:i] + args[i + 2:]

    fajly = [Path(a) for a in args]
    net = [f for f in fajly if not f.exists()]
    if net:
        sys.exit("нет таких файлов: " + ", ".join(str(f) for f in net))

    k = gauth.moi()
    if papka_imya:
        print(f"папка: {papka_imya}")
    for f in fajly:
        r = gdisk.zagruzit(k, f, papka_imya)
        print(f"{r['name']}\t{r['id']}\t{r.get('webViewLink', '')}")


if __name__ == "__main__":
    main()
