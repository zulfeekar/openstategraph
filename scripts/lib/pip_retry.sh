# scripts/lib/pip_retry.sh — bounded polling for index propagation delay.
#
# `pip download`/`pip install` against a package index minutes after upload
# can fail with "Could not find a version that satisfies the requirement",
# naming only the versions that existed before the upload — even though the
# index's own JSON API already lists the new one (launch-readiness ticket 37).
# That is index propagation delay, not a nonexistent release, so the caller
# must poll instead of failing on the first miss.
#
# This does NOT replace `--no-cache-dir` — that addresses a *different* cause
# (pip's local cache of a simple-index page fetched before the upload) and is
# the caller's job to pass in the pip invocation itself. Both can be in play
# at once; this file only bounds the wait for server-side propagation.
#
# Usage:
#   source scripts/lib/pip_retry.sh
#   pip_retry "openstategraph==0.3.0rc5" python3 -m pip install --no-cache-dir ...
#
# The first argument is a human-readable description of what is being waited
# for, used only in messages. Every remaining argument is the command to run.
#
# Env:
#   OSG_INDEX_RETRIES       attempts before giving up (default 10)
#   OSG_INDEX_RETRY_DELAY   seconds between attempts (default 15)
#
# A command that never succeeds still fails the caller (`return 1`) once the
# attempt ceiling is reached — this is a bounded wait, never a skip.
pip_retry() {
  local desc="$1"
  shift
  local retries="${OSG_INDEX_RETRIES:-10}"
  local delay="${OSG_INDEX_RETRY_DELAY:-15}"
  local attempt=1

  until "$@"; do
    if [ "$attempt" -ge "$retries" ]; then
      echo "$desc never became available from the index after $retries attempts (${delay}s apart) — giving up" >&2
      return 1
    fi
    echo "    not visible yet for $desc (attempt $attempt/$retries) — the index is catching up"
    attempt=$((attempt + 1))
    sleep "$delay"
  done
}
