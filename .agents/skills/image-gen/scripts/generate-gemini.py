#!/usr/bin/env python3
"""Генерация картинок через Gemini API (AI Studio) - Nano Banana.

Написано 05.08.2026: в паке обёртки под AI Studio не было, только
Vertex (другая авторизация - GCP-проект + gcloud) и OpenAI-совместимая.

Модели и цена за картинку (официальная страница Google, сверено 31.07.2026):
  nano2      gemini-3.1-flash-image        $0.067 за 1K   ← дефолт
  nano2-lite gemini-3.1-flash-lite-image   $0.034 за 1K
  pro        gemini-3-pro-image            $0.134 за 1K/2K, $0.24 за 4K
  nano1      gemini-2.5-flash-image        $0.039
Бесплатного тарифа у image-моделей НЕТ - нужен включённый биллинг.

Ключ: переменная окружения GEMINI_API_KEY (или GOOGLE_API_KEY), иначе строка
      GEMINI_API_KEY=... в файле .env в корне офиса. Рядом со скриптом .env не держим.

Запуск:
    python3 generate-gemini.py -p "промт" -o ./img.png -a 16:9
    python3 generate-gemini.py -p "промт" -e pro -a 9:16 -o ./hero.png

Замечание про API: Google отдаёт генерацию через новый эндпоинт /v1beta/interactions;
классический /v1beta/models/{model}:generateContent тоже жив. Скрипт пробует первый,
при 404/400 переключается на второй и сообщает, какой сработал (поле "endpoint" в
ответе). Ошибки печатаются телом целиком - если формат где-то разойдётся, будет видно
точно, а не «что-то не так».
"""
import argparse
import base64
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def ca_context():
    """macOS-питон часто не видит хранилище сертификатов → SSL: CERTIFICATE_VERIFY_FAILED.
    Берём certifi, если он есть, иначе системный бандл macOS."""
    for candidate in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
        if candidate and os.path.exists(candidate):
            return ssl.create_default_context(cafile=candidate)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = ca_context()

API_ROOT = os.environ.get("GEMINI_API_ROOT", "https://generativelanguage.googleapis.com/v1beta")

ENGINES = {
    "nano2": "gemini-3.1-flash-image",
    "nano2-lite": "gemini-3.1-flash-lite-image",
    "pro": "gemini-3-pro-image",
    "nano1": "gemini-2.5-flash-image",
}
DEFAULT_ENGINE = os.environ.get("GEMINI_IMAGE_ENGINE", "nano2")

ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]


# скрипт лежит в <офис>/.agents/skills/image-gen/scripts/, корень офиса - на четыре папки выше
OFFICE = Path(__file__).resolve().parents[4]


def load_api_key():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip()
    env_path = OFFICE / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        for name in ("GEMINI_API_KEY=", "GOOGLE_API_KEY="):
            if line.startswith(name):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return None


def chasti_s_foto(fayly):
    """Картинки на вход (режим правки кадра): nano banana принимает их inline_data
    перед текстом промта - тем же способом, что и foto-sessiya.py."""
    chasti = []
    for f in fayly or []:
        tip = mimetypes.guess_type(f)[0] or "image/jpeg"
        with open(f, "rb") as fh:
            chasti.append({"inline_data": {"mime_type": tip,
                                           "data": base64.b64encode(fh.read()).decode()}})
    return chasti


def post(url, payload, key):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def dig_image(obj):
    """Достаёт base64 картинки из ответа любой из двух схем - рекурсивно, по ключам."""
    if isinstance(obj, dict):
        for k in ("data", "b64_json", "bytesBase64Encoded"):
            v = obj.get(k)
            if isinstance(v, str) and len(v) > 512:
                return v
        inline = obj.get("inlineData") or obj.get("inline_data")
        if isinstance(inline, dict) and isinstance(inline.get("data"), str):
            return inline["data"]
        for v in obj.values():
            found = dig_image(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = dig_image(v)
            if found:
                return found
    return None


def generate(prompt, output, aspect, engine, size=None, images=None):
    key = load_api_key()
    if not key:
        return {"success": False, "error": "Пропуск к Gemini не подключён: нет строки GEMINI_API_KEY в файле .env "
                                           "в корне офиса. Как получить - team/agents/tehnar/vneshnie-servisy.md, раздел «Картинки»"}

    model = ENGINES.get(engine)
    if not model:
        return {"success": False, "error": f"неизвестный движок {engine}; доступны: {', '.join(ENGINES)}"}

    # Порядок проверен на живом API 05.08.2026: generateContent принимает imageConfig
    # (дошло до квоты, т.е. тело валидно). У interactions параметра image_config НЕТ -
    # он отвечает 400 «Unknown parameter», поэтому там пропорция уходит в текст промта.
    attempts = [
        (
            "generateContent",
            f"{API_ROOT}/models/{model}:generateContent",
            {
                "contents": [{"parts": chasti_s_foto(images) + [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    # imageSize 1K/2K/4K понимает только pro (gemini-3-pro-image); добавлено 11.09.2026
                    "imageConfig": {"aspectRatio": aspect, **({"imageSize": size} if size else {})},
                },
            },
        ),
        (
            "interactions",
            f"{API_ROOT}/interactions",
            {
                "model": model,
                "input": [{"type": "text", "text": f"{prompt}\n\nAspect ratio: {aspect}."}],
            },
        ),
    ]

    # У /interactions картинок на вход нет - в режиме правки кадра туда не идём,
    # иначе модель молча нарисует новое изображение вместо правки.
    if images:
        attempts = [a for a in attempts if a[0] == "generateContent"]

    errors = []
    for name, url, payload in attempts:
        try:
            data = post(url, payload, key)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            errors.append({"endpoint": name, "http": e.code, "body": body[:900]})
            continue
        except Exception as e:
            errors.append({"endpoint": name, "error": str(e)})
            continue

        b64 = dig_image(data)
        if not b64:
            errors.append({"endpoint": name, "error": "картинки в ответе нет", "body": json.dumps(data)[:900]})
            continue

        img = base64.b64decode(b64)
        out_dir = os.path.dirname(os.path.abspath(output))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output, "wb") as f:
            f.write(img)

        return {
            "success": True,
            "filePath": os.path.abspath(output),
            "provider": "gemini-aistudio",
            "endpoint": name,
            "engine": engine,
            "model": model,
            "aspect": aspect,
            "bytes": len(img),
        }

    return {"success": False, "error": "оба эндпоинта не отдали картинку", "attempts": errors}


def main():
    p = argparse.ArgumentParser(description="Генерация картинки через Gemini API (Nano Banana)")
    p.add_argument("--prompt", "-p", required=True)
    p.add_argument("--output", "-o", default=f"./gen-gemini-{int(time.time())}.png")
    p.add_argument("--aspect-ratio", "-a", default="1:1", choices=ASPECTS)
    p.add_argument("--engine", "-e", default=DEFAULT_ENGINE, choices=list(ENGINES),
                   help=f"движок (дефолт {DEFAULT_ENGINE}); pro = Nano Banana Pro")
    p.add_argument("--image", "-i", action="append",
                   help="картинка на вход (режим правки кадра); можно несколько - "
                        "первая обычно исходный кадр, дальше референсы")
    p.add_argument("--size", "-s", default=None, choices=["1K", "2K", "4K"],
                   help="размер выхода, только для -e pro (4K = $0.24 за картинку)")
    a = p.parse_args()

    result = generate(a.prompt, a.output, a.aspect_ratio, a.engine, a.size, a.image)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
