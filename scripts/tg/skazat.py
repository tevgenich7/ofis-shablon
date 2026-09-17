#!/usr/bin/env python3
"""
Короткое сообщение владелице в телеграм от офиса.

    python3 scripts/tg/skazat.py "текст"
    echo "текст" | python3 scripts/tg/skazat.py

Токен и адрес берутся из .env корня офиса (TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID).
Нет чего-то из двух - скрипт молча выходит с кодом 1: это не повод ронять вечерний
порядок, просто сообщение не уйдёт.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]


def iz_env(imena: tuple[str, ...]) -> str:
    for imya in imena:
        znach = os.environ.get(imya, "").strip()
        if znach:
            return znach
    fajl = KOREN / ".env"
    if fajl.exists():
        for stroka in fajl.read_text(encoding="utf-8", errors="ignore").splitlines():
            stroka = stroka.strip()
            if not stroka or stroka.startswith("#") or "=" not in stroka:
                continue
            imya, _, znach = stroka.partition("=")
            if imya.strip() in imena:
                znach = znach.strip().strip('"').strip("'")
                if znach:
                    return znach
    return ""


def main() -> int:
    text = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not text:
        return 1
    token = iz_env(("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"))
    chat = iz_env(("ADMIN_CHAT_ID", "CHAT_ID"))
    if not token or not chat:
        print("нет токена бота или адреса в .env - сообщение не отправлено", file=sys.stderr)
        return 1
    dannye = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=dannye)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return 0 if json.loads(r.read()).get("ok") else 1
    except Exception as e:
        print(f"телеграм не ответил: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
