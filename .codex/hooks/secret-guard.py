#!/usr/bin/env python3
"""Сторож на запись файлов (PreToolUse): не давать переписать секреты и трогать карантин.
Проверка грубая - регулярка по всему tool_input, потому что имя поля с путём у разных
инструментов отличается. Ложное срабатывание дешевле пропуска."""
import json, re, sys

SECRET = re.compile(r'(?<!\w)\.env(?!\w)|\.pem(?!\w)|secrets?[/.]|credentials|(^|[/\s"\'])karantin/')

try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)

blob = json.dumps(ev.get('tool_input') or {}, ensure_ascii=False)
if SECRET.search(blob):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "офис: правка секретов и карантина запрещена",
    }}, ensure_ascii=False))
sys.exit(0)
