#!/usr/bin/env bash
# Starts the app after ./setup.sh: the extraction server on http://127.0.0.1:8000
# and the frontend on http://localhost:5173, which it opens in your browser.
# Ctrl+C stops both.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
# Where setup.sh put Node.js (if it downloaded it), mineru and claude, which the extraction server runs.
export PATH="$ROOT/.runtime/node/bin:$HOME/.local/bin:$PATH"

if [ ! -x "$ROOT/extraction/.venv/bin/python" ] || [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Run ./setup.sh first." >&2
  exit 1
fi

(cd "$ROOT/extraction" && exec .venv/bin/python api.py) &
api=$!
# --strictPort: fail rather than move to another port, which the browser wouldn't be opened at.
(cd "$ROOT/frontend" && exec node_modules/.bin/vite --strictPort) &
web=$!

# Disable the shutdown traps and send SIGTERM to both child PIDs, ignoring kill errors.
stop() {
  trap - INT TERM EXIT
  kill "$api" "$web" 2>/dev/null || true
}
trap 'stop; exit 130' INT TERM
trap stop EXIT

# Open the page once the frontend answers.
for _ in $(seq 30); do
  if curl -s -o /dev/null http://localhost:5173; then
    if command -v open >/dev/null; then open http://localhost:5173
    elif command -v xdg-open >/dev/null; then xdg-open http://localhost:5173 >/dev/null 2>&1
    fi
    break
  fi
  kill -0 "$web" 2>/dev/null || break
  sleep 1
done

# Run until Ctrl+C, or until either one stops on its own.
while kill -0 "$api" 2>/dev/null && kill -0 "$web" 2>/dev/null; do sleep 1; done
echo "The app stopped. If a message above says an address or port is already in use," \
  "the app is probably still running in another terminal." >&2
exit 1
