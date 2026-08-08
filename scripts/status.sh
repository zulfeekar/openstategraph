#!/usr/bin/env bash
# Answers "is the stack up?" in one command — ticket 57.
check() { # name, url
  if out=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$2"); then
    [ "$out" = "200" ] && echo "✔ $1 up ($2)" && return
  fi
  echo "✘ $1 DOWN ($2)"
}
check "runtime" "http://localhost:8000/api/health"
check "editor " "http://localhost:5273"
