#!/usr/bin/env python3
"""
Стоки офиса: поиск и скачивание бесплатных фото и видео под перебивки в рилсах,
фоны каруселей и обложки.

Три бесплатных источника, ключи в .env корня офиса:
    PEXELS_API_KEY    - фото и видео, 200 запросов в час
    UNSPLASH_API_KEY  - фото, 50 запросов в час на демо-ключе
    PIXABAY_API_KEY   - фото и видео

Ключа нет - скрипт честно скажет, какой именно, и не будет делать вид, что искал.

Использование:
    python3 stoki.py "woman skincare face" --tip foto --skolko 8
    python3 stoki.py "serum drops macro" --tip video --skolko 5 --istochnik pexels
    python3 stoki.py "clinic interior" --skachat 3            # скачать первые 3 находки

Куда кладёт: inbox/stoki/<запрос>/ - оттуда Монтажёр и Дизайнер берут в работу.
Наружу уходит только текст запроса. Ничего из офиса не отправляется.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

KOREN = Path(__file__).resolve().parents[4]      # .agents/skills/stoki/scripts -> корень офиса
KUDA = KOREN / "inbox" / "stoki"


def klyuchi() -> dict:
    """Читает .env корня офиса. Значения никуда не печатаются и не логируются."""
    out = {}
    for imya in ("PEXELS_API_KEY", "UNSPLASH_API_KEY", "PIXABAY_API_KEY"):
        znach = os.environ.get(imya, "").strip()
        if znach:
            out[imya] = znach
    fajl = KOREN / ".env"
    if fajl.exists():
        for stroka in fajl.read_text(encoding="utf-8", errors="ignore").splitlines():
            stroka = stroka.strip()
            if not stroka or stroka.startswith("#") or "=" not in stroka:
                continue
            imya, _, znach = stroka.partition("=")
            imya, znach = imya.strip(), znach.strip().strip('"').strip("'")
            if imya in ("PEXELS_API_KEY", "UNSPLASH_API_KEY", "PIXABAY_API_KEY") and znach:
                out.setdefault(imya, znach)
    return out


def zapros(url: str, zagolovki: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=zagolovki or {})
    req.add_header("User-Agent", "ofis-blogera/1.0")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# ── источники ────────────────────────────────────────────────────────────────

def pexels(klyuch: str, tekst: str, tip: str, skolko: int) -> list[dict]:
    baza = "https://api.pexels.com/videos/search" if tip == "video" else "https://api.pexels.com/v1/search"
    url = f"{baza}?query={urllib.parse.quote(tekst)}&per_page={skolko}&orientation=portrait"
    d = zapros(url, {"Authorization": klyuch})
    out = []
    for it in d.get("videos" if tip == "video" else "photos", []):
        if tip == "video":
            fajly = sorted(it.get("video_files", []), key=lambda f: -(f.get("width") or 0))
            if not fajly:
                continue
            out.append({"istochnik": "pexels", "avtor": it.get("user", {}).get("name", ""),
                        "stranica": it.get("url", ""), "fajl": fajly[0].get("link", ""),
                        "razmer": f'{fajly[0].get("width")}x{fajly[0].get("height")}'})
        else:
            out.append({"istochnik": "pexels", "avtor": it.get("photographer", ""),
                        "stranica": it.get("url", ""), "fajl": it.get("src", {}).get("large2x", ""),
                        "razmer": f'{it.get("width")}x{it.get("height")}'})
    return out


def unsplash(klyuch: str, tekst: str, tip: str, skolko: int) -> list[dict]:
    if tip == "video":
        return []          # у Unsplash видео нет, это честно, а не ошибка
    url = (f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(tekst)}"
           f"&per_page={skolko}&orientation=portrait")
    d = zapros(url, {"Authorization": f"Client-ID {klyuch}"})
    out = []
    for it in d.get("results", []):
        out.append({"istochnik": "unsplash", "avtor": (it.get("user") or {}).get("name", ""),
                    "stranica": (it.get("links") or {}).get("html", ""),
                    "fajl": (it.get("urls") or {}).get("regular", ""),
                    "razmer": f'{it.get("width")}x{it.get("height")}'})
    return out


def pixabay(klyuch: str, tekst: str, tip: str, skolko: int) -> list[dict]:
    baza = "https://pixabay.com/api/videos/" if tip == "video" else "https://pixabay.com/api/"
    url = f"{baza}?key={klyuch}&q={urllib.parse.quote(tekst)}&per_page={max(skolko, 3)}&safesearch=true"
    if tip != "video":
        url += "&image_type=photo&orientation=vertical"
    d = zapros(url)
    out = []
    for it in d.get("hits", []):
        if tip == "video":
            v = (it.get("videos") or {}).get("large") or (it.get("videos") or {}).get("medium") or {}
            if not v.get("url"):
                continue
            out.append({"istochnik": "pixabay", "avtor": it.get("user", ""),
                        "stranica": it.get("pageURL", ""), "fajl": v.get("url"),
                        "razmer": f'{v.get("width")}x{v.get("height")}'})
        else:
            out.append({"istochnik": "pixabay", "avtor": it.get("user", ""),
                        "stranica": it.get("pageURL", ""), "fajl": it.get("largeImageURL", ""),
                        "razmer": f'{it.get("imageWidth")}x{it.get("imageHeight")}'})
    return out


ISTOCHNIKI = {
    "pexels": ("PEXELS_API_KEY", pexels),
    "unsplash": ("UNSPLASH_API_KEY", unsplash),
    "pixabay": ("PIXABAY_API_KEY", pixabay),
}


def skachat(nahodki: list[dict], tekst: str, skolko: int) -> list[Path]:
    papka = KUDA / re.sub(r"[^\w\- ]+", "", tekst).strip().replace(" ", "-")[:60]
    papka.mkdir(parents=True, exist_ok=True)
    fajly = []
    for i, n in enumerate(nahodki[:skolko], 1):
        if not n.get("fajl"):
            continue
        rasshirenie = ".mp4" if ".mp4" in n["fajl"] else ".jpg"
        put = papka / f'{i:02d}-{n["istochnik"]}{rasshirenie}'
        try:
            req = urllib.request.Request(n["fajl"], headers={"User-Agent": "ofis-blogera/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(put, "wb") as f:
                f.write(r.read())
            fajly.append(put)
        except Exception as e:
            print(f"  не скачалось ({n['istochnik']}): {e}", file=sys.stderr)
    # рядом кладём, откуда что взято: авторов бесплатных стоков принято указывать
    if fajly:
        spisok = [f'{p.name} - {n.get("avtor","")} / {n.get("stranica","")}'
                  for p, n in zip(fajly, nahodki[:skolko])]
        (papka / "otkuda.txt").write_text("\n".join(spisok), encoding="utf-8")
    return fajly


def main() -> int:
    p = argparse.ArgumentParser(description="поиск бесплатных фото и видео на стоках")
    p.add_argument("zapros", help="что ищем, лучше по-английски: стоки ищут по английским словам")
    p.add_argument("--tip", choices=["foto", "video"], default="foto")
    p.add_argument("--skolko", type=int, default=8)
    p.add_argument("--istochnik", choices=list(ISTOCHNIKI) + ["vse"], default="vse")
    p.add_argument("--skachat", type=int, default=0, help="скачать первые N находок")
    a = p.parse_args()

    k = klyuchi()
    nuzhny = list(ISTOCHNIKI) if a.istochnik == "vse" else [a.istochnik]
    nahodki, molchat = [], []

    for imya in nuzhny:
        peremennaya, funkciya = ISTOCHNIKI[imya]
        if peremennaya not in k:
            molchat.append(f"{imya} (нет {peremennaya} в .env)")
            continue
        try:
            nahodki += funkciya(k[peremennaya], a.zapros, a.tip, a.skolko)
        except Exception as e:
            molchat.append(f"{imya}: {e}")

    if molchat:
        print("Не искал тут: " + "; ".join(molchat), file=sys.stderr)
    if not nahodki:
        print("Ничего не нашлось. Если источники молчат - проверь ключи в .env.")
        return 1

    for i, n in enumerate(nahodki, 1):
        print(f'{i:2d}. [{n["istochnik"]}] {n["razmer"]:>10}  {n.get("avtor","")}  {n["stranica"]}')

    if a.skachat:
        fajly = skachat(nahodki, a.zapros, a.skachat)
        print(f"\nСкачано {len(fajly)} шт. в {fajly[0].parent if fajly else KUDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
