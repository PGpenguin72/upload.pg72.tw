#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "❌  找不到 .env 檔案"
  echo "   請先：cp .env.example .env  然後填入設定值"
  exit 1
fi

# macOS 需要先安裝 libmagic：brew install libmagic
# Ubuntu/Debian：apt-get install libmagic1

mkdir -p uploads temp

pip install -r requirements.txt -q

echo "🚀  啟動 upload service on port $(grep PORT .env | cut -d= -f2 || echo 3000)..."
uvicorn main:app --host 0.0.0.0 --port "$(python3 -c "from config import settings; print(settings.port)")"
