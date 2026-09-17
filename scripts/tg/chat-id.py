#!/usr/bin/env python3
"""Показывает chat_id тех, кто писал боту (нужно один раз, чтобы вписать в .env).

    python3 scripts/tg/chat-id.py

Если пусто - напиши боту любое сообщение в личку и запусти снова.
Токен берётся из .env в корне офиса (TELEGRAM_BOT_TOKEN или BOT_TOKEN), значение не печатается.
"""
import json
import sys
from pathlib import Path
from urllib import error, request

KORNI = Path(__file__).resolve().parents[2]


def dostat_token() -> str:
    put = KORNI / ".env"
    if not put.exists():
        sys.exit("нет файла .env в корне офиса: сначала положи туда строку TELEGRAM_BOT_TOKEN=...")
    slovar = {}
    for stroka in put.read_text(encoding="utf-8").splitlines():
        stroka = stroka.strip()
        if stroka and not stroka.startswith("#") and "=" in stroka:
            klyuch, znachenie = stroka.split("=", 1)
            slovar[klyuch.strip().lower()] = znachenie.strip().strip('"').strip("'")
    for imya in ("telegram_bot_token", "bot_token"):
        if slovar.get(imya):
            print(f"токен взят из {imya.upper()}")
            return slovar[imya]
    sys.exit("в .env нет строки TELEGRAM_BOT_TOKEN (или BOT_TOKEN)")


def sprosit(token: str, metod: str) -> dict:
    """Один запрос к телеграму. Нет сети - человеческое сообщение вместо трейсбека."""
    try:
        with request.urlopen(f"https://api.telegram.org/bot{token}/{metod}", timeout=30) as otvet:
            return json.loads(otvet.read())
    except error.HTTPError as e:
        if e.code in (401, 404):
            sys.exit("телеграм не принял токен бота: проверь строку TELEGRAM_BOT_TOKEN в .env")
        sys.exit(f"телеграм ответил ошибкой {e.code} на {metod}")
    except (error.URLError, TimeoutError, OSError):
        sys.exit("не могу достучаться до телеграма, проверь интернет")


def main() -> None:
    token = dostat_token()
    me = sprosit(token, "getMe").get("result", {})
    print(f"бот: @{me.get('username')} ({me.get('first_name')})")

    hook = sprosit(token, "getWebhookInfo").get("result", {})
    if hook.get("url"):
        print(f"ВНИМАНИЕ: у бота стоит вебхук {hook['url']} - "
              "апдейты уходят туда, getUpdates будет пустым (вебхук не трогаю)")

    otchet = sprosit(token, "getUpdates")
    if not otchet.get("ok"):
        sys.exit(f"телеграм ответил: {otchet}")

    nayden = {}
    for obnovlenie in otchet.get("result", []):
        soobshchenie = (
            obnovlenie.get("message")
            or obnovlenie.get("edited_message")
            or obnovlenie.get("channel_post")
            or {}
        )
        chat = soobshchenie.get("chat")
        if chat:
            nayden[chat["id"]] = chat
    if not nayden:
        sys.exit("боту никто не писал (или апдейты уже съедены вебхуком/поллингом) - "
                 "напиши ему в личку любое сообщение и запусти снова")
    for chat_id, chat in nayden.items():
        imya = " ".join(
            filter(None, [chat.get("first_name"), chat.get("last_name")])
        ) or chat.get("title", "")
        print(f"ADMIN_CHAT_ID={chat_id}   # {chat.get('type')} {imya} @{chat.get('username', '')}")


if __name__ == "__main__":
    main()
