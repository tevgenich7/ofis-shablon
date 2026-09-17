"""
Разовая авторизация офиса в Google от имени владелицы.

Печатает ссылку - владелица открывает её в браузере и подтверждает доступ. Токен ложится
в .mcp-sheets/token.json и дальше живёт сам (в статусе приложения «In production»
refresh-токен не протухает; протухает он только в статусе Testing, через 7 дней).

    scripts/gugl/venv/bin/python3 scripts/gugl/avtorizaciya.py

После авторизации проверяет боем: создаёт папку, документ и таблицу, пишет и читает,
загружает файл на Диск. Всё созданное на проверке тут же удаляет, кроме рабочей папки.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402
from googleapiclient.http import MediaInMemoryUpload  # noqa: E402

import gauth  # noqa: E402
import gdisk  # noqa: E402


def poluchit_token() -> None:
    if gauth.TOKEN.exists():
        creds = gauth.oauth_creds(trebovat=False)
        if creds and creds.valid:
            print("[ok] токен уже есть и действует")
            return
        print("[..] токен есть, но недействителен - авторизуемся заново")

    if not gauth.CREDS.exists():
        sys.exit(
            f"нет файла OAuth-клиента: {gauth.CREDS}\n"
            "Скачай его в Google Cloud → Google Auth Platform → Clients → «Офис» → Download JSON."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(gauth.CREDS), gauth.SCOPES)
    creds = flow.run_local_server(
        port=0,
        open_browser=False,
        authorization_prompt_message=(
            "\n>>> ОТКРОЙ ЭТУ ССЫЛКУ В БРАУЗЕРЕ:\n{url}\n\n"
            "Экран «Google не проверило это приложение» - это нормально: приложение твоё, "
            "верификация под скоуп drive.file не нужна.\n"
            "Жми «Дополнительные настройки» → «Перейти на страницу...» → «Продолжить».\n"
        ),
        success_message="Готово. Можно закрывать вкладку и возвращаться в офис.",
    )
    gauth.TOKEN.write_text(creds.to_json())
    print(f"[ok] токен сохранён: {gauth.TOKEN}")


def proverka_boem() -> None:
    k = gauth.moi()

    try:
        papka = gdisk.korennaya_papka(k)
    except HttpError as e:
        sys.exit(f"[!] Drive API не отвечает ({e.status_code}): {e.reason}")
    print(f"[ok] рабочая папка на Диске: «{gdisk.KOREN}» ({papka})")

    doc = gdisk.novyy_dokument(k, "проверка связи - документ", [("Связь офиса с гуглом работает", "NORMAL_TEXT")])
    print(f"[ok] документ создан и заполнен: {doc['webViewLink']}")

    kniga = gdisk.novaya_tablica(k, "проверка связи - таблица")
    pervaya = next(iter(gdisk.vkladki(k, kniga["id"])))   # имя первой вкладки зависит от локали
    gdisk.zapisat(k, kniga["id"], pervaya, [["что", "значение"], ["связь офис-гугл", "работает"]])
    nazad = gdisk.chitat(k, kniga["id"], pervaya, "A1:B2")
    print(f"[ok] таблица создана, записано и прочитано обратно: {nazad}")

    media = MediaInMemoryUpload(b"proverka svyazi", mimetype="text/plain")
    fajl = k["drive"].files().create(
        body={"name": "проверка связи.txt", "parents": [papka]},
        media_body=media, fields="id,webViewLink").execute()
    print("[ok] файл на Диск загружается - значит мемы и тяжёлое тоже поедут")

    for f in (doc["id"], kniga["id"], fajl["id"]):
        k["drive"].files().delete(fileId=f).execute()
    print("[ok] проверочные файлы удалены, папка осталась\n")
    print("Офис теперь умеет: новый документ под задачу · новая таблица под задачу · "
          "загрузка файлов на Диск · свои подпапки.")


if __name__ == "__main__":
    poluchit_token()
    proverka_boem()
