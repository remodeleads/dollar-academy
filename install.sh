#!/bin/bash
# One-time setup: create the Python venv and install dependencies.
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"

echo "▶ Creating virtualenv…"
python3 -m venv "$BASE/.venv"
"$BASE/.venv/bin/pip" install -q --upgrade pip
"$BASE/.venv/bin/pip" install -q -r "$BASE/requirements.txt"
echo "✅ venv ready."

cat <<'EOF'

Next steps:
  1. put your Google OAuth file here as    credentials.json
  2. .venv/bin/python authorize.py         # ONE sign-in → Calendar (read) + Drive (upload)
  3. edit config.json → set DRIVE_FOLDER_ID (from your Drive folder URL)
  4. .venv/bin/python pipeline.py --dry-run --scan   # preview matches (touches nothing)
  5. .venv/bin/python pipeline.py --scan             # first real run
Then, to run it in the background forever:
  6. ./load-agent.sh
EOF
