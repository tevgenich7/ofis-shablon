#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Расшифровка аудио и видео через Deepgram (speech-to-text).

Единственный канал транскрибации в офисе. Всё, что нужно перевести из звука в текст,
идёт сюда: голосовые, созвоны, кружки, видео, аудиозаметки.

Использование:
    python3 scripts/transcribe.py <файл-или-URL> [опции]

Опции:
    --lang ru|en|multi|auto   язык (по умолчанию ru; multi = многоязычная модель;
                              auto = определить автоматически)
    --model nova-3            модель Deepgram (по умолчанию nova-3)
    --speakers                разделить по говорящим (диаризация: «Спикер 1: …»)
    --out <путь.md>           куда сохранить (по умолчанию knowledge/raw/transcripts/)
    --json                    сохранить рядом сырой ответ Deepgram (.json)
    --no-compress             не пережимать через ffmpeg, слать файл как есть
    --print                   напечатать всю расшифровку в консоль

Ключ: переменная окружения DEEPGRAM_API_KEY или строка DEEPGRAM_API_KEY=... в .env
в корне офиса. Ключ нигде не печатается и не пишется в расшифровку.

Безопасность: скрипт умеет ходить только на api.deepgram.com и отправляет туда
ровно один файл - тот, что назван в аргументе. Другого адреса в нём нет.
"""

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Единственный адрес, куда скрипт умеет ходить.
API_HOST = "api.deepgram.com"
API_URL = f"https://{API_HOST}/v1/listen"

# Тариф pay-as-you-go, deepgram.com/pricing на 18.08.2026 - для оценки стоимости.
PRICE_PER_MIN = {"mono": 0.0077, "multi": 0.0092}

OFFICE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = OFFICE_ROOT / "knowledge" / "raw" / "transcripts"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".aac", ".flac", ".wma", ".amr"}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def die(msg, hint=None):
    print(f"\n[транскрибация] не вышло: {msg}", file=sys.stderr)
    if hint:
        print(f"[что делать] {hint}", file=sys.stderr)
    sys.exit(1)


def read_api_key():
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if key:
        return key
    env_file = OFFICE_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "DEEPGRAM_API_KEY":
                return value.strip().strip("'\"")
    die(
        "не найден ключ Deepgram",
        "положи ключ в файл .env в корне офиса строкой:\n"
        "  DEEPGRAM_API_KEY=твой_ключ\n"
        "Ключ берётся тут: https://console.deepgram.com → Settings → API Keys → Create a New API Key",
    )


def slugify(name):
    name = name.lower()
    out = []
    for ch in name:
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or "zapis"


def human_time(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def compress_to_opus(src_path):
    """Видео и тяжёлое аудио пережимаем в моно-opus 16 кГц: меньше вес, та же цена
    (Deepgram считает по длительности), быстрее загрузка. Не вышло - шлём оригинал."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="dg-")) / "audio.ogg"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "24k",
        str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        print(f"[ffmpeg] пережать не вышло ({stderr.decode(errors='ignore')[:200].strip()}), "
              f"шлю файл как есть", file=sys.stderr)
        return None
    if not tmp.exists() or tmp.stat().st_size == 0:
        return None
    return tmp


def build_url(args):
    params = {
        "model": args.model,
        "smart_format": "true",
        "punctuate": "true",
        "paragraphs": "true",
    }
    if args.lang == "auto":
        params["detect_language"] = "true"
    else:
        params["language"] = args.lang
    if args.speakers:
        params["diarize"] = "true"
        params["utterances"] = "true"
    return API_URL + "?" + urllib.parse.urlencode(params)


def call_deepgram(url, api_key, body, content_type):
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Token {api_key}")
    req.add_header("Content-Type", content_type)
    if urllib.parse.urlparse(url).hostname != API_HOST:
        die("адрес запроса не Deepgram - отправка остановлена")
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        if exc.code in (401, 403):
            die(f"Deepgram не принял ключ ({exc.code})",
                "проверь DEEPGRAM_API_KEY в .env - ключ должен быть от проекта в console.deepgram.com")
        if exc.code == 402:
            die("на счету Deepgram кончились деньги (402)",
                "пополни баланс в console.deepgram.com → Billing")
        if exc.code == 413:
            die("файл слишком большой для Deepgram (лимит 2 ГБ)",
                "перезапусти без --no-compress, чтобы файл пережался в opus")
        die(f"Deepgram ответил ошибкой {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        die(f"не достучался до Deepgram: {exc.reason}", "проверь интернет и попробуй ещё раз")


def extract_text(data, speakers):
    alt = (
        data.get("results", {})
        .get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
    )

    if speakers:
        utterances = data.get("results", {}).get("utterances") or []
        if utterances:
            lines, current, buf = [], None, []
            for utt in utterances:
                who = utt.get("speaker", 0)
                if who != current:
                    if buf:
                        lines.append(" ".join(buf))
                    current = who
                    buf = [f"**Спикер {who + 1}** ({human_time(utt.get('start', 0))}): "
                           f"{utt.get('transcript', '').strip()}"]
                else:
                    buf.append(utt.get("transcript", "").strip())
            if buf:
                lines.append(" ".join(buf))
            return "\n\n".join(lines)

    paragraphs = (alt.get("paragraphs") or {}).get("paragraphs") or []
    if paragraphs:
        chunks = []
        for para in paragraphs:
            sentences = [s.get("text", "").strip() for s in para.get("sentences", [])]
            text = " ".join(x for x in sentences if x)
            if text:
                chunks.append(text)
        if chunks:
            return "\n\n".join(chunks)

    return alt.get("transcript", "").strip()


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("source", help="путь к файлу или прямая ссылка на аудио/видео")
    parser.add_argument("--lang", default="ru", help="ru | en | multi | auto (по умолчанию ru)")
    parser.add_argument("--model", default="nova-3", help="модель Deepgram (по умолчанию nova-3)")
    parser.add_argument("--speakers", action="store_true", help="разделить по говорящим")
    parser.add_argument("--out", default=None, help="путь к файлу расшифровки")
    parser.add_argument("--json", action="store_true", dest="save_json",
                        help="сохранить сырой ответ Deepgram")
    parser.add_argument("--no-compress", action="store_true", help="не пережимать через ffmpeg")
    parser.add_argument("--print", action="store_true", dest="print_all",
                        help="напечатать всю расшифровку")
    args = parser.parse_args()

    api_key = read_api_key()
    url = build_url(args)
    is_remote = args.source.startswith(("http://", "https://"))

    if is_remote:
        source_label = args.source
        base_name = Path(urllib.parse.urlparse(args.source).path).stem or "zapis"
        body = json.dumps({"url": args.source}).encode("utf-8")
        content_type = "application/json"
        sent_bytes = None
    else:
        src = Path(args.source).expanduser().resolve()
        if not src.exists():
            die(f"файла нет: {src}")
        ext = src.suffix.lower()
        if ext not in VIDEO_EXT | AUDIO_EXT:
            print(f"[внимание] расширение {ext or '(нет)'} не похоже на аудио или видео - "
                  f"пробую всё равно", file=sys.stderr)
        source_label = str(src)
        base_name = src.stem

        upload = None if args.no_compress else compress_to_opus(src)
        payload_path = upload or src
        content_type = ("audio/ogg" if upload
                        else mimetypes.guess_type(str(src))[0] or "application/octet-stream")
        body = payload_path.read_bytes()
        sent_bytes = len(body)
        size_note = f"{sent_bytes / 1024 / 1024:.1f} МБ"
        if upload:
            size_note += f" (пережато из {src.stat().st_size / 1024 / 1024:.1f} МБ)"
        print(f"[отправляю в Deepgram] {src.name} → {size_note}")

    data = call_deepgram(url, api_key, body, content_type)

    text = extract_text(data, args.speakers)
    if not text:
        die("Deepgram вернул пустую расшифровку",
            "проверь, что в файле есть речь; для другого языка добавь --lang en или --lang auto")

    meta = data.get("metadata", {})
    duration = float(meta.get("duration", 0) or 0)
    model_name = ", ".join(
        info.get("name", "?") for info in (meta.get("model_info") or {}).values()
    ) or args.model
    rate = PRICE_PER_MIN["multi"] if args.lang == "multi" else PRICE_PER_MIN["mono"]
    cost = duration / 60 * rate

    detected = (
        data.get("results", {}).get("channels", [{}])[0].get("detected_language")
        if args.lang == "auto" else None
    )

    stamp = datetime.now()
    if args.out:
        out_path = Path(args.out).expanduser()
    else:
        out_path = DEFAULT_OUT_DIR / f"{slugify(base_name)}-{stamp:%Y-%m-%d}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        f"# Расшифровка: {base_name}",
        "",
        f"- источник: `{source_label}`",
        f"- длительность: {human_time(duration)}",
        f"- модель: {model_name} · язык: {detected or args.lang}"
        + (" · по говорящим" if args.speakers else ""),
        f"- расшифровано: {stamp:%d.%m.%Y %H:%M}",
        f"- стоимость: ~${cost:.3f} (оценка по тарифу pay-as-you-go на 18.08.2026)",
        "",
        "---",
        "",
    ]
    out_path.write_text("\n".join(header) + text + "\n", encoding="utf-8")

    if args.save_json:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[сырой ответ] {json_path}")

    print(f"[готово] {out_path}")
    print(f"[итого] {human_time(duration)} звука · {len(text)} знаков · ~${cost:.3f}")
    print()
    print(text if args.print_all else (text[:600] + ("…" if len(text) > 600 else "")))


if __name__ == "__main__":
    main()
