#!/usr/bin/env python3
"""Генерация картинки через fal.ai (FLUX.2 [dev]) - облачная альтернатива уровня Midjourney.
Написано 13.09.2026. Ключ FAL_KEY в .env офиса.
Только urllib, клиент fal не ставим (правило офиса: ничего не ставить без разрешения).

Цена: $0.012 за мегапиксель (страница fal, сверено 13.09.2026): 2048x1152 = 2,4 МП ≈ $0.03.
Потолок стороны 2048 px, поэтому 4K потом тянем апскейлером (RealESRGAN локально или fal esrgan).

Запуск:
  python3 generate-fal.py -p "промт" -o out.png                # 2048x1152
  python3 generate-fal.py -p "промт" -o out.png --w 2048 --h 1152 --steps 28 --guidance 2.5 --seed 7
  python3 generate-fal.py -p "промт" -i ref.png -o out.png     # режим правки по картинке (flux-2 edit)
"""
import argparse, base64, json, mimetypes, os, sys, time, urllib.error, urllib.request
from pathlib import Path

# скрипт лежит в <офис>/.agents/skills/image-gen/scripts/, корень офиса - на четыре папки выше
OFFICE = Path(__file__).resolve().parents[4]
QUEUE = "https://queue.fal.run"
MODEL_T2I = "fal-ai/flux-2"
MODEL_EDIT = "fal-ai/flux-2/edit"

NET_KLYUCHA = ("Пропуск к fal не подключён: нет строки FAL_KEY в файле .env в корне офиса.\n"
               "Как получить - team/agents/tehnar/vneshnie-servisy.md, раздел «FLUX через fal».")

def key():
    k = os.environ.get("FAL_KEY", "").strip()
    if k:
        return k
    env = OFFICE / ".env"
    try:
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("FAL_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        sys.exit(NET_KLYUCHA)
    if not k:
        sys.exit(NET_KLYUCHA)
    return k

def req(url, data=None, timeout=180):
    r = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                               headers={"Authorization": f"Key {key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {url}\n{e.read().decode()[:2000]}")

def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--prompt", required=True); p.add_argument("-o", "--output", required=True)
    p.add_argument("-i", "--image", action="append", help="картинка на вход (режим flux-2/edit); можно несколько: первая - сцена, вторая - образец стиля")
    p.add_argument("--w", type=int, default=2048); p.add_argument("--h", type=int, default=1152)
    p.add_argument("--steps", type=int, default=28); p.add_argument("--guidance", type=float, default=2.5)
    p.add_argument("--seed", type=int); a = p.parse_args()

    payload = {"prompt": a.prompt, "image_size": {"width": a.w, "height": a.h}, "num_inference_steps": a.steps,
               "guidance_scale": a.guidance, "num_images": 1, "output_format": "png", "enable_safety_checker": False}
    if a.seed is not None: payload["seed"] = a.seed
    model = MODEL_T2I
    if a.image:
        model = MODEL_EDIT; payload["image_urls"] = [data_uri(x) for x in a.image]
    t0 = time.time()
    sub = req(f"{QUEUE}/{model}", payload)
    status_url = sub.get("status_url"); resp_url = sub.get("response_url")
    if not status_url:
        sys.exit("нет status_url в ответе: " + json.dumps(sub)[:500])
    while True:
        st = req(status_url)
        if st.get("status") == "COMPLETED": break
        if st.get("status") in ("FAILED", "ERROR"): sys.exit("fal: " + json.dumps(st)[:1000])
        time.sleep(2)
    res = req(resp_url)
    imgs = res.get("images") or []
    if not imgs: sys.exit("нет картинки в ответе: " + json.dumps(res)[:1000])
    with urllib.request.urlopen(imgs[0]["url"], timeout=180) as r, open(a.output, "wb") as f:
        f.write(r.read())
    print(json.dumps({"output": a.output, "model": model, "seed": res.get("seed"), "size": f"{imgs[0].get('width')}x{imgs[0].get('height')}",
                      "seconds": round(time.time() - t0), "usd_est": round(a.w * a.h / 1e6 * 0.012, 3)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
