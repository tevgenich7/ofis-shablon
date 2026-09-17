#!/usr/bin/env python3
"""ИИ-фотосессия: генерация фото С ЛИЦОМ КОНКРЕТНОГО ЧЕЛОВЕКА (Nano Banana).

Чем отличается от generate-gemini.py: тот генерит только по тексту. Здесь на
вход подаются ФОТО человека - модель берёт с них внешность (лицо, возраст,
телосложение) и переносит в описанную сцену. Это image-to-image по идентичности,
ровно то, что делают каналы с «фотосессиями по промту».

Модели и цена за картинку (сверено по докстрингу generate-gemini.py, 31.07.2026):
  nano2  gemini-3.1-flash-image  $0.067   ← дефолт, годится для проб
  pro    gemini-3-pro-image      $0.134   ← лучше держит лицо, брать на финал
Бесплатного тарифа у image-моделей нет. Ключ GEMINI_API_KEY берётся из окружения,
иначе из файла .env в корне офиса (рядом со скриптом .env не держим).

Один кадр:
    python3 foto-sessiya.py --refs папка_с_фото -p "промт" -o кадр.png -a 3:4

Серия из файла (JSON: [{"slug": "...", "aspect": "3:4", "prompt": "..."}, ...]):
    python3 foto-sessiya.py --refs папка_с_фото --seriya seriya.json --out-dir папка/

Скелет промта - в konstruktor_promta() ниже. Он не украшение: без блока про
идентичность модель рисует «похожего человека», а без блока против приукрашивания
делает всех стройнее и моложе, чем на исходных фото.
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

RASSHIRENIYA = (".jpg", ".jpeg", ".png", ".webp")
MAKS_REFOV = 8  # тело запроса пухнет, но сходство держится на количестве
                # пикселей лица: на шести кадрах по пояс модель начинала
                # досочинять черты (поймано 02.09.2026)


def ca_context():
    """macOS-питон часто не видит хранилище сертификатов → CERTIFICATE_VERIFY_FAILED."""
    for kandidat in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
        if kandidat and os.path.exists(kandidat):
            return ssl.create_default_context(cafile=kandidat)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = ca_context()
API_ROOT = os.environ.get("GEMINI_API_ROOT", "https://generativelanguage.googleapis.com/v1beta")

DVIZHKI = {
    "nano2": "gemini-3.1-flash-image",
    "nano2-lite": "gemini-3.1-flash-lite-image",
    "pro": "gemini-3-pro-image",
    "nano1": "gemini-2.5-flash-image",
}
PROPORCII = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]

# Две обязательные рамки вокруг любой сцены. Формулировки взяты из разбора
# работающих промтов (knowledge/raw/tg-kanaly/imagine_idea.md, снято 02.09.2026):
# первая держит внешность, вторая запрещает «улучшать» человека.
YAKOR_LICHNOSTI = (
    "Create one realistic photo of the person from the uploaded photos, placed into "
    "the photoshoot described below.\n\n"
    "Use the uploaded photos as the identity source for the person: real facial likeness, "
    "age impression, skin tone, hair, facial hair, visible body shape, body volume, "
    "proportions, and natural clothing fit. Do not copy the casual clothing, pose, "
    "lighting, or location from the uploaded photos.\n\n"
    "Adapt the described outfit, pose, and camera framing to the person's real visible "
    "build from the uploaded photos. Keep their natural proportions and weight "
    "distribution; do not make the person taller, more model-like, or more "
    "conventionally polished than the uploaded photos show."
)
FINAL = (
    "Render it as a realistic photo in the visual style described above, with natural skin "
    "texture, believable fabric, coherent light, and accurate hands. No text, no watermarks, "
    "no logos anywhere in the image."
)

# Второй проход. Генерация с нуля хорошо держит лицо только когда оно занимает
# большую часть кадра; в сцене с окружением модель отвлекается на обстановку и
# лицо уплывает (поймано 02.09.2026 на кадрах с кофейней и доской). Тогда сцену
# оставляем как есть и переклеиваем на неё настоящее лицо отдельным запросом.
PODMENA_LICA = (
    "The FIRST uploaded image is a finished photograph. All the following images show the "
    "real face of a specific person.\n\n"
    "Return the first photograph with only one change: the face and head must become the "
    "real person's face from the other images. Keep everything else pixel-for-pixel as it "
    "is - the pose, body, hands, clothing, background, framing, colour grading, depth of "
    "field and the direction and softness of the light.\n\n"
    "Match the head angle, gaze direction and lighting of the original photograph, but the "
    "facial identity must be unmistakably the person from the reference images: same face "
    "shape, jaw width, nose, brow line, eye shape and colour, hairline and stubble pattern. "
    "Do not slim the face, do not change his age, do not beautify him.\n\n"
    "Skin must be clean and even, free of pimples and spots, while keeping natural texture."
)


def konstruktor_promta(scena, profil=""):
    """Собирает полный промт из скелета. scena - либо готовая строка, либо dict
    с блоками сцены; в обоих случаях идентичность и финал приклеиваются сами.

    profil - постоянные требования к внешности конкретного человека (кожа,
    сложение, причёска). Живут отдельным файлом рядом с его фото и вставляются
    в КАЖДЫЙ кадр: иначе одно и то же приходится дописывать в каждую сцену
    руками, а забытая строка сразу видна на картинке."""
    if isinstance(scena, str):
        telo = scena.strip()
    else:
        poryadok = [
            ("scene", "Scene and environment"),
            ("camera", "Camera and crop"),
            ("pose", "Pose and body placement"),
            ("head", "Head, gaze, expression"),
            ("wardrobe", "Wardrobe"),
            ("props", "Props and object interaction"),
            ("constraints", "Pose reconstruction constraints"),
            ("light", "Lighting and color"),
            ("composition", "Composition and details"),
        ]
        chasti = [f"{zagolovok}:\n{scena[klyuch].strip()}"
                  for klyuch, zagolovok in poryadok if scena.get(klyuch)]
        telo = "\n\n".join(chasti)
    bloki = [YAKOR_LICHNOSTI]
    if profil.strip():
        bloki.append(profil.strip())
    bloki += [telo, FINAL]
    return "\n\n".join(bloki)


# скрипт лежит в <офис>/.agents/skills/image-gen/scripts/, корень офиса - на четыре папки выше
OFFICE = Path(__file__).resolve().parents[4]


def kluch():
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if k:
        return k.strip()
    try:
        stroki = (OFFICE / ".env").read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for stroka in stroki:
        stroka = stroka.strip()
        for imya in ("GEMINI_API_KEY=", "GOOGLE_API_KEY="):
            if stroka.startswith(imya):
                val = stroka.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return None


def sobrat_refy(puti):
    """Разворачивает папки в список файлов-картинок."""
    fayly = []
    for p in puti:
        if os.path.isdir(p):
            fayly += [os.path.join(p, f) for f in sorted(os.listdir(p))
                      if f.lower().endswith(RASSHIRENIYA)]
        elif os.path.isfile(p):
            fayly.append(p)
    return fayly[:MAKS_REFOV]


def chasti_s_foto(fayly):
    chasti = []
    for f in fayly:
        tip = mimetypes.guess_type(f)[0] or "image/jpeg"
        with open(f, "rb") as fh:
            chasti.append({"inline_data": {"mime_type": tip,
                                           "data": base64.b64encode(fh.read()).decode()}})
    return chasti


def dostat_kartinku(obj):
    """Достаёт base64 картинки из ответа - рекурсивно, схема ответа менялась."""
    if isinstance(obj, dict):
        inline = obj.get("inlineData") or obj.get("inline_data")
        if isinstance(inline, dict) and isinstance(inline.get("data"), str):
            return inline["data"]
        for k in ("data", "b64_json", "bytesBase64Encoded"):
            v = obj.get(k)
            if isinstance(v, str) and len(v) > 512:
                return v
        for v in obj.values():
            n = dostat_kartinku(v)
            if n:
                return n
    elif isinstance(obj, list):
        for v in obj:
            n = dostat_kartinku(v)
            if n:
                return n
    return None


def sgenerit(promt, foto_chasti, vyhod, proporciya, dvizhok, api):
    model = DVIZHKI[dvizhok]
    url = f"{API_ROOT}/models/{model}:generateContent"
    telo = {
        "contents": [{"parts": foto_chasti + [{"text": promt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"],
                             "imageConfig": {"aspectRatio": proporciya}},
    }
    req = urllib.request.Request(
        url, data=json.dumps(telo, ensure_ascii=False).encode(),
        headers={"x-goog-api-key": api, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300, context=SSL_CTX) as r:
            otvet = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "telo": e.read().decode("utf-8", "replace")[:600]}
    except Exception as e:
        return {"ok": False, "oshibka": f"{type(e).__name__}: {e}"}

    b64 = dostat_kartinku(otvet)
    if not b64:
        # Часто это отказ модели по фильтрам - причина лежит в finishReason.
        prichina = json.dumps(otvet, ensure_ascii=False)[:600]
        return {"ok": False, "oshibka": "картинки в ответе нет", "telo": prichina}

    papka = os.path.dirname(os.path.abspath(vyhod))
    if papka:
        os.makedirs(papka, exist_ok=True)
    dannye = base64.b64decode(b64)
    with open(vyhod, "wb") as f:
        f.write(dannye)
    return {"ok": True, "fayl": os.path.abspath(vyhod), "bayt": len(dannye), "model": model}


def main():
    p = argparse.ArgumentParser(description="ИИ-фотосессия с лицом человека (Nano Banana)")
    p.add_argument("--refs", nargs="+", required=True, help="папки или файлы с фото человека")
    p.add_argument("--profil", help="файл с постоянными требованиями к внешности; "
                                    "если не задан, берётся profil-vneshnosti.txt рядом с фото")
    p.add_argument("--prompt", "-p", help="промт-сцена (идентичность допишется сама)")
    p.add_argument("--prompt-file", help="файл с промтом-сценой")
    p.add_argument("--seriya", help="JSON со списком сцен для пачки")
    p.add_argument("--out-dir", default="./fotosessiya", help="куда класть серию")
    p.add_argument("--output", "-o", help="файл для одиночного кадра")
    p.add_argument("--aspect-ratio", "-a", default="3:4", choices=PROPORCII)
    p.add_argument("--engine", "-e", default="nano2", choices=list(DVIZHKI))
    p.add_argument("--baza", help="готовый кадр для ВТОРОГО прохода: сцена остаётся, "
                                  "меняется только лицо на настоящее с референсов")
    p.add_argument("--pokazat-promt", action="store_true", help="напечатать промт и выйти")
    a = p.parse_args()

    api = kluch()
    if not api and not a.pokazat_promt:
        print("Пропуск к Gemini не подключён: нет строки GEMINI_API_KEY в файле .env в корне офиса. Как получить - team/agents/tehnar/vneshnie-servisy.md, раздел «Картинки»")
        sys.exit(1)

    fayly = sobrat_refy(a.refs)
    if not fayly and not a.pokazat_promt:
        print(f"фото-референсов не нашлось в: {', '.join(a.refs)}")
        sys.exit(1)
    print(f"референсов: {len(fayly)}")
    for f in fayly:
        print(f"  {f}")

    # Профиль внешности: явно указанный файл либо тот, что лежит рядом с фото.
    # Второе - чтобы про него нельзя было забыть, вызывая скрипт наспех.
    put_profilya = a.profil
    if not put_profilya and fayly:
        ryadom = os.path.join(os.path.dirname(os.path.abspath(fayly[0])), "profil-vneshnosti.txt")
        put_profilya = ryadom if os.path.exists(ryadom) else None
    profil = open(put_profilya).read() if put_profilya else ""
    print(f"профиль внешности: {put_profilya or 'нет'}")

    sceny = []
    if a.baza:
        sceny = []  # второму проходу сцена не нужна: она уже на базовом кадре
    elif a.seriya:
        sceny = json.load(open(a.seriya))
    else:
        tekst = a.prompt or (open(a.prompt_file).read() if a.prompt_file else None)
        if not tekst:
            print("нужен -p, --prompt-file или --seriya")
            sys.exit(1)
        sceny = [{"slug": "kadr", "prompt": tekst, "aspect": a.aspect_ratio}]

    if a.pokazat_promt:
        for s in sceny:
            print(f"\n{'=' * 70}\n{s.get('slug', '?')}  [{s.get('aspect', a.aspect_ratio)}]\n{'=' * 70}")
            print(konstruktor_promta(s.get("prompt") or s, profil))
        return

    chasti = chasti_s_foto(fayly)

    # Второй проход: базовый кадр идёт ПЕРВЫМ, промт сцены не нужен вовсе.
    if a.baza:
        vyhod = a.output or a.baza.replace(".png", "-litso.png")
        print(f"\nвторой проход: {a.baza} → {vyhod}")
        r = sgenerit(PODMENA_LICA, chasti_s_foto([a.baza]) + chasti, vyhod,
                     a.aspect_ratio, a.engine, api)
        print("  готово" if r["ok"] else f"  НЕ вышло: {json.dumps(r, ensure_ascii=False)[:400]}")
        sys.exit(0 if r["ok"] else 1)

    itogi = []
    for i, s in enumerate(sceny, 1):
        slug = s.get("slug", f"kadr-{i}")
        vyhod = a.output if (a.output and len(sceny) == 1) else os.path.join(a.out_dir, f"{slug}.png")
        promt = konstruktor_promta(s.get("prompt") or s, profil)
        print(f"\n[{i}/{len(sceny)}] {slug} → {vyhod}")
        r = sgenerit(promt, chasti, vyhod, s.get("aspect", a.aspect_ratio), a.engine, api)
        if r["ok"]:
            print(f"  готово, {r['bayt'] // 1024} КБ, {r['model']}")
        else:
            print(f"  НЕ вышло: {json.dumps(r, ensure_ascii=False)[:400]}")
        itogi.append({"slug": slug, **r})
        if i < len(sceny):
            time.sleep(2)

    horosho = sum(1 for x in itogi if x.get("ok"))
    print(f"\nитого: {horosho} из {len(sceny)}")
    sys.exit(0 if horosho else 1)


if __name__ == "__main__":
    main()
