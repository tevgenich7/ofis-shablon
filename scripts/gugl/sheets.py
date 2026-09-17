"""
Google Sheets для офиса - от имени владелицы (OAuth, скоуп drive.file).

Таблицы создаёт сам офис в своей папке на её Диске («Офис - рабочие файлы», см. gdisk.py),
он же добавляет вкладки, пишет и читает. Чужие таблицы офису не видны: только те,
которые он создал сам.

Основные операции живут в gdisk.py (novaya_tablica, vkladka, zapisat, dopisat, chitat);
здесь - тонкие обёртки для старых вызовов и проверка связи.

Проверка связи: scripts/gugl/venv/bin/python3 scripts/gugl/sheets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from googleapiclient.errors import HttpError  # noqa: E402

import gauth  # noqa: E402
import gdisk  # noqa: E402

OFFICE = Path(__file__).resolve().parents[2]


def services():
    """(sheets, drive) от имени владелицы. Нет токена - человеческая подсказка и выход."""
    k = gauth.moi()
    return k["sheets"], k["drive"]


def find_books(drive) -> list[dict]:
    """Все таблицы, которые создал офис (свежие первыми)."""
    return drive.files().list(
        q=f"mimeType='{gdisk.MIME_TABLICA}' and trashed=false",
        fields="files(id,name,webViewLink)", pageSize=50, orderBy="modifiedTime desc",
    ).execute().get("files", [])


def tabs(sheets, book_id: str) -> dict[str, int]:
    """Вкладки книги: имя → gid."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=book_id, fields="sheets(properties(sheetId,title))"
    ).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}


def ensure_tab(sheets, book_id: str, title: str) -> int:
    """Вкладка с таким именем: вернуть существующую или создать. Возвращает gid."""
    have = tabs(sheets, book_id)
    if title in have:
        return have[title]
    res = sheets.spreadsheets().batchUpdate(
        spreadsheetId=book_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def write(sheets, book_id: str, tab: str, rows: list[list], start: str = "A1") -> None:
    sheets.spreadsheets().values().update(
        spreadsheetId=book_id,
        range=f"'{tab}'!{start}",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def read(sheets, book_id: str, tab: str, rng: str = "A1:Z1000") -> list[list]:
    got = sheets.spreadsheets().values().get(
        spreadsheetId=book_id, range=f"'{tab}'!{rng}"
    ).execute()
    return got.get("values", [])


def main() -> None:
    sheets, drive = services()

    try:
        books = find_books(drive)
    except HttpError as e:
        sys.exit(f"Drive API не отвечает ({e.status_code}): {e.reason}")

    if not books:
        print("Офис ещё не создавал ни одной таблицы - это нормально для нового офиса.")
        print("Проверка связи боем (создаёт и удаляет пробную таблицу):")
        print("  scripts/gugl/venv/bin/python3 scripts/gugl/avtorizaciya.py")
        return

    print(f"[ok] доступ жив, таблиц офиса: {len(books)}")
    for b in books[:10]:
        print(f"  - {b['name']}  →  {b['webViewLink']}")


if __name__ == "__main__":
    main()
