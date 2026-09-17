#!/usr/bin/env python3
"""Сторож на команды в терминале (PreToolUse). Замена списка запретов из .claude/settings.json
для Codex, где такого списка нет.

Правило, по которому всё устроено: **запрещаем отправку наружу, разрешаем чтение своего
состояния**. Помощник должен уметь посмотреть, живы ли процессы, отвечает ли панель и есть ли
связь с телеграмом - иначе любая поломка упирается в человека с терминалом. Но ничего из офиса
наружу не уходит и ничего из интернета не ставится.

Запрещённая команда проверяется как ПЕРВОЕ слово сегмента, опасные куски - где угодно в строке.
"""
import json, re, sys

BAD_CMD = {
    'wget', 'scp', 'sftp', 'rsync', 'nc', 'ncat', 'netcat', 'telnet', 'ftp',
    'ssh', 'mail', 'sendmail', 'osascript', 'npx', 'yarn', 'pnpm', 'brew', 'gem', 'cargo', 'winget', 'choco',
}
BAD_ANY = [
    r'\bnpm\s+(i|install)\b', r'\bpip3?\s+install\b', r'\bgo\s+install\b',
    r'python3?\s+-c\b', r'node\s+-e\b', r'perl\s+-e\b', r'ruby\s+-e\b', r'\b(ba)?sh\s+-c\b', r'\beval\b',
    r'\bgh\b', r'\bgit\s+push\b',
    r'\brm\s+-[rf]{2}\b',
    r'--dangerously-bypass-approvals-and-sandbox', r'--dangerously-skip-permissions', r'(?<!\w)--yolo(?!\w)',
    r'(?<!\w)\.env(?!\w)', r'\.pem(?!\w)', r'\bsecrets?\b', r'\bcredentials\b',
    r'(^|[\s;&|])\.?/?karantin/',
]

# ── curl: только посмотреть, только своё ─────────────────────────────────────
# Разрешены свой компьютер и телеграм: этого хватает, чтобы проверить панель и связь бота.
CURL_MOZHNO = re.compile(
    r'^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?([/?#]|$)'
    r'|^https://api\.telegram\.org([/?#]|$)', re.I)
# Любой флаг, которым можно что-то ОТПРАВИТЬ - значит это уже не проверка.
CURL_OTPRAVKA = re.compile(
    r'(^|\s)(-d|--data|--data-binary|--data-raw|--data-urlencode|-F|--form|-T|--upload-file|--json)(\s|=)'
    r'|(^|\s)-X\s*(POST|PUT|PATCH|DELETE)\b'
    r'|(^|\s)-[a-zA-Z]*[dFT][a-zA-Z]*(\s|$)', re.I)
ADRES = re.compile(r'https?://\S+', re.I)

# ── git: забрать обновления офиса можно, отправлять - нет ────────────────────
OBNOVLENIYA = 'github.com/tevgenich7/ofis-shablon'


def first_token(seg):
    seg = seg.strip()
    while True:
        m = re.match(r'^(?:\w+=\S*|sudo|command|env)\s+', seg)
        if not m:
            break
        seg = seg[m.end():]
    tok = re.split(r'\s', seg, maxsplit=1)[0]
    return tok.rsplit('/', 1)[-1]


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"офис: {reason}",
    }}, ensure_ascii=False))
    sys.exit(0)


def proverit_curl(seg, ves_cmd):
    """curl пропускаем, только если это чистая проверка своего же хозяйства."""
    if '$(' in ves_cmd or '`' in ves_cmd:
        deny('curl с подстановкой команды под запретом: адрес должен быть виден целиком')
    if CURL_OTPRAVKA.search(seg):
        deny('curl с отправкой данных под запретом, проверять можно только чтением')
    adresa = ADRES.findall(seg)
    if not adresa:
        deny('curl без явного адреса под запретом')
    for a in adresa:
        a = a.strip('\'"')
        if not CURL_MOZHNO.match(a):
            deny(f'curl наружу под запретом ({a}); можно только свой компьютер и api.telegram.org')


def proverit_git(seg):
    """Забрать обновления офиса - можно. Тянуть что попало из интернета - нет."""
    if re.search(r'\bgit\s+(clone|fetch|pull|remote\s+add)\b', seg):
        adresa = ADRES.findall(seg) + re.findall(r'git@\S+', seg)
        for a in adresa:
            if OBNOVLENIYA not in a:
                deny(f'из интернета берём только обновления офиса, а тут {a}')


try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)

ti = ev.get('tool_input') or {}
cmd = ti.get('command', '')
if isinstance(cmd, list):
    cmd = ' '.join(str(x) for x in cmd)
cmd = str(cmd)

for p in BAD_ANY:
    if re.search(p, cmd):
        deny(f"команда под запретом ({p})")

for seg in re.split(r'[;&|]{1,2}|\n|\$\(|`', cmd):
    t = first_token(seg)
    if t in BAD_CMD:
        deny(f"команда «{t}» под запретом")
    if t == 'curl':
        proverit_curl(seg, cmd)
    if t == 'git':
        proverit_git(seg)

sys.exit(0)
