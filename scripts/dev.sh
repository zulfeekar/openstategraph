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
#   2. Even without --reload, this app cannot run multi-worker today — but the
#      reason changed with ticket 05 and is now smaller and precise. The HITL
#      checkpointer is no longer a module-level InMemorySaver: it is a
#      SqliteSaver on workflows/.openstategraph/checkpoints.sqlite, so a paused
#      approval now survives this script's restart-on-every-file-save. What it
#      does NOT survive is a second process: langgraph-checkpoint-sqlite's own
#      SqliteSaver documents itself as "lightweight, synchronous ... does not
#      scale to multiple threads", and its only concurrency control is a
#      threading.Lock per instance — which two OS processes do not share. The
#      long-term memory Store (OPENSTATEGRAPH_MEMORY_PATH -> SqliteStore) has
#      exactly the same shape. Raising the ceiling means PostgresSaver +
#      PostgresStore dropped into the same two seams; nothing else changes.
#      The container CMD is single-worker for exactly this reason, and says so.
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
#
# --reload-exclude and --timeout-graceful-shutdown are BOTH load-bearing, and
# both were added after one wedged server was diagnosed end to end (ticket 11).
# The failure looked like "the run never ends", and the mechanism was:
#
#   1. Something writes inside a watched tree while an SSE run is streaming.
#      This is not only a developer typing — the app writes there ITSELF:
#      `prebuilt_email.OUTBOX` is `workflows/_outbox/`, so the store-analytics
#      report's own happy path (send the approved report) drops an `.eml` into
#      a --reload-dir and reloads the server that is mid-send. Compiling a
#      mounted workflow package writes `workflows/<slug>/__pycache__/*.pyc`
#      for the same reason.
#   2. uvicorn's reloader then logs "Shutting down / Waiting for connections
#      to close" — and an SSE response never closes on its own, so the
#      graceful wait never returns. No replacement child is ever spawned.
#   3. The reloader parent still holds :8000, so every later request — the
#      live run, the next run, even /api/health — connects and hangs FOREVER.
#      Observed live: `curl /api/health` timed out at 30s with the log's last
#      line being "Waiting for connections to close."
#
# So: exclude the paths the *runtime* writes (they are output, not source),
# and cap the graceful wait so a genuine source edit restarts the server
# instead of wedging it. A killed stream is a visible, recoverable failure;
# a server that accepts connections and never answers is not.
PYTHONPATH="backend:workflows/chinook-assistant" SSL_CERT_FILE="${CERT_FILE}" \
  supervise backend python3 -m uvicorn openstategraph.api.main:app --port 8000 --app-dir backend \
    --reload --reload-dir backend --reload-dir workflows \
    --reload-exclude '*/.openstategraph/*' --reload-exclude '*.eml' \
    --reload-exclude '*/__pycache__/*' --reload-exclude '*.pyc' \
    --reload-exclude '*/.pytest_cache/*' \
    --reload-exclude '*.sqlite' --reload-exclude '*.sqlite-*' \
    --timeout-graceful-shutdown 3

supervise vite npm run dev

echo
echo "editor:  http://localhost:5273"
echo "runtime: http://localhost:8000/api/health"
echo "stop:    scripts/dev.sh stop   ·   status: scripts/status.sh"
