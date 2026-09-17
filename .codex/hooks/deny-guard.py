#!/usr/bin/env python3
"""Сторож на команды в терминале (PreToolUse). Замена списка запретов из .claude/settings.json
для Codex, где такого списка нет. Смысл тот же: наружу ничего не уходит, секреты не трогаем,
из интернета ничего не ставим. Запрещённая команда проверяется как ПЕРВОЕ слово сегмента,
опасные куски - где угодно в строке."""
import json, re, sys

BAD_CMD = {
    'curl', 'wget', 'scp', 'sftp', 'rsync', 'nc', 'ncat', 'netcat', 'telnet', 'ftp',
    'ssh', 'mail', 'sendmail', 'osascript', 'npx', 'yarn', 'pnpm', 'brew', 'gem', 'cargo', 'winget', 'choco',
}
BAD_ANY = [
    r'\bnpm\s+(i|install)\b', r'\bpip3?\s+install\b', r'\bgo\s+install\b', r'\bgit\s+clone\b',
    r'python3?\s+-c\b', r'node\s+-e\b', r'perl\s+-e\b', r'ruby\s+-e\b', r'\b(ba)?sh\s+-c\b', r'\beval\b',
    r'\bgh\b', r'\bgit\s+push\b',
    r'\brm\s+-[rf]{2}\b',
    r'--dangerously-bypass-approvals-and-sandbox', r'--dangerously-skip-permissions', r'(?<!\w)--yolo(?!\w)',
    r'(?<!\w)\.env(?!\w)', r'\.pem(?!\w)', r'\bsecrets?\b', r'\bcredentials\b',
    r'(^|[\s;&|])\.?/?karantin/',
]

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
sys.exit(0)
