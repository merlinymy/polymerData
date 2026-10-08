#!/usr/bin/env bash
# Installs everything the app needs, on macOS or Linux. On a Mac,
# PolymerData.app runs it for you; from a terminal:
#
#     ./setup.sh
#
# Node.js (into .runtime/node, if yours is missing or too old), Claude Code
# (logged in with your Claude account, no API key), MinerU and its model files
# (about 2 GB), the extraction server's Python packages and the frontend's
# packages. Asks once where to keep your data. Safe to run again: it skips
# what's already done, so run it after every update too.
#
# With GUI=1, as PolymerData.app runs it, its questions come as dialogs, each
# step's name is added to .runtime/setup-steps, and the reason it stopped, if
# it does, goes to .runtime/setup-error: the app shows them on a progress page.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RUNTIME="$ROOT/.runtime"
mkdir -p "$RUNTIME"
GUI="${GUI:-}"
# Where this script puts Node.js, and where uv, Claude Code and MinerU install their commands.
export PATH="$RUNTIME/node/bin:$HOME/.local/bin:$PATH"

if [ -n "$GUI" ]; then AGAIN="double-click PolymerData again"; else AGAIN="run ./setup.sh again"; fi

# Print the step name ($1); with GUI set, append it to .runtime/setup-steps.
step() {
  printf '\n==> %s\n' "$1"
  if [ -n "$GUI" ]; then echo "$1" >>"$RUNTIME/setup-steps"; fi
}
# Print the reason ($1) to stderr and exit 1; with GUI set, save it to .runtime/setup-error.
fail() {
  printf '\n%s\n' "$1" >&2
  if [ -n "$GUI" ]; then echo "$1" >"$RUNTIME/setup-error"; fi
  exit 1
}
# A dialog with one button: message TEXT BUTTON.
message() {
  osascript - "$1" "$2" >/dev/null <<'EOF'
on run argv
  activate
  display dialog (item 1 of argv) buttons {item 2 of argv} default button 1 with title "PolymerData"
end run
EOF
}
# Asks where to keep the data, suggesting the folder it's given; prints the answer.
# Canceling returns nonzero; the caller then uses the suggested folder.
choose_data_dir() {
  osascript - "$1" <<'EOF'
on run argv
  set suggested to item 1 of argv
  activate
  set reply to display dialog "PolymerData keeps the papers it reads, and the data it gets out of them, in one folder:" & return & return & suggested & return & return & "Use this folder, or choose another one?" buttons {"Choose Another…", "Use This Folder"} default button 2 with title "PolymerData"
  if button returned of reply is "Use This Folder" then return suggested
  return POSIX path of (choose folder with prompt "Choose the folder for PolymerData's data:")
end run
EOF
}

# ERR trap handler: report a failed step through fail() and exit 1.
on_error() { fail "That step didn't finish. Check the internet connection, then $AGAIN. If it stops at the same step again, the latest messages say why."; }
trap on_error ERR

case "$(uname -s)" in
  Darwin | Linux) ;;
  *) fail "setup.sh runs on macOS and Linux. Windows isn't supported yet." ;;
esac

step "Checking Node.js"
# Return success for Node.js 20.19+, 22.12+, or a major version above 22.
# A missing Node.js or any other version returns nonzero (including 21.x).
node_ok() {
  command -v node >/dev/null &&
    node -e 'const [a, b] = process.versions.node.split(".").map(Number);
             process.exit(a > 22 || (a === 22 && b >= 12) || (a === 20 && b >= 19) ? 0 : 1)'
}
if ! node_ok; then
  echo "Downloading Node.js into .runtime/node"
  os="$(uname -s | tr '[:upper:]' '[:lower:]')" # darwin or linux
  case "$(uname -m)" in arm64 | aarch64) arch=arm64 ;; *) arch=x64 ;; esac
  base=https://nodejs.org/dist/latest-v24.x
  name="$(curl -fsSL "$base/SHASUMS256.txt" | grep -Eo "node-v[0-9.]+-$os-$arch\.tar\.gz" | sed -n 1p)"
  [ -n "$name" ] || fail "Couldn't find Node.js to download. Check the internet connection, then $AGAIN."
  rm -rf "$RUNTIME/node" "$RUNTIME/node.tmp"
  mkdir -p "$RUNTIME/node.tmp"
  curl -fsSL "$base/$name" | tar -xzf - -C "$RUNTIME/node.tmp" --strip-components 1
  mv "$RUNTIME/node.tmp" "$RUNTIME/node"
  node_ok || fail "Node.js didn't install. To try again, $AGAIN."
fi
node --version

step "Choosing where to keep your data"
ENV_FILE=extraction/.env
[ -f "$ENV_FILE" ] || cp extraction/.env.example "$ENV_FILE"
data_dir="$(sed -n 's/^DATA_DIR=//p' "$ENV_FILE" | tail -n 1)"
if [ -z "$data_dir" ]; then
  if [ -n "$GUI" ]; then
    suggested="$HOME/PolymerData Results"
    data_dir="$(choose_data_dir "$suggested")" || data_dir="$suggested"
    data_dir="${data_dir%/}"
  else
    echo "Parsed papers and extraction results go in one folder."
    answer=""
    if [ -t 0 ]; then
      read -r -p "Folder to use, e.g. ~/polymer-data (press Enter for extraction/output in this folder): " answer || true
    fi
    data_dir="${answer:-extraction/output}"
  fi
  # Replace the DATA_DIR line, or add one if the file has none.
  awk -v line="DATA_DIR=$data_dir" '/^DATA_DIR=/ { print line; done = 1; next } { print }
    END { if (!done) print line }' "$ENV_FILE" >"$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
fi
mkdir -p "${data_dir/#\~/$HOME}"
echo "Data folder: $data_dir (to change it, edit DATA_DIR in $ENV_FILE)"

step "Checking uv, the tool that installs MinerU and Python"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version
uv tool update-shell >/dev/null 2>&1 || true # so new terminals find mineru and claude too

step "Checking Claude Code and your Claude login"
if ! command -v claude >/dev/null; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
claude --version
# Without an API key in the environment, as the extraction server calls it.
# Return success only if Claude's auth status reports loggedIn: true.
logged_in() { env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude auth status --json 2>/dev/null | grep -q '"loggedIn": *true'; }
if ! logged_in; then
  if [ -n "$GUI" ]; then
    message "PolymerData reads papers with Claude, using your Claude account (a Pro, Max, Team or Enterprise plan).

Your browser opens next. Log in there, then come back to the setup page." "Log In"
  else
    echo "Log in with your Claude account (Pro, Max, Team or Enterprise). A browser window opens."
  fi
  env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude auth login || true
  logged_in || fail "You're not logged in to Claude yet. To try again, $AGAIN."
fi
echo "Logged in."

step "Installing the extraction server's Python packages"
[ -x extraction/.venv/bin/python ] || uv venv --quiet --python 3.12 extraction/.venv
uv pip install --quiet --python extraction/.venv/bin/python -r extraction/requirements.txt
PY=extraction/.venv/bin/python

step "Installing the frontend's packages"
(cd frontend && npm install --no-fund --no-audit --loglevel=error)

step "Installing MinerU, which turns a PDF into text and figure images"
if ! command -v mineru >/dev/null; then
  uv tool install --python 3.10 "mineru>=4.0,<5"
fi
mineru --version | sed -n 1p
# Ready once MinerU's local parser offers the "advanced" tier, the one extraction uses.
mineru_ready() {
  mineru server status --json 2>/dev/null | "$PY" -c 'import json, sys
local = json.load(sys.stdin).get("parse_server", {}).get("local", {})
sys.exit(0 if "advanced" in (local.get("supported_tiers") or []) else 1)' 2>/dev/null
}
if ! mineru_ready; then
  echo "Downloading MinerU's model files (about 2 GB) and starting it. This takes a while."
  mineru-kit models download --tier standard
  mineru config set parse_server.local.mode managed # parse on this computer, not MinerU's online service
  mineru server restart
  printf 'Waiting for MinerU to load its models'
  for _ in $(seq 60); do
    mineru_ready && break
    printf '.'
    sleep 5
  done
  echo
  mineru_ready || fail "MinerU is still loading its models. In a few minutes, $AGAIN."
fi
echo "MinerU is ready."

step "Asking Claude a test question"
"$PY" -c 'from util.claudeAPIMock import ask_llm; print("Claude says:", ask_llm("Reply with the single word: ready"))' ||
  fail "Claude didn't answer. If the setup page or the lines above mention a usage limit, wait for it to reset; then $AGAIN."

printf '\nAll set. Start the app with: ./start.sh\n'
