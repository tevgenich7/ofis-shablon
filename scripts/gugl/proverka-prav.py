"""Проверить, что доступ офиса к Google жив (OAuth-токен владелицы, скоуп drive.file).

Ничего не создаёт и не удаляет: смотрит, есть ли токен, и пробует прочитать список
файлов, которые офис создал сам. Полная проверка боем (создать и удалить пробные
документ, таблицу и файл) - scripts/gugl/avtorizaciya.py.

    scripts/gugl/venv/bin/python3 scripts/gugl/proverka-prav.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from googleapiclient.errors import HttpError  # noqa: E402

import gauth  # noqa: E402


def main() -> None:
    if not gauth.est_oauth():
        sys.exit(gauth.NET_TOKENA)
    k = gauth.moi()
    try:
        fajly = k["drive"].files().list(
            q="trashed=false", fields="files(id,name,mimeType)", pageSize=50,
            orderBy="modifiedTime desc").execute().get("files", [])
    except HttpError as e:
        sys.exit(f"Drive API не отвечает ({e.status_code}): {e.reason}")

    print(f"[ok] токен действует, файлов офиса на её Диске: {len(fajly)}")
    for f in fajly[:15]:
        print(f"  - {f['name']}  [{f['mimeType'].split('.')[-1]}]")
    if not fajly:
        print("Файлов пока нет - это нормально для нового офиса; создавать умеет avtorizaciya.py (проверка боем).")


if __name__ == "__main__":
    main()
