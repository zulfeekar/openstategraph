#!/usr/bin/env bash
# Carry work from the private repository to the public one, in the order that
# makes CI useful.
#
# WHY THIS EXISTS
#
# On 2026-09-07 the public repository went red twice within twenty minutes of
# becoming public, both times for a defect the private repository's own CI
# would have caught — because the push to public happened first and CI ran
# afterwards, in front of whoever was watching. Nothing was wrong with the
# gates. The order was wrong.
#
# WHY IT IS A CHERRY-PICK AND NOT A PUSH
#
# The two repositories have unrelated histories on purpose: public `main` began
# as one squashed parentless commit carrying no private history. So there is no
# fast-forward between them, ever, and `git push public main:main` is rejected.
# The bridge is `public-demo`, a local branch whose first commit is the public
# release commit and whose every later commit is a cherry-pick.
#
# WHICH COMMITS ARE OUTSTANDING IS DERIVED, NOT REMEMBERED
#
# `git cherry-pick -x` writes `(cherry picked from commit <sha>)` into the
# message it creates. That trailer is the record, so the bridge branch itself
# says what has already been carried and no file has to be kept in step with
# it. A list somewhere else would be a second copy of one fact.
set -euo pipefail

BETA_REMOTE="${BETA_REMOTE:-beta}"
PUBLIC_REMOTE="${PUBLIC_REMOTE:-public}"
SOURCE_BRANCH="${SOURCE_BRANCH:-main}"
BRIDGE_BRANCH="${BRIDGE_BRANCH:-public-demo}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

cd "$(git rev-parse --show-toplevel)"
started_on="$(git branch --show-current)"
restore() { git switch -q "$started_on" 2>/dev/null || true; }
trap restore EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- preconditions

# A cherry-pick needs a clean tree, and this script deliberately does not clean
# it for you. Other sessions edit this checkout; `git stash` here would swallow
# somebody else's uncommitted work and leave no trace of having done it.
if [ -n "$(git status --porcelain)" ]; then
  say "The working tree is not clean. Commit or set these aside yourself:"
  git status --short
  echo
  echo "This script will not stash. Another session may own these changes."
  exit 1
fi

[ "$(git branch --show-current)" = "$SOURCE_BRANCH" ] || {
  echo "Run this from $SOURCE_BRANCH (you are on $(git branch --show-current))."; exit 1; }

command -v gh >/dev/null || { echo "gh is required to read CI."; exit 1; }

# --------------------------------------------------------------- 1. push private

head_sha="$(git rev-parse HEAD)"
say "1/4  Pushing $SOURCE_BRANCH to $BETA_REMOTE ($(git rev-parse --short HEAD))"
if [ "$DRY_RUN" = 1 ]; then
  echo "     (dry run — not pushing)"
else
  git push "$BETA_REMOTE" "$SOURCE_BRANCH"
fi

# ------------------------------------------------------------------ 2. wait for CI

beta_repo="$(git remote get-url "$BETA_REMOTE" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
say "2/4  Waiting for CI on $beta_repo"

if [ "$DRY_RUN" = 1 ]; then
  echo "     (dry run — not waiting)"
else
  # The run has to exist before it can be watched: GitHub takes a few seconds to
  # create it, and asking too early finds the *previous* commit's run and
  # reports its verdict, which is the one failure mode a gate like this must not
  # have.
  run_id=""
  for _ in $(seq 1 30); do
    run_id="$(gh run list --repo "$beta_repo" --workflow ci.yml \
      --commit "$head_sha" --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
    [ -n "$run_id" ] && break
    sleep 5
  done
  [ -n "$run_id" ] || { echo "No CI run appeared for $head_sha after 150s."; exit 1; }

  echo "     run $run_id — this takes about eleven minutes"
  if ! gh run watch "$run_id" --repo "$beta_repo" --exit-status --interval 30 >/dev/null; then
    say "CI failed on $beta_repo. Nothing was carried to public."
    gh run view "$run_id" --repo "$beta_repo" | sed -n '/^JOBS/,/^$/p'
    exit 1
  fi
  echo "     green"
fi

# ------------------------------------------------------- 3. cherry-pick what is new

say "3/4  Finding commits not yet on $BRIDGE_BRANCH"

git rev-parse --verify -q "$BRIDGE_BRANCH" >/dev/null || {
  echo "$BRIDGE_BRANCH does not exist. It is the bridge branch whose first commit"
  echo "is the public release commit; create it before using this script."; exit 1; }

# Everything the bridge already carries, by the sha the -x trailer names.
carried="$(git log "$BRIDGE_BRANCH" --format=%B | sed -nE 's/^\(cherry picked from commit ([0-9a-f]+)\)$/\1/p')"

# Where to start walking. The bridge's root commit is the squash that opened
# the public repository, and its *tree* is byte-identical to the private commit
# it was taken from — so the baseline is derivable rather than remembered. A
# number written down here would be a third copy of a fact the two repositories
# already agree on, and it would rot at the next squash.
bridge_root="$(git rev-list --max-parents=0 "$BRIDGE_BRANCH")"
bridge_tree="$(git rev-parse "$bridge_root^{tree}")"
baseline="$(git log "$SOURCE_BRANCH" --format='%H %T' | awk -v t="$bridge_tree" '$2 == t { print $1; exit }')"

if [ -z "$baseline" ]; then
  echo "Cannot find the commit on $SOURCE_BRANCH whose tree the public squash was"
  echo "taken from (tree $bridge_tree). Set RELEASE_BASE to it and run again."
  baseline="${RELEASE_BASE:-}"
  [ -n "$baseline" ] || exit 1
fi
echo "     baseline $(git rev-parse --short "$baseline") — the commit public was cut from"

outstanding=()
while read -r sha; do
  [ -n "$sha" ] || continue
  printf '%s\n' "$carried" | grep -q "^$sha$" || outstanding+=("$sha")
done < <(git log "$baseline..$SOURCE_BRANCH" --format=%H --reverse)

if [ ${#outstanding[@]} -eq 0 ]; then
  say "Nothing outstanding. Public is up to date."
  exit 0
fi

echo "     ${#outstanding[@]} commit(s) to carry:"
for sha in "${outstanding[@]}"; do
  printf '       %s  %s\n' "$(git rev-parse --short "$sha")" "$(git log -1 --format=%s "$sha")"
done

if [ "$DRY_RUN" = 1 ]; then
  say "(dry run — stopping before the cherry-pick)"
  exit 0
fi

git switch -q "$BRIDGE_BRANCH"
for sha in "${outstanding[@]}"; do
  # `--allow-empty` because the docs-freshness escape hatch is an empty commit
  # by design, and it has to reach public with the rest.
  if ! git cherry-pick -x --allow-empty "$sha"; then
    say "Cherry-pick of $(git rev-parse --short "$sha") conflicted."
    echo "Resolve it, then \`git cherry-pick --continue\`, then run this again."
    exit 1
  fi
done

# ---------------------------------------------------------------- 4. push public

say "4/4  Pushing $BRIDGE_BRANCH to $PUBLIC_REMOTE:main"
git push "$PUBLIC_REMOTE" "$BRIDGE_BRANCH:main"

public_repo="$(git remote get-url "$PUBLIC_REMOTE" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
say "Done. Public is $(git rev-parse --short "$BRIDGE_BRANCH")."
echo "Watch it: gh run list --repo $public_repo --limit 3"
