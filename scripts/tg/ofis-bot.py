#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Телеграм-бот офиса: связь владелицы с офисом с телефона. Один файл, без сторонних библиотек.

Что умеет:
  - текст   → отдаёт офису как задачу, ответ присылает обратно;
  - голосовое → расшифровывает через Deepgram (scripts/transcribe.py), отдаёт офису
                как правку или задачу: «(голосовое) …»;
  - видео / файлы / фото → кладёт в inbox/ (дубли, скриншоты статистики); подпись к файлу
                уходит офису как задача;
  - всё новое, что офис положил в results/ за время ответа, присылает обратно: ролики
    как видео, картинки как фото, тексты файлом.

Разговор держится (офис помнит контекст) через id сессии в scripts/tg/sostoyanie.json.
Команды: /zanovo - начать разговор заново, /start - что умею.

Запуск:
    python3 scripts/tg/ofis-bot.py             # работает, пока не нажмёшь Ctrl+C
    python3 scripts/tg/ofis-bot.py --proverka  # проверить токен и агентскую программу

Настройки - в .env в корне офиса (значения нигде не печатаются):
    токен бота      TELEGRAM_BOT_TOKEN (или BOT_TOKEN)
    чат владелицы   ADMIN_CHAT_ID (нет - бот привяжется к первому, кто ему напишет,
                    и запомнит в sostoyanie.json; остальным отвечает «бот только для владелицы»)
    агент           OFFICE_AGENT=claude | codex (нет - берёт ту программу, что стоит)

Безопасность: скрипт ходит только на api.telegram.org; расшифровка идёт через
scripts/transcribe.py (api.deepgram.com). Другого адреса в нём нет. Чужие сообщения
не исполняются. Токен не логируется.
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ZDES = Path(__file__).resolve().parent
KOREN = ZDES.parents[1]
INBOX = KOREN / "inbox"
RESULTS = KOREN / "results"
SOSTOYANIE = ZDES / "sostoyanie.json"
TRANSCRIBE = KOREN / "scripts" / "transcribe.py"

# ── настройки ────────────────────────────────────────────────────────────────

def env_slovar() -> dict:
    slovar = dict(os.environ)
    put = KOREN / ".env"
    if put.exists():
        for stroka in put.read_text(encoding="utf-8", errors="replace").splitlines():
            stroka = stroka.strip()
            if not stroka or stroka.startswith("#") or "=" not in stroka:
                continue
            imya, _, znachenie = stroka.partition("=")
            slovar.setdefault(imya.strip(), znachenie.strip().strip("'\""))
    return slovar


def dostat(slovar: dict, imena, obyazatelno=True) -> str:
    nizhnie = {k.lower(): v for k, v in slovar.items() if v}
    for imya in imena:
        if imya.lower() in nizhnie:
            return nizhnie[imya.lower()]
    if obyazatelno:
        sys.exit(f"в .env нет ни одного из: {', '.join(imena)}")
    return ""


def ssl_ctx():
    for kandidat in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
        if kandidat and os.path.exists(kandidat):
            return ssl.create_default_context(cafile=kandidat)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = ssl_ctx()


def sostoyanie() -> dict:
    try:
        return json.loads(SOSTOYANIE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def zapisat_sostoyanie(d: dict):
    SOSTOYANIE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# ── телеграм ─────────────────────────────────────────────────────────────────

def tg(token: str, metod: str, polya: dict | None = None, timeout: int = 60):
    url = f"https://api.telegram.org/bot{token}/{metod}"
    dannye = json.dumps(polya or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=dannye, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as otvet:
        otchet = json.loads(otvet.read().decode("utf-8"))
    if not otchet.get("ok"):
        raise RuntimeError(f"telegram {metod}: {otchet.get('description')}")
    return otchet["result"]


def tg_fajl(token: str, metod: str, polya: dict, pole: str, put: Path, timeout: int = 300):
    """POST multipart: отправить файл (видео, фото, документ)."""
    granica = "----ofis" + uuid.uuid4().hex
    telo = bytearray()
    for k, v in polya.items():
        telo += f"--{granica}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    mime = mimetypes.guess_type(str(put))[0] or "application/octet-stream"
    telo += (f"--{granica}\r\nContent-Disposition: form-data; name=\"{pole}\"; "
             f"filename=\"{put.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8")
    telo += put.read_bytes()
    telo += f"\r\n--{granica}--\r\n".encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{metod}", data=bytes(telo),
                                 headers={"Content-Type": f"multipart/form-data; boundary={granica}"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as otvet:
        otchet = json.loads(otvet.read().decode("utf-8"))
    if not otchet.get("ok"):
        raise RuntimeError(f"telegram {metod}: {otchet.get('description')}")
    return otchet["result"]


def opisat_oshibku_telegrama(e: Exception) -> str:
    """Короткая причина для журнала; пропуск и текст запроса сюда не попадают."""
    if isinstance(e, urllib.error.HTTPError):
        znachenie = {
            401: "пропуск бота неверный",
            409: "бот запущен дважды",
        }.get(e.code, "Telegram отклонил запрос")
        return f"HTTP {e.code}: {znachenie}"
    return type(e).__name__


def skachat(token: str, file_id: str, kuda: Path) -> Path:
    info = tg(token, "getFile", {"file_id": file_id})
    url = f"https://api.telegram.org/file/bot{token}/{info['file_path']}"
    kuda.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=600, context=SSL_CTX) as r, open(kuda, "wb") as f:
        shutil.copyfileobj(r, f)
    return kuda


def narezat(tekst: str, limit: int = 3900) -> list[str]:
    tekst = (tekst or "").strip() or "(пусто)"
    kuski, tek = [], ""
    for abzac in tekst.split("\n"):
        if len(tek) + len(abzac) + 1 > limit:
            kuski.append(tek)
            tek = ""
        tek += abzac + "\n"
    if tek.strip():
        kuski.append(tek)
    return kuski


def otpravit(token: str, chat_id, tekst: str):
    for kusok in narezat(tekst):
        tg(token, "sendMessage", {"chat_id": chat_id, "text": kusok, "disable_web_page_preview": True})


class Pechataet:
    """Пока офис думает, телеграм показывает «печатает…»."""

    def __init__(self, token, chat_id):
        self.token, self.chat_id, self.stop = token, chat_id, threading.Event()

    def __enter__(self):
        def krutit():
            while not self.stop.is_set():
                try:
                    tg(self.token, "sendChatAction", {"chat_id": self.chat_id, "action": "typing"}, timeout=10)
                except Exception:
                    pass
                self.stop.wait(4)
        threading.Thread(target=krutit, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.stop.set()


# ── агентская программа ──────────────────────────────────────────────────────

def najti_agenta(env: dict):
    hochu = (env.get("OFFICE_AGENT") or "").lower()
    poryadok = ["codex", "claude"] if hochu == "codex" else ["claude", "codex"]
    for vid in poryadok:
        kandidaty = [f"/opt/homebrew/bin/{vid}", f"/usr/local/bin/{vid}",
                     str(Path.home() / ".local/bin" / vid), shutil.which(vid) or ""]
        if vid == "codex":
            kandidaty.append("/Applications/ChatGPT.app/Contents/Resources/codex")  # codex внутри приложения ChatGPT
        for kandidat in kandidaty:
            if kandidat and os.path.exists(kandidat):
                return vid, kandidat
    return None, None


def sprosit_ofis(vid: str, bin_: str, tekst: str, sessiya: str | None) -> tuple[str, str | None]:
    """Отдаёт задачу офису, возвращает (ответ, id сессии)."""
    if vid == "claude":
        argv = [bin_, "-p", tekst, "--output-format", "json", "--permission-mode", "acceptEdits"]
        if sessiya:
            argv += ["--resume", sessiya]
        p = subprocess.run(argv, cwd=KOREN, capture_output=True, text=True, timeout=1500)
        try:
            d = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            return (p.stdout.strip() or p.stderr.strip() or "офис не ответил")[-3000:], sessiya
        return d.get("result") or "(офис ответил пусто)", d.get("session_id") or sessiya

    # codex: задача в stdin, события JSONL на выходе
    argv = [bin_, "exec", "--json", "--skip-git-repo-check",
            "-s", "workspace-write", "-c", 'approval_policy="never"', "-C", str(KOREN)]
    if sessiya:
        argv += ["resume", sessiya]
    p = subprocess.run(argv, cwd=KOREN, input=tekst, capture_output=True, text=True, timeout=1500)
    otvet, novaya = "", sessiya
    for stroka in p.stdout.splitlines():
        try:
            s = json.loads(stroka)
        except Exception:
            continue
        if s.get("type") == "thread.started":
            novaya = s.get("thread_id") or novaya
        it = s.get("item") or {}
        if s.get("type") == "item.completed" and it.get("type") == "agent_message" and it.get("text"):
            otvet = it["text"]
    return otvet or (p.stderr.strip()[-2000:] or "офис не ответил"), novaya


# ── что офис положил в results/ за время ответа ──────────────────────────────

def snimok_results() -> dict:
    return {str(p): p.stat().st_mtime for p in RESULTS.rglob("*") if p.is_file() and not p.name.startswith(".")}


def novoe(do: dict) -> list[Path]:
    posle = snimok_results()
    return [Path(p) for p, t in posle.items() if p not in do or t > do[p]]


def otdat_fajly(token, chat_id, fajly: list[Path]):
    for f in sorted(fajly):
        razmer = f.stat().st_size
        try:
            if razmer > 49 * 1024 * 1024:
                otpravit(token, chat_id, f"готово, но файл больше 50 МБ, телеграм его не примет: {f.relative_to(KOREN)}")
            elif f.suffix.lower() in (".mp4", ".mov"):
                tg_fajl(token, "sendVideo", {"chat_id": str(chat_id), "caption": f.name, "supports_streaming": "true"}, "video", f)
            elif f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                tg_fajl(token, "sendPhoto", {"chat_id": str(chat_id), "caption": f.name}, "photo", f)
            else:
                tg_fajl(token, "sendDocument", {"chat_id": str(chat_id), "caption": f.name}, "document", f)
        except Exception as e:  # noqa: BLE001
            otpravit(token, chat_id, f"не смог отправить {f.name}: {e}")


# ── расшифровка голосового ───────────────────────────────────────────────────

def rasshifrovat(put: Path) -> str:
    out = put.with_suffix(".md")
    p = subprocess.run([sys.executable, str(TRANSCRIBE), str(put), "--out", str(out)],
                       cwd=KOREN, capture_output=True, text=True, timeout=600)
    if not out.exists():
        raise RuntimeError((p.stderr or p.stdout).strip()[-800:] or "расшифровка не получилась")
    tekst = out.read_text(encoding="utf-8")
    if tekst.startswith("---"):
        chasti = tekst.split("---", 2)
        tekst = chasti[2] if len(chasti) == 3 else tekst
    return tekst.strip()


# ── обработка одного сообщения ───────────────────────────────────────────────

POMOSH = ("Я бот твоего офиса. Пиши текстом или голосовым, что нужно: сценарий, пост, правка "
          "к ролику. Кидай видео-дубли и скриншоты, я положу их в офис. Ответы и готовые ролики "
          "пришлю сюда. /zanovo - начать разговор заново.")


def obrabotat(token, agent, soobshchenie, sost: dict):
    chat_id = soobshchenie["chat"]["id"]
    tekst = (soobshchenie.get("text") or "").strip()
    podpis = (soobshchenie.get("caption") or "").strip()
    zadacha = None
    prinyato = []

    if tekst == "/start":
        otpravit(token, chat_id, POMOSH)
        return
    if tekst == "/zanovo":
        sost["sessiya"] = None
        zapisat_sostoyanie(sost)
        otpravit(token, chat_id, "Начинаем заново, прошлый разговор офис больше не держит в голове.")
        return

    shtamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    if soobshchenie.get("voice") or soobshchenie.get("audio"):
        v = soobshchenie.get("voice") or soobshchenie.get("audio")
        put = INBOX / "golosovye" / f"{shtamp}.ogg"
        with Pechataet(token, chat_id):
            skachat(token, v["file_id"], put)
            try:
                rasshifrovka = rasshifrovat(put)
            except Exception as e:  # noqa: BLE001
                otpravit(token, chat_id, f"Голосовое сохранил, но расшифровать не смог: {e}\n"
                                         "Скорее всего нет ключа расшифровки. Напиши текстом, пожалуйста.")
                return
        zadacha = f"(голосовое от владелицы, расшифровка) {rasshifrovka}"

    for vid, pole in (("video", "video"), ("video_note", "video_note"), ("document", "document"), ("photo", "photo")):
        if not soobshchenie.get(vid):
            continue
        obj = soobshchenie[vid]
        if vid == "photo":
            obj = obj[-1]  # самое крупное
        imya = obj.get("file_name") or f"{shtamp}.{ {'video': 'mp4', 'video_note': 'mp4', 'photo': 'jpg'}.get(vid, 'bin') }"
        put = INBOX / imya
        with Pechataet(token, chat_id):
            skachat(token, obj["file_id"], put)
        prinyato.append(put.relative_to(KOREN))

    if prinyato and not podpis and not zadacha:
        otpravit(token, chat_id, "Принял, положил в inbox: " + ", ".join(map(str, prinyato)) +
                 "\nНапиши, что с этим сделать (например: «это дубли, собери ролик по вчерашнему сценарию»).")
        return

    if podpis:
        zadacha = (zadacha + "\n" if zadacha else "") + podpis
    if prinyato:
        zadacha = (zadacha or "") + "\nФайлы только что легли в inbox: " + ", ".join(map(str, prinyato))
    if tekst:
        zadacha = tekst

    if not zadacha:
        otpravit(token, chat_id, "Не понял, что с этим делать. Напиши текстом или голосовым.")
        return

    vid, bin_ = agent
    do = snimok_results()
    with Pechataet(token, chat_id):
        try:
            otvet, sessiya = sprosit_ofis(vid, bin_, zadacha, sost.get("sessiya"))
        except subprocess.TimeoutExpired:
            otpravit(token, chat_id, "Офис думал дольше 25 минут и не ответил. Попробуй разбить задачу на части.")
            return
    sost["sessiya"] = sessiya
    zapisat_sostoyanie(sost)
    otpravit(token, chat_id, otvet)
    otdat_fajly(token, chat_id, novoe(do))


# ── главный цикл ─────────────────────────────────────────────────────────────

def glavnaya():
    env = env_slovar()
    token = dostat(env, ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"))
    sost = sostoyanie()
    vladelica = dostat(env, ("ADMIN_CHAT_ID",), obyazatelno=False) or sost.get("vladelica")
    agent = najti_agenta(env)
    if not agent[0]:
        sys.exit("не вижу ни claude, ни codex на этом компьютере: офису не через что думать")

    try:
        me = tg(token, "getMe")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"не могу достучаться до телеграма: {opisat_oshibku_telegrama(e)}")
    except RuntimeError as e:
        sys.exit(f"телеграм не принял токен бота: {e}. Проверь строку TELEGRAM_BOT_TOKEN в .env")
    print(f"[бот] @{me.get('username')} · агент: {agent[0]} · владелица: {'задана' if vladelica else 'первый, кто напишет'}")
    if "--proverka" in sys.argv:
        print("[бот] токен и агент в порядке")
        return

    offset = None
    while True:
        try:
            staroe = tg(token, "getUpdates", {"timeout": 0})
            break
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as e:
            print(f"[бот] Telegram: {opisat_oshibku_telegrama(e)}; повтор через 5 с")
            time.sleep(5)
    for u in staroe:
        offset = u["update_id"] + 1   # старое не перечитываем
    print("[бот] слушаю. Ctrl+C - остановить")
    while True:
        try:
            obnovleniya = tg(token, "getUpdates", {"timeout": 50, "offset": offset,
                                                    "allowed_updates": ["message"]}, timeout=70)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as e:
            print(f"[бот] Telegram: {opisat_oshibku_telegrama(e)}; повтор через 5 с")
            time.sleep(5)
            continue
        for u in obnovleniya:
            offset = u["update_id"] + 1
            m = u.get("message")
            if not m or m["chat"]["type"] != "private":
                continue
            chat_id = m["chat"]["id"]
            if not vladelica:
                vladelica = str(chat_id)
                sost["vladelica"] = vladelica
                zapisat_sostoyanie(sost)
                print(f"[бот] привязался к владелице (chat_id записан в {SOSTOYANIE.name})")
            if str(chat_id) != str(vladelica):
                try:
                    otpravit(token, chat_id, "Этот бот работает только для владелицы офиса.")
                except Exception:
                    pass
                continue
            try:
                obrabotat(token, agent, m, sost)
            except Exception as e:  # noqa: BLE001
                print(f"[бот] ошибка: {e}")
                try:
                    otpravit(token, chat_id, f"Что-то сломалось: {e}\nСкажи Технарю в офисе, он разберётся.")
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        glavnaya()
    except KeyboardInterrupt:
        print("\n[бот] остановлен")
