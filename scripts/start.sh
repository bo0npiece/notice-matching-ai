#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ ! -f .env ]; then
  cp .env.example .env
fi
# 첫 실행은 인터넷 연결 필요. 이후에는 설치된 패키지로 바로 실행.
if ! .venv/bin/python -c 'import fastapi,uvicorn,httpx,dotenv,multipart,PIL,jsonschema' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
