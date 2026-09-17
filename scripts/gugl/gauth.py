"""
Авторизация офиса в Google - от имени владелицы, через OAuth.

  Токен владелицы: .mcp-sheets/token.json (появляется после avtorizaciya.py).
  Клиент OAuth:    .mcp-sheets/credentials.json (скачан из её проекта Google Cloud).

  Скоуп один - drive.file: офис видит и правит только те файлы, которые сам создал.
  В её Диск целиком он не заглядывает. Это non-sensitive скоуп, поэтому приложение
  публикуется без сайта и политики конфиденциальности.

  Приложение должно стоять в статусе «In production»: в статусе Testing Google убивает
  refresh-токен через 7 дней, и офис каждую неделю просит авторизоваться заново.

Другого способа входа (сервисные аккаунты) в офисе нет: у них нет места на Диске,
создавать файлы они не могут.
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

OFFICE = Path(__file__).resolve().parents[2]
SECRETS = OFFICE / ".mcp-sheets"
CREDS = SECRETS / "credentials.json"        # OAuth-клиент из её Google Cloud
TOKEN = SECRETS / "token.json"              # токен владелицы, появляется после avtorizaciya.py

# ровно один скоуп: он non-sensitive, значит приложение публикуется без верификации.
# Sheets и Docs API работают под ним для файлов, которые создало само приложение.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

NET_TOKENA = (
    "Офис ещё не авторизован в Google от имени владелицы.\n"
    "Один раз: scripts/gugl/venv/bin/python3 scripts/gugl/avtorizaciya.py\n"
    "До этого таблицы, документы, формы и Диск офису недоступны."
)


def oauth_creds(trebovat: bool = True) -> Credentials | None:
    """Токен владелицы. Протухший обновляем молча; нет файла - None (или выход с подсказкой)."""
    if not TOKEN.exists():
        if trebovat:
            sys.exit(NET_TOKENA)
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json())
        return creds
    if trebovat:
        sys.exit(
            "Токен Google больше не действует - переавторизация:\n"
            "  scripts/gugl/venv/bin/python3 scripts/gugl/avtorizaciya.py\n"
            "Если это повторяется каждую неделю - приложение вернулось в статус Testing, "
            "проверь в Google Auth Platform, что стоит «In production»."
        )
    return None


def api(creds):
    """Три клиента на одних правах: Диск, Документы, Таблицы."""
    return {
        "drive": build("drive", "v3", credentials=creds),
        "docs": build("docs", "v1", credentials=creds),
        "sheets": build("sheets", "v4", credentials=creds),
    }


def moi(trebovat: bool = True) -> dict | None:
    """Клиенты от имени владелицы (OAuth). Единственный режим работы офиса."""
    creds = oauth_creds(trebovat)
    return api(creds) if creds else None


def est_oauth() -> bool:
    return TOKEN.exists()
