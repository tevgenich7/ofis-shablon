"""
Операции офиса на Google Диске от имени владелицы (OAuth, скоуп drive.file).

Всё, что офис создаёт, лежит в одной папке «Офис - рабочие файлы» на её Диске и в её
подпапках. Папку эту создаёт само приложение - иначе оно её не увидит: drive.file даёт
доступ только к своим файлам. Владелица может перетащить папку куда угодно на Диске,
доступ сохранится.

Файлы, которые создала не эта папка офиса (её старые документы, чужие таблицы),
офису не видны: попытка писать туда даст 404. Это граница по замыслу, а не ошибка.
"""

from __future__ import annotations

from pathlib import Path

from googleapiclient.http import MediaFileUpload

from docs import BODY, clear, write_blocks

KOREN = "Офис - рабочие файлы"

MIME_PAPKA = "application/vnd.google-apps.folder"
MIME_DOK = "application/vnd.google-apps.document"
MIME_TABLICA = "application/vnd.google-apps.spreadsheet"

POLYA = "id,name,webViewLink,mimeType"


# ── папки ────────────────────────────────────────────────────────────────────

def _najti_papku(k, imya: str, roditel: str | None) -> str | None:
    q = [f"name = '{imya}'", f"mimeType = '{MIME_PAPKA}'", "trashed = false"]
    if roditel:
        q.append(f"'{roditel}' in parents")
    est = k["drive"].files().list(q=" and ".join(q), fields="files(id)", pageSize=10).execute()
    files = est.get("files", [])
    return files[0]["id"] if files else None


def _sozdat_papku(k, imya: str, roditel: str | None) -> str:
    body = {"name": imya, "mimeType": MIME_PAPKA}
    if roditel:
        body["parents"] = [roditel]
    return k["drive"].files().create(body=body, fields="id").execute()["id"]


def korennaya_papka(k) -> str:
    """Рабочая папка офиса на Диске. Нет - создаём."""
    return _najti_papku(k, KOREN, None) or _sozdat_papku(k, KOREN, None)


def papka(k, imya: str = "") -> str:
    """Подпапка под задачу («рилсы», «авито», «мемы»). Пусто - корневая папка офиса."""
    koren = korennaya_papka(k)
    if not imya:
        return koren
    return _najti_papku(k, imya, koren) or _sozdat_papku(k, imya, koren)


# ── поиск ────────────────────────────────────────────────────────────────────

def spisok(k, mime: str | None = None, v_papke: str = "") -> list[dict]:
    """Файлы, созданные офисом. mime - отфильтровать по типу, v_papke - по подпапке."""
    q = ["trashed = false", f"'{papka(k, v_papke)}' in parents"]
    if mime:
        q.append(f"mimeType = '{mime}'")
    return k["drive"].files().list(
        q=" and ".join(q), fields=f"files({POLYA})", pageSize=200,
        orderBy="modifiedTime desc").execute().get("files", [])


def najti(k, imya: str, mime: str | None = None) -> dict | None:
    """Файл офиса по имени - точное совпадение, иначе по вхождению. Свежий важнее."""
    q = ["trashed = false"]
    if mime:
        q.append(f"mimeType = '{mime}'")
    vse = k["drive"].files().list(
        q=" and ".join(q), fields=f"files({POLYA})", pageSize=200,
        orderBy="modifiedTime desc").execute().get("files", [])
    imya_l = imya.strip().lower()
    for f in vse:
        if f["name"].strip().lower() == imya_l:
            return f
    for f in vse:
        if imya_l in f["name"].lower():
            return f
    return None


# ── документы ────────────────────────────────────────────────────────────────

def novyy_dokument(k, imya: str, bloki: list[tuple[str, str]] | None = None,
                   v_papke: str = "") -> dict:
    """Создать документ под задачу и залить содержимое."""
    fajl = k["drive"].files().create(
        body={"name": imya, "mimeType": MIME_DOK, "parents": [papka(k, v_papke)]},
        fields=POLYA).execute()
    if bloki:
        write_blocks(k["docs"], fajl["id"], bloki)
    return fajl


def perezalit_dokument(k, doc_id: str, bloki: list[tuple[str, str]]) -> None:
    """Вычистить документ и залить заново - источник правды остаётся в файлах офиса."""
    clear(k["docs"], doc_id)
    write_blocks(k["docs"], doc_id, bloki)


# ── таблицы ──────────────────────────────────────────────────────────────────

def novaya_tablica(k, imya: str, v_papke: str = "") -> dict:
    """Создать книгу под задачу. Первая вкладка называется «Лист1»."""
    return k["drive"].files().create(
        body={"name": imya, "mimeType": MIME_TABLICA, "parents": [papka(k, v_papke)]},
        fields=POLYA).execute()


def vkladki(k, book_id: str) -> dict[str, int]:
    meta = k["sheets"].spreadsheets().get(
        spreadsheetId=book_id, fields="sheets(properties(sheetId,title))").execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}


def vkladka(k, book_id: str, imya: str) -> int:
    """Вкладка с таким именем: вернуть существующую или создать. Возвращает gid."""
    est = vkladki(k, book_id)
    if imya in est:
        return est[imya]
    otvet = k["sheets"].spreadsheets().batchUpdate(
        spreadsheetId=book_id,
        body={"requests": [{"addSheet": {"properties": {"title": imya}}}]}).execute()
    return otvet["replies"][0]["addSheet"]["properties"]["sheetId"]


def zapisat(k, book_id: str, vkl: str, stroki: list[list], nachalo: str = "A1") -> None:
    k["sheets"].spreadsheets().values().update(
        spreadsheetId=book_id, range=f"'{vkl}'!{nachalo}",
        valueInputOption="USER_ENTERED", body={"values": stroki}).execute()


def dopisat(k, book_id: str, vkl: str, stroki: list[list]) -> None:
    k["sheets"].spreadsheets().values().append(
        spreadsheetId=book_id, range=f"'{vkl}'!A1",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": stroki}).execute()


def chitat(k, book_id: str, vkl: str, diapazon: str = "A1:Z1000") -> list[list]:
    got = k["sheets"].spreadsheets().values().get(
        spreadsheetId=book_id, range=f"'{vkl}'!{diapazon}").execute()
    return got.get("values", [])


# ── файлы ────────────────────────────────────────────────────────────────────

def zagruzit(k, put: Path, v_papke: str = "") -> dict:
    """Залить файл на Диск. Файл с тем же именем в той же папке обновляется, а не дублируется."""
    papka_id = papka(k, v_papke)
    est = k["drive"].files().list(
        q=f"'{papka_id}' in parents and trashed = false and name = '{put.name}'",
        fields="files(id)", pageSize=10).execute().get("files", [])
    media = MediaFileUpload(str(put), resumable=put.stat().st_size > 5_000_000)
    if est:
        return k["drive"].files().update(
            fileId=est[0]["id"], media_body=media, fields=POLYA).execute()
    return k["drive"].files().create(
        body={"name": put.name, "parents": [papka_id]}, media_body=media,
        fields=POLYA).execute()


__all__ = [
    "KOREN", "MIME_DOK", "MIME_TABLICA", "BODY",
    "korennaya_papka", "papka", "spisok", "najti",
    "novyy_dokument", "perezalit_dokument",
    "novaya_tablica", "vkladki", "vkladka", "zapisat", "dopisat", "chitat",
    "zagruzit",
]
