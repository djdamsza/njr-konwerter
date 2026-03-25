#!/bin/bash
cd "$(dirname "$0")"
if lsof -ti:5050 >/dev/null 2>&1; then
  echo "Zatrzymuję starą instancję na porcie 5050..."
  lsof -ti:5050 | xargs kill -9 2>/dev/null
  sleep 1
fi
if ! python3 -c "import flask" 2>/dev/null; then
  pip3 install -r requirements.txt
fi
echo "Edytor bazy VirtualDJ - otwórz http://127.0.0.1:5050"
python3 app.py
