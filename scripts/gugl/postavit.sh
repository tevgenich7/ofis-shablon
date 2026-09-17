#!/bin/bash
# Один раз на этом компьютере: своё окружение для гугл-скриптов офиса.
# Ставит три библиотеки Google в папку внутри офиса, систему не трогает.
# Снести потом - удалить папку scripts/gugl/venv.
set -e
KOREN="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$KOREN/scripts/gugl"

python3 -m venv venv
./venv/bin/python3 -m pip install --quiet --upgrade pip
./venv/bin/python3 -m pip install --quiet \
  google-api-python-client google-auth-httplib2 google-auth-oauthlib

echo "Готово. Дальше один раз вход в гугл:"
echo "  scripts/gugl/venv/bin/python3 scripts/gugl/avtorizaciya.py"
