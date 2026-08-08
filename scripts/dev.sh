#!/usr/bin/env bash
# One command for the whole stack — ticket 57.
#
#   scripts/dev.sh          start backend + editor, supervised (restart on crash)
#   scripts/dev.sh stop     stop everything this script started
#
# Usually reached as `./start dev`. The containerised counterpart is `./start`.
#
# Both processes hot-reload: Vite does it natively, uvicorn via --reload.
#
# WORKER COUNT — two independent reasons it is 1, both real:
#
#   1. `--reload` and `--workers N` are mutually exclusive. uvicorn's reloader
#      is itself the supervising process, so passing both makes it warn and
#      run a single worker anyway. Asking for more here would be theatre.
#   2. Even without --reload, this app cannot run multi-worker today. The
#      human-in-the-loop checkpointer in api/main.py is a module-level
#      `InMemorySaver` — per-process state. A second worker gets a second,
#      empty copy, so a /api/runs/resume that lands on the wrong worker cannot
#      find the run it is resuming. Fixing that is not a flag: it needs a
#      persisted checkpointer (SqliteSaver on a file for one host, Postgres
#      beyond that) wired into main.py. The container CMD is single-worker for
#      exactly this reason, and says so.
#
# Encapsulates the two incantations the README used to ask you to hand-type:
# the backend's PYTHONPATH (the chinook path shim pytest.ini documents) and
# SSL_CERT_FILE (python.org macOS installs ship no CA bundle — ticket 59
# moves this into tool code; the env var stays as belt-and-braces).
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.dev"
mkdir -p "$RUN_DIR"

#: Patterns matching the actual worker processes, as distinct from the
#: supervisors that spawn them. Both are *grandchildren*, which is why killing
#: the supervisor is not enough on its own:
#:   backend — `--reload` makes uvicorn a reloader parent with a server child.
#:   vite    — `npm run dev` execs npm, which forks the real vite process.
#: `pkill -P <supervisor>` reaches only the direct child, so the grandchild is
#: re-parented to init and survives. Observed live: `dev.sh stop` reported
#: "stopped backend / stopped vite" while a uvicorn and two vites kept running
#: and port 8000 kept answering.
WORKER_PATTERNS='uvicorn openstategraph.api.main:app
node_modules/.bin/vite'

sweep_workers() { # signal
  echo "$WORKER_PATTERNS" | while IFS= read -r pattern; do
    [ -n "$pattern" ] && pkill "$1" -f "$pattern" 2>/dev/null
  done
  sweep_ports "$1"
  return 0
}

#: Cmdline patterns are not sufficient, and this is the specific reason:
#: under `--reload`, uvicorn's actual *server* process is spawned through
#: multiprocessing, so its cmdline is
#:   python -c 'from multiprocessing.spawn import spawn_main; ...'
#: with the word "uvicorn" nowhere in it. Kill the reloader parent with
#: SIGKILL (which cannot be forwarded) and that child is re-parented to init,
#: still holding port 8000. Observed live: every pattern sweep reported
#: success, no process matched "uvicorn", and :8000 kept answering 200.
#: So the last word belongs to whoever actually holds the port.
sweep_ports() { # signal
  command -v lsof >/dev/null 2>&1 || return 0
  for port in 8000 5273; do
    for pid in $(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
      kill "$1" "$pid" 2>/dev/null
    done
  done
  return 0
}

#: Kill supervisor loops that no pid file points at any more. This is not
#: paranoia — it is the failure that made `stop` look broken: starting the
#: stack twice overwrites .dev/*.supervisor.pid with the second run's PIDs,
#: so the first run's loops become unreachable *and* immortal, respawning a
#: worker every 2s forever. Observed live: two orphan supervisors from a
#: five-minute-old run kept resurrecting uvicorn and vite through repeated,
#: apparently-successful `stop` calls. Excludes this process and its parent,
#: which match the same pattern.
sweep_supervisors() {
  for pid in $(pgrep -f "scripts/dev.sh" 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "${PPID:-0}" ] && continue
    kill "$pid" 2>/dev/null && echo "stopped orphaned supervisor $pid"
  done
  return 0
}

stop_all() {
  # Supervisors first, so nothing restarts the workers we are about to sweep.
  # (The old order swept first and left the supervisor alive for its 2s
  # restart loop to bring a fresh worker straight back up.)
  for name in backend vite; do
    local_pid_file="$RUN_DIR/$name.supervisor.pid"
    if [ -f "$local_pid_file" ]; then
      kill "$(cat "$local_pid_file")" 2>/dev/null
      pkill -P "$(cat "$local_pid_file")" 2>/dev/null
      rm -f "$local_pid_file"
      echo "stopped $name"
    fi
  done
  # Belt-and-braces for orphans — escalate to SIGKILL after a grace
  # period: uvicorn's graceful shutdown waits for in-flight requests, and a
  # long-running SSE stream keeps it draining forever with the listener
  # already closed (observed live: port dead, process alive for minutes).
  sweep_supervisors
  sweep_workers -TERM
  sleep 3
  sweep_workers -KILL
  exit 0
}
[ "${1:-}" = "stop" ] && stop_all

# Refuse to start a second stack on top of a live one. Without this, the new
# run's pid files overwrite the old run's and the old supervisors become
# orphans no `stop` can reach (see sweep_supervisors). Cheaper to prevent than
# to sweep, and the ports would clash anyway — the second uvicorn just logs
# "Address already in use" on a 2s loop forever.
for name in backend vite; do
  pid_file="$RUN_DIR/$name.supervisor.pid"
  if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$name is already running (.dev/$name.supervisor.pid)." >&2
    echo "Stop it first:  ./start stop" >&2
    exit 1
  fi
done

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
# --reload-dir is scoped rather than left to default: uvicorn's default is the
# current working directory, which here is the repo root — so the watcher would
# walk node_modules/ and dist/ and burn CPU (or hit the macOS fd limit) waiting
# for changes that can never affect the Python process. backend/ and workflows/
# are the only trees whose edits the server should react to.
PYTHONPATH="backend:workflows/chinook-nl-to-sql" SSL_CERT_FILE="${CERT_FILE}" \
  supervise backend python3 -m uvicorn openstategraph.api.main:app --port 8000 --app-dir backend \
    --reload --reload-dir backend --reload-dir workflows

supervise vite npm run dev

echo
echo "editor:  http://localhost:5273"
echo "runtime: http://localhost:8000/api/health"
echo "stop:    scripts/dev.sh stop   ·   status: scripts/status.sh"
