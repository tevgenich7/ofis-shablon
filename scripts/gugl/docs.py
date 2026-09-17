"""
Google Docs для офиса - от имени владелицы (OAuth, скоуп drive.file).

Документы создаёт сам офис в своей папке на её Диске (gdisk.novyy_dokument) и пишет
внутрь. Чужие документы ему не видны: только те, которые он создал сам.

Здесь - разметка документа: очистка и заливка блоков (текст, стиль абзаца).
Создание, поиск и перезаливка - в gdisk.py, конвертер markdown - в md2docs.py.

Проверка связи:  scripts/gugl/venv/bin/python3 scripts/gugl/docs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OFFICE = Path(__file__).resolve().parents[2]

MIME_DOK = "application/vnd.google-apps.document"

H1, H2, H3, H4, BODY = "HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4", "NORMAL_TEXT"

# псевдостиль: обычный абзац, но жирным текстом. Нужен под реплику в раскадровке -
# её читают вслух на съёмке, и глаз должен ловить её среди служебных полей.
BODY_BOLD = "NORMAL_TEXT_BOLD"


def services():
    """(docs, drive) от имени владелицы. Нет токена - человеческая подсказка и выход."""
    import gauth
    k = gauth.moi()
    return k["docs"], k["drive"]


def find_docs(drive) -> list[dict]:
    """Документы, которые создал офис (свежие первыми)."""
    return drive.files().list(
        q=f"mimeType='{MIME_DOK}' and trashed=false",
        fields="files(id,name,webViewLink)", pageSize=50, orderBy="modifiedTime desc",
    ).execute().get("files", [])


def u16(s: str) -> int:
    """Длина в кодовых единицах UTF-16 - именно так Docs считает индексы.
    Обычная len() врёт на эмодзи (они вне BMP и весят две единицы)."""
    return len(s.encode("utf-16-le")) // 2


def clear(docs, doc_id: str) -> None:
    """Вычистить документ целиком, чтобы залить заново."""
    doc = docs.documents().get(documentId=doc_id).execute()
    end = doc["body"]["content"][-1]["endIndex"]
    if end <= 2:  # пустой документ, удалять нечего
        return
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}}]},
    ).execute()


def write_blocks(docs, doc_id: str, blocks: list[tuple[str, str]]) -> None:
    """Залить документ списком (текст, стиль). Один insertText, потом стили абзацев.

    blocks: [("Заголовок", H1), ("текст абзаца", BODY), ...]
    """
    text = ""
    spans: list[tuple[int, int, str]] = []
    for chunk, style in blocks:
        start = u16(text)
        text += chunk + "\n"
        spans.append((start, u16(text), style))

    total = u16(text)
    reqs: list[dict] = [
        {"insertText": {"location": {"index": 1}, "text": text}},
        # сброс: вставленный текст наследует оформление того, что было в доке
        # до заливки, поэтому явно кладём всё в обычный стиль без жирного
        {"updateParagraphStyle": {
            "range": {"startIndex": 1, "endIndex": 1 + total},
            "paragraphStyle": {"namedStyleType": BODY},
            "fields": "namedStyleType",
        }},
        {"updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 1 + total},
            "textStyle": {"bold": False},
            "fields": "bold",
        }},
    ]
    for start, end, style in spans:
        if style == BODY:
            continue  # сброс выше уже сделал что надо
        if style == BODY_BOLD:
            reqs.append({
                "updateTextStyle": {
                    "range": {"startIndex": 1 + start, "endIndex": 1 + end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            continue
        reqs.append({
            "updateParagraphStyle": {
                "range": {"startIndex": 1 + start, "endIndex": 1 + end},
                "paragraphStyle": {"namedStyleType": style},
                "fields": "namedStyleType",
            }
        })
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": reqs}).execute()


if __name__ == "__main__":
    docs, drive = services()
    found = find_docs(drive)
    if not found:
        print("Офис ещё не создавал документов - это нормально для нового офиса.")
        print("Новый документ под задачу создаёт gdisk.novyy_dokument; проверка связи боем:")
        print("  scripts/gugl/venv/bin/python3 scripts/gugl/avtorizaciya.py")
        sys.exit(0)
    print(f"[ok] доступ жив, документов офиса: {len(found)}")
    for f in found[:10]:
        print(f"  - {f['name']}  →  {f['webViewLink']}")
