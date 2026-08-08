#!/usr/bin/env bash
# One command for the whole stack — ticket 57.
#
#   scripts/dev.sh          start backend + editor, supervised (restart on crash)
#   scripts/dev.sh stop     stop everything this script started
#
# Encapsulates the two incantations the README used to ask you to hand-type:
# the backend's PYTHONPATH (the chinook path shim pytest.ini documents) and
# SSL_CERT_FILE (python.org macOS installs ship no CA bundle — ticket 59
# moves this into tool code; the env var stays as belt-and-braces).
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.dev"
mkdir -p "$RUN_DIR"

stop_all() {
  for name in backend vite; do
    local_pid_file="$RUN_DIR/$name.supervisor.pid"
    if [ -f "$local_pid_file" ]; then
      pkill -P "$(cat "$local_pid_file")" 2>/dev/null
      kill "$(cat "$local_pid_file")" 2>/dev/null
      rm -f "$local_pid_file"
      echo "stopped $name"
    fi
  done
  # Belt-and-braces for orphans — escalate to SIGKILL after a grace
  # period: uvicorn's graceful shutdown waits for in-flight requests, and a
  # long-running SSE stream keeps it draining forever with the listener
  # already closed (observed live: port dead, process alive for minutes).
  pkill -f "uvicorn openstategraph.api.main:app" 2>/dev/null
  sleep 3
  pkill -9 -f "uvicorn openstategraph.api.main:app" 2>/dev/null
  exit 0
}
[ "${1:-}" = "stop" ] && stop_all

command -v npm >/dev/null || { echo "npm not found" >&2; exit 1; }
CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null || true)"

supervise() { # name, command...
  local name="$1"; shift
  (
    while true; do
      echo "[$(date +%H:%M:%S)] starting $name" >> "$RUN_DIR/$name.log"
      "$@" >> "$RUN_DIR/$name.log" 2>&1
      echo "[$(date +%H:%M:%S)] $name exited ($?) — restarting in 2s" >> "$RUN_DIR/$name.log"
      sleep 2
    done
  ) &
  echo $! > "$RUN_DIR/$name.supervisor.pid"
  echo "$name supervised (log: .dev/$name.log)"
}

cd "$ROOT"
PYTHONPATH="backend:workflows/chinook-nl-to-sql" SSL_CERT_FILE="${CERT_FILE}" \
  supervise backend python3 -m uvicorn openstategraph.api.main:app --port 8000 --app-dir backend
supervise vite npm run dev

echo
echo "editor:  http://localhost:5273"
echo "runtime: http://localhost:8000/api/health"
echo "stop:    scripts/dev.sh stop   ·   status: scripts/status.sh"
