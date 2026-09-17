"""
Гугл-формы руками офиса: создать анкету и наполнить её вопросами.

Владелец говорит «нужна анкета с такими вопросами» - офис пишет разметку и зовёт этот
скрипт. Ни редактора скриптов, ни ручной вставки: форма появляется готовой со ссылкой.

Запуск:
    python3 scripts/gugl/forma.py sozdat "09.09 - Анкета" --iz-fajla work/anketa.md
    python3 scripts/gugl/forma.py napolnit <id формы> --iz-fajla work/anketa.md

Разметка анкеты (простой текст, пишется руками или Копирайтером):

    # Заголовок формы
    Описание формы одной строкой.

    ## Название раздела     - каждый раздел идёт отдельной страницей формы
    = подсказка к разделу

    ?? Текст вопроса
    = подсказка под вопросом
    *                      - вопрос обязательный
    ~                      - короткий ответ (по умолчанию длинный, абзацем)
    + Вариант ответа       - «+» превращают вопрос в выбор одного варианта
    ++ Вариант ответа      - «++» разрешают отметить несколько
    + другое               - добавляет настоящее поле «Другое», а не пункт списка
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import gauth
import gdisk

# Скоуп берём тот же, что у остальных операций офиса - drive.file. Forms API его
# принимает для форм, которые приложение само и создало, поэтому отдельных прав
# и повторной авторизации не требуется (проверено 09.09.2026).

POCHTA_VLADELCA = "t.evgenich7@gmail.com"


# ── доступ ───────────────────────────────────────────────────────────────────

def klienty():
    """
    Работаем от имени владельца (OAuth), а не сервисного аккаунта: у сервисного
    аккаунта нет своего Диска, и любая новая форма упирается в квоту.
    """
    creds = gauth.oauth_creds()
    return {
        "forms": build("forms", "v1", credentials=creds),
        "drive": build("drive", "v3", credentials=creds),
    }


# ── разбор разметки ──────────────────────────────────────────────────────────

def razobrat(text: str) -> dict:
    zagolovok, opisanie, punkty = "", "", []
    tek = None

    def zakryt():
        nonlocal tek
        if tek:
            punkty.append(tek)
            tek = None

    for syraya in text.splitlines():
        s = syraya.strip()
        if not s:
            continue

        if s.startswith("# ") and not s.startswith("##"):
            zakryt()
            zagolovok = s[2:].strip()
        elif s.startswith("## "):
            zakryt()
            punkty.append({"vid": "razdel", "titul": s[3:].strip(), "podskazka": ""})
        elif s.startswith("?? "):
            zakryt()
            tek = {"vid": "vopros", "titul": s[3:].strip(), "podskazka": "",
                   "obyazatelnyj": False, "korotkij": False, "varianty": [],
                   "neskolko": False, "drugoe": False}
        elif s.startswith("= "):
            cel = tek if tek else (punkty[-1] if punkty else None)
            if cel is not None:
                cel["podskazka"] = s[2:].strip()
        elif s.startswith("++ ") or s.startswith("+ "):
            if tek:
                if s.startswith("++ "):
                    tek["neskolko"] = True
                    znachenie = s[3:].strip()
                else:
                    znachenie = s[2:].strip()
                if znachenie.lower() in ("другое", "другой", "…"):
                    tek["drugoe"] = True
                else:
                    tek["varianty"].append(znachenie)
        elif s == "*":
            if tek:
                tek["obyazatelnyj"] = True
        elif s == "~":
            if tek:
                tek["korotkij"] = True
        elif not punkty and not tek and not opisanie:
            opisanie = s

    zakryt()
    return {"zagolovok": zagolovok, "opisanie": opisanie, "punkty": punkty}


# ── сборка запросов к форме ──────────────────────────────────────────────────

def zaprosy(anketa: dict) -> list[dict]:
    out = []
    if anketa["opisanie"]:
        out.append({"updateFormInfo": {
            "info": {"description": anketa["opisanie"]},
            "updateMask": "description",
        }})

    # первый раздел живёт на титульной странице рядом с описанием формы: отдельная
    # страница с одним заголовком выглядит как пустой экран и злит заполняющего
    punkty = anketa["punkty"]
    if punkty and punkty[0]["vid"] == "razdel":
        punkty = punkty[1:]

    for i, p in enumerate(punkty):
        if p["vid"] == "razdel":
            # дальше каждый раздел - своя страница: длинная анкета не пугает полотном
            punkt = {"title": p["titul"], "pageBreakItem": {}}
            if p["podskazka"]:
                punkt["description"] = p["podskazka"]
        else:
            if p["varianty"] or p["drugoe"]:
                vybor = {
                    "type": "CHECKBOX" if p["neskolko"] else "RADIO",
                    "options": [{"value": v} for v in p["varianty"]],
                }
                if p["drugoe"]:
                    vybor["options"].append({"isOther": True})
                vopros = {"required": p["obyazatelnyj"], "choiceQuestion": vybor}
            else:
                vopros = {"required": p["obyazatelnyj"],
                          "textQuestion": {"paragraph": not p["korotkij"]}}
            punkt = {"title": p["titul"], "questionItem": {"question": vopros}}
            if p["podskazka"]:
                punkt["description"] = p["podskazka"]

        out.append({"createItem": {"item": punkt, "location": {"index": i}}})
    return out


def pochistit(k, form_id: str) -> None:
    """Убирает то, что в форме уже есть, чтобы повторный запуск не плодил дубли."""
    forma = k["forms"].forms().get(formId=form_id).execute()
    bylo = forma.get("items", [])
    if not bylo:
        return
    k["forms"].forms().batchUpdate(formId=form_id, body={
        "requests": [{"deleteItem": {"location": {"index": i}}} for i in range(len(bylo) - 1, -1, -1)]
    }).execute()


def napolnit(k, form_id: str, anketa: dict) -> None:
    pochistit(k, form_id)
    zapr = zaprosy(anketa)
    if anketa["zagolovok"]:
        zapr.insert(0, {"updateFormInfo": {
            "info": {"title": anketa["zagolovok"]}, "updateMask": "title",
        }})
    k["forms"].forms().batchUpdate(formId=form_id, body={"requests": zapr}).execute()


def sozdat_pustuyu(k, titul: str) -> str:
    """
    Пустая форма. Заводим её Диском - в папке офиса на Диске владелицы (подпапка
    «анкеты»), а наполняем уже Формами: так форма лежит там же, где остальное.
    """
    telo = {
        "name": titul,
        "mimeType": "application/vnd.google-apps.form",
        "parents": [gdisk.papka(k, "анкеты")],
    }
    try:
        return k["drive"].files().create(body=telo, fields="id").execute()["id"]
    except HttpError as e:
        if e.status_code in (403, 404) and "forms.googleapis.com" in str(e):
            sys.exit(
                "Google Forms API ещё не включён в облачном проекте.\n"
                "Включается один раз, за минуту:\n"
                "  console.cloud.google.com/apis/library/forms.googleapis.com\n"
                "Выбери свой проект (тот, где создан OAuth-клиент офиса) и нажми «Включить»."
            )
        raise


def dat_dostup(k, file_id: str, pochta: str) -> None:
    try:
        k["drive"].permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "writer", "emailAddress": pochta},
            sendNotificationEmail=False,
        ).execute()
    except HttpError as e:
        print(f"  (доступ для {pochta} выдать не удалось: {e.reason})", file=sys.stderr)


# ── команды ──────────────────────────────────────────────────────────────────

def cmd_sozdat(args):
    k = klienty()
    anketa = razobrat(Path(args.iz_fajla).read_text(encoding="utf-8"))
    titul = args.imya or anketa["zagolovok"] or "Анкета"

    form_id = sozdat_pustuyu(k, titul)
    napolnit(k, form_id, anketa)
    dat_dostup(k, form_id, args.pochta)

    gotovo = k["forms"].forms().get(formId=form_id).execute()
    print(f"Форма готова: {titul}")
    print(f"  заполнять:    {gotovo.get('responderUri', '')}")
    print(f"  редактировать: https://docs.google.com/forms/d/{form_id}/edit")
    print(f"  вопросов:     {len(gotovo.get('items', []))}")


def cmd_napolnit(args):
    k = klienty()
    anketa = razobrat(Path(args.iz_fajla).read_text(encoding="utf-8"))
    napolnit(k, args.form_id, anketa)
    gotovo = k["forms"].forms().get(formId=args.form_id).execute()
    print(f"Наполнено. Вопросов: {len(gotovo.get('items', []))}")
    print(f"  заполнять: {gotovo.get('responderUri', '')}")


def main():
    p = argparse.ArgumentParser(description="Гугл-формы руками офиса")
    pod = p.add_subparsers(dest="cmd", required=True)

    s = pod.add_parser("sozdat", help="создать новую форму и наполнить")
    s.add_argument("imya", nargs="?", default="")
    s.add_argument("--iz-fajla", required=True, dest="iz_fajla")
    s.add_argument("--pochta", default=POCHTA_VLADELCA)
    s.set_defaults(func=cmd_sozdat)

    n = pod.add_parser("napolnit", help="наполнить существующую форму")
    n.add_argument("form_id")
    n.add_argument("--iz-fajla", required=True, dest="iz_fajla")
    n.set_defaults(func=cmd_napolnit)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
