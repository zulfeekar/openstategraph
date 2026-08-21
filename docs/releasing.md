# Releasing

How a change becomes a version on PyPI, who decides, and what to do when it
goes wrong. Maintainers only — contributors want
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

The design goal is one sentence: **everything up to the irreversible step is
automatic and repeatable; the irreversible step waits for a human who has
already seen it work.**

---

## The train

```
 contributor  ──▶  pull request  ──▶  CI (ci.yml)  ──▶  merge to main
                                       every check, no secrets,
                                       identical for forks

 maintainer   ──▶  Actions ▸ "Release PR" ▸ version: 0.3.0     (release-pr.yml)
                        │
                        ▼
                   PR "chore: release v0.3.0"
                   two edits: pyproject version + CHANGELOG date
                        │
                   ┌────┴────┐  merging it is authoring the release,
                   │  MERGE  │  not approving the publish
                   └────┬────┘
                        ▼
 main  ──▶  detect  ──▶  tag v0.3.0  ──▶  build  ──▶  TestPyPI   (release.yml)
            (is this a       (annotated,     (wheel +      (upload,
             prepared         from the       sdist +       --skip-existing)
             release?)        merge commit)  clean-venv
                                             proof)
                        │
                        ▼
                   REHEARSAL — install openstategraph==0.3.0 FROM TestPyPI
                   into an empty venv outside any checkout, and drive it
                        │
                   ┌────┴──────────┐
                   │  HUMAN GATE   │  environment: pypi, required reviewer
                   └────┬──────────┘
                        ▼
                     PyPI  ──▶  GitHub Release (notes from CHANGELOG.md)
```

A pre-release version (`0.3.0rc1`, `a1`, `b1`) stops after the rehearsal: the
`pypi` job's condition reads the version, so the decision lives in the thing
being released rather than in whoever clicked the button.

---

## Where the version lives

| File | Is it the version? | Who edits it |
| --- | --- | --- |
| `backend/pyproject.toml` | **Yes. The only literal.** | `scripts/prepare_release.py`, via the Release PR |
| `openstategraph.__version__` | Derived — `importlib.metadata` reads the installed distribution | nobody |
| `CHANGELOG.md` heading | The same version, and the release notes | a human writes the body; the script dates the heading |
| `package.json` | **No.** The editor is `"private": true` and is published to no registry, so its `version` describes nothing anyone can install. | nobody, until it is published — at which point it needs its own train, not a shared number |

Two literals of the same number is how `text2sql` ended up shipping
`pyproject` 0.4.0 against `__version__` 0.3.0
([`decisions/sdk-practice.md`](decisions/sdk-practice.md) §2). One literal, one
derivation, no reconciliation job.

---

## Cutting a release

1. **Write the notes first.** `CHANGELOG.md` gains a `## X.Y.Z — unreleased`
   section as the work lands; entries go under it in the same pull request as
   the change. Nothing below invents prose.
2. **Actions ▸ Release PR ▸ Run workflow**, version `0.3.0`. It refuses a
   version that is already tagged, already dated, or has an empty section.
3. **Review the release PR.** Two edits, no more. Read the rendered notes in
   the PR body the way a stranger will read them on the PyPI page.
4. **Merge it.** This starts `release.yml`. Nothing is published yet.
5. **Wait for the rehearsal.** It ends with a job summary containing the exact
   `pip install` line it used.
6. **Approve the `pypi` environment** — see the checklist below.
7. **Done.** The GitHub Release appears with the changelog section as its body
   and the wheel + sdist attached.

To rehearse without releasing, prepare `0.3.0rc1`: the train runs end to end,
uploads to TestPyPI, rehearses, and stops. No approval is even requested.

### What the rehearsal actually proves

`scripts/clean_install_proof.sh` is the whole rehearsal, and it runs twice per
release — once on the wheel this repository built, once on the wheel the index
served. It answers two different questions, and it is worth knowing which is
which before trusting a green run.

**Packaging and wiring.** The wheel carries its package data — the editor
bundle, `compile/port_specs.json`, every template, the examples including
`sql-qa`'s database. Installed outside any checkout with `PYTHONPATH` empty,
the templates scaffold, the examples copy with their mounts, `validate` and
`graph` and `serve` work, paths resolve to the *project* rather than into
`site-packages`, the runtime executes a compiled graph, and the editor, the
customer chat and the API all answer under one origin.

**Behaviour** (providers-and-credentials 05). Compiling and answering is not
the same as answering *correctly*, and a green pytest run is silent about the
difference: `pytest.ini` puts a workflow's `tools/` on `sys.path` in the
checkout, so bindings resolve in-tree for a reason an adopter does not have.
Six assertions, none of which needs a credential — *absent* and *wrong* are
testable with no vendor account, and only *valid* is not:

| Guarantee | Where it would break |
| --- | --- |
| Every name in `backend/tests/public_api.txt` imports from the installed package | a public symbol that exists in the source tree and is not shipped (build mode only) |
| A package that arrived without its `tools/` fails `validate` with exit 1, naming the unbound types and the fix | a copied or exported document, which is the normal way one travels |
| User-scoped memory refuses a run the server identified nobody for, and writes nothing | the shared-`anonymous` merge, where two strangers read each other's remembered facts |
| `POST /api/runs` with `user_email` is a 422 | a client naming the person whose memory namespace it wants |
| A missing provider key is a 200 carrying the variable to set, never a 500 and never a blank answer | the first thing a new adopter hits |
| `GET /api/workflows/{slug}` round-trips into `PUT` unchanged | fetch, edit, put back — the first script a customer writes |

The proof's server is started with every provider credential unset, so the
credential assertion cannot pass by quietly calling a real vendor on a
developer's machine. On this hardware the whole script takes about **37
seconds** with the editor bundle already built, and several minutes when it has
to run `npm ci && npm run build` first.

**Still not covered**, so that nobody reads the table as exhaustive: the
CLI-and-library half of `RunResult`'s failure/report split (a legally-empty run
must exit 0), `openstategraph validate`'s exit 1 on a mount cycle, a saved
`settings.recursionLimit` reaching the graph, and `ThreadSummary.failed` on the
wire. Each needs either a run that produces a thread or a fixture the proof
does not yet scaffold — `providers-and-credentials/06`.

### What to check before clicking approve

The gate exists because a version number, once used on PyPI, is burned — a
yank hides a file, it does not free the number. So the question at the gate is
not "is this good?" but **"is this the thing that was tested?"**

- [ ] **The rehearsal job is green**, and its summary names the version you
      intend to publish. It installed from an index, not from a file we built —
      that is what makes it a rehearsal and not a re-run of the build.
- [ ] **The tag `v0.3.0` points at the merge commit of the release PR**, and
      nothing has been pushed to main since that you expected to be in it.
- [ ] **The changelog diff is the one you reviewed** — `git show v0.3.0 -- CHANGELOG.md`.
      Breaking changes are called out in prose, not implied by a version bump.
- [ ] **`docs/stability.md` still tells the truth** if any Tier 1 symbol moved.
- [ ] **No `PLACEHOLDER` remains** in what a stranger will see:
      `grep -rn PLACEHOLDER backend/pyproject.toml site/index.html .github/CODEOWNERS`
- [ ] Optional but cheap: install the TestPyPI build yourself and use it for
      thirty seconds. The command is in the job summary.

---

## One-time setup, by hand

None of this can be configured from a workflow file. Until it exists, the train
runs but does not gate.

### 1. The `pypi` environment — this is the human gate

Settings ▸ Environments ▸ **New environment** ▸ name it exactly `pypi`.

- **Required reviewers**: the maintainer(s). Without this the environment is a
  label and the publish job does not wait for anybody.
- **Deployment branches**: `main` only.
- Description worth pasting in: *"Approving publishes to PyPI. A version number
  cannot be reused. Check the rehearsal job's summary first — docs/releasing.md."*

### 2. Secrets

| Secret | Where | Needed by |
| --- | --- | --- |
| `TEST_PYPI_API_TOKEN` | test.pypi.org ▸ API tokens | `release.yml` ▸ `testpypi` |
| `PYPI_API_TOKEN` | pypi.org ▸ API tokens, project-scoped once the project exists | `release.yml` ▸ `pypi` |

Neither is reachable from a fork: `release.yml` does not run on `pull_request`
at all, and `ci.yml` references no secret anywhere. Scope the PyPI token to the
`openstategraph` project as soon as the first release creates it — the initial
upload needs an account-wide token, and it should be replaced immediately
after.

The successor is **PyPI Trusted Publishing (OIDC)**, which deletes both tokens.
It cannot be configured before the project exists on PyPI under a real
repository. The repository half of that is settled — `backend/pyproject.toml`'s
URLs are real and point at the remote — so the one thing left is the first PyPI
upload (`decisions/sdk-practice.md` recommendation 6).

### 3. Branch protection — the required status checks

Settings ▸ Branches ▸ protect `main` ▸ *Require status checks to pass*. **Add
one check:**

```
ci-success
```

That job (`ci.yml`) fails unless every other job succeeded or legitimately
skipped, so adding a job to its `needs:` list is how a new check becomes
mandatory — no second place to update, and no re-listing when a job is renamed
or gains a matrix.

If you would rather see them individually, require these exact names instead,
and remember to revisit the list whenever `ci.yml` changes:

```
frontend
generated-port-specs
generated-openapi
backend (3.11)
backend (3.13)
clean-install
docs-freshness
e2e
```

**`backend` is a matrix job, and that changes the name you must type.** GitHub
reports one check per leg, `backend (3.11)` and `backend (3.13)`, so requiring
plain `backend` matches nothing and protects less than the page you are looking
at claims to. This is the exact failure mode the paragraph above predicts, and
it caught this document: the matrix was added and the list was not re-read.
Which is the argument for requiring `ci-success` alone.

Also switch on: *Require a pull request before merging* (1 approval),
*Require review from Code Owners*, *Dismiss stale approvals*, and *Require
branches to be up to date*. Do **not** allow force pushes — the release train
tags commits on main and a rewritten history orphans a published tag.

`docs-freshness` only runs on pull requests, so it will show as skipped on
push-to-main runs; `ci-success` accounts for that.

### 4. `CODEOWNERS`

`.github/CODEOWNERS` still ships with `@PLACEHOLDER`. It was written that way
because the checkout had no remote and the handle was not a fact; the remote
and the handle are both facts now, so this is an outstanding edit rather than a
deferral. An unresolvable owner is silently ignored — and, with *Require review
from Code Owners* enabled, blocks every pull request. Replace it before
enabling that setting.

### 5. Labels

`.github/labeler.yml` applies `frontend` `backend` `workflows` `docs` `ci`
`e2e`; the Release PR applies `release`. Create them once:

```bash
for l in frontend backend workflows docs ci e2e release; do
  gh label create "$l" --force
done
```

---

## When it goes wrong

### The rehearsal failed

Nothing was published to PyPI; that is the entire point of the job. The tag,
however, exists — the train tags before it builds, so the artefact always
corresponds to a named commit.

Fix the defect on main, then release the **next** patch version (`0.3.1`).
`0.3.0` is spent on TestPyPI and its tag stays as a record. If you would rather
reuse the number and the tag is only minutes old and nobody has fetched it:

```bash
git tag -d v0.3.0
git push origin :refs/tags/v0.3.0        # delete the remote tag
# fix, merge, then: Actions ▸ Release ▸ Run workflow (resume: false)
```

Deleting a tag anyone may already have fetched is not worth the saved digit.
Prefer the patch bump.

### The rehearsal passed, a later job failed (PyPI upload, GitHub Release)

Re-run the train without re-tagging:

**Actions ▸ Release ▸ Run workflow ▸ `resume: true`.** That skips the tag job
and the freshness tests, rebuilds, re-uploads to TestPyPI (`--skip-existing`
makes that a no-op), rehearses again, and stops at the gate as before.

### The version is already on PyPI

You cannot overwrite it, and deleting a release does not free the number.
The `pypi` job checks this before uploading and fails loudly rather than
letting twine produce a 400.

If the published version is broken:

```bash
# 1. Yank it — installs stop resolving to it, existing pins keep working.
pip install --upgrade twine        # or use the PyPI web UI: Manage ▸ Yank
gh release edit v0.3.0 --title "v0.3.0 (yanked)" 2>/dev/null || true

# 2. Ship the fix as a patch. There is no other move.
#    - fix on main, with a test that fails without it
#    - add "## 0.3.1 — unreleased" to CHANGELOG.md, saying what 0.3.0 broke
#    - Actions ▸ Release PR ▸ 0.3.1
```

Yanking is done from the PyPI web UI (Manage project ▸ Releases ▸ Options ▸
Yank) or with `twine`'s API; there is no `gh` command for it. **Never delete**
a PyPI release — yanking leaves existing pins working, deletion breaks them and
still does not let you reuse the number.

### A tag was pushed by mistake

It publishes nothing. `release.yml` has no tag trigger: the train is started by
a commit on main whose pyproject version is untagged and whose changelog
section is dated. A stray `v9.9.9` is inert.

Remove it anyway, so `git describe` and the release list stay honest:

```bash
git tag -d v9.9.9
git push origin :refs/tags/v9.9.9
```

The reverse failure — the version you want is already tagged, so `detect`
skips — is fixed by deleting that tag (if it was a mistake) or by bumping to
the next version (if it was a real release).

### The changelog entry is wrong

**Before the release PR is merged:** push a commit to the release branch. The
PR body's rendered notes are stale after that, but the job that publishes the
GitHub Release re-reads `CHANGELOG.md` at tag time, so what ships is what is in
the file.

**After the tag exists, before PyPI:** fix `CHANGELOG.md` on main, then re-tag
so the tag and the notes agree — the GitHub Release job checks out the default
branch, but the tag is what people read:

```bash
git tag -f -a v0.3.0 -m "Release v0.3.0"     # only safe pre-publish
git push --force origin v0.3.0
```

**After PyPI:** the PyPI description is frozen for that version — it is built
into the artefact — so it cannot be corrected in place. Fix `CHANGELOG.md` on
main and edit the GitHub Release, which is the copy people actually read:

```bash
python scripts/changelog_section.py 0.3.0 > /tmp/notes.md
gh release edit v0.3.0 --notes-file /tmp/notes.md
```

If the error is *material* — a missing breaking-change warning — say so in the
next version's section too. A correction nobody sees is not a correction.

### The release PR was merged too early

Before the train reaches the gate, cancel the workflow run
(Actions ▸ the run ▸ Cancel), then revert the merge:

```bash
git revert -m 1 <merge-commit>          # restores "unreleased" and the old version
git push origin main
git push origin :refs/tags/v0.3.0       # the tag job may already have run
```

`concurrency: { group: release, cancel-in-progress: false }` means a second
train cannot start while the first is alive, including while it waits at the
gate — so an accidental merge cannot race a deliberate one.

### The gate has been waiting for days

Nothing degrades. The run stays pending until approved or cancelled (GitHub
expires it after 30 days). Rejecting it fails the run cleanly; nothing is
published, and the tag remains for the next attempt via `resume: true`.

---

## Why this and not release-please

`release-please` is the obvious candidate and it was seriously considered — it
implements exactly the shape used here: a bot-authored release PR whose merge
is the human decision. Two facts about *this* repository decided against it.

**1. Our changelog is written, not generated.** `CHANGELOG.md` is a long
document of prose that explains *why* each change happened, with measurements
("78 → 36 distributions"), the reasoning behind each breaking change, and
migration advice. release-please's contribution is generating that file from
commit subjects. Trading a written document for a bulleted list of commit
subjects is a downgrade in the artefact users read most.

**2. Adopting it means changing commit discipline, today, repository-wide.**
The last thirty commit subjects are descriptive and deliberately so — *"RC-01:
generate the port table from TypeScript; the hand copy held 10 of 38 node
types"*. Not one carries a `feat:`/`fix:` prefix. release-please cannot see a
release in any of them: it would open no release PR at all until the convention
is adopted, and the first generated changelog would cover only post-adoption
commits, leaving a visible seam. So the cost is not "add a prefix" — it is
"adopt Conventional Commits and accept a changelog with two halves".

**This is a deferral, not a rejection.** The independent survey in
[`decisions/sdk-practice.md`](decisions/sdk-practice.md) reached the same
verdict from the other direction (recommendation 7: *"our CHANGELOG is
genuinely better prose … this is a 1.0 item, not a now item"*). Adopt it when
the commit rate makes hand-writing the notes the bottleneck. When we do, take
the two things that survey found: the `!`-in-the-**PR-title** rule
(release-please reads the squash commit, not the PR body) and the
`changelog-sections` table. And per its recommendation 10, let it write
`backend/pyproject.toml` only — keep `__version__` derived.

Until then, `release-pr.yml` provides the mechanism release-please would have
provided (a reviewable release commit, a dated changelog, an automatic tag)
with the notes hand-written, and **commit messages stay as they are**. No
contributor has to learn a prefix table to land a fix.

### One deliberate deviation from `decisions/sdk-practice.md`

That document's recommendation 11 is *"keep the tag as the release trigger"*.
This design does not, and the reason is that the property it was protecting is
better served the new way.

The property was: *the pre-release decision should live in the artefact, not in
whoever clicked the button.* Under a tag trigger it lived in the tag's shape.
It now lives in the **version string in `backend/pyproject.toml`**, which is
strictly stronger — a tag can disagree with the version it claims to name
(tagging `v0.3.0` on a commit whose pyproject says `0.2.9` publishes `0.2.9`),
and a version string cannot disagree with itself. `detect` reads the version
from the artefact and derives everything, tag included, from it.

Three further reasons the tag trigger could not stay:

1. **The owner's requirement is a reviewable release commit.** A tag trigger
   makes the version bump and the changelog date a manual local edit with no
   review artefact. Once a release PR exists, *someone has to push a tag after
   merging it* — which is precisely the tag-vs-release-PR reconciliation that
   recommendation 11 cited as `deepagents`' fifteen troubleshooting sections.
   Automating the tag inside the run is how that class of failure is avoided,
   not imported.
2. **A tag pushed by `GITHUB_TOKEN` does not start another workflow.** So a
   design where a workflow tags and a tag-triggered workflow publishes silently
   does nothing, and the usual fix is a long-lived personal access token with
   far broader write scope than this needs.
3. **Idempotence.** "Release when the version is untagged and the changelog is
   dated" is self-limiting: re-running it is a no-op, and an ordinary merge to
   main is inert. No branch naming convention, no release-commit sniffing.

Everything else in that document's list stands, and the cheap items it flagged
are taken here: `concurrency` on `ci.yml` (recommendation 3) and `CODEOWNERS`
(recommendation 9). Recommendation 4 — testing the Python versions we advertise
— was deferred by this page to avoid renaming status checks in the same change
that asks you to configure them. **It has since landed**: `ci.yml`'s `backend`
job carries `python-version: ["3.11", "3.13"]`, which is why the individual
check names above are `backend (3.11)` and `backend (3.13)`. With `ci-success`
required instead, it needed no branch-protection edit, exactly as predicted.

---

## What has run, and what still has not

**Until 2026-08-15 this section said the opposite**, and it was true when
written: no remote, so nothing above had ever executed. The remote `beta`
exists now, and the train has run.

**The rc1 rehearsal happened and it worked.** `v0.3.0rc1` is tagged on the
remote, and the run that made it carried `detect → tag → build → testpypi →
rehearsal` all green, with `pypi` and `github-release` correctly **skipped**
because a pre-release stops before the irreversible step. That is exactly the
shape this document prescribes for a first release, and it is no longer a
prediction.

`ci.yml` and `release.yml` both run on every push to `main`; `triage.yml` has
run on a pull request. So the gates on this page describe observed behaviour,
not intent.

Three things still have not executed, and they are named rather than implied:

| | State |
| --- | --- |
| The **`pypi` job** | never run. `0.3.0rc1` is on TestPyPI only, and the human gate has never been clicked |
| `openwiki-update.yml` | zero runs, ever |
| `pages.yml` (*Deploy landing page*) | four runs, four failures — `HttpError: Not Found` from `actions/configure-pages`. See production-ready ticket 28 |

`docs-freshness` is `if: github.event_name == 'pull_request'` and this
repository pushes straight to `main`, so it skips on nearly every run by
design — `ci-success` accounts for that, and a skip is not a gap.
