> **Who this page is for:** you are the maintainer taking this repository
> public, or you are changing one of its GitHub settings and want to know what
> depends on it.

# Public repository settings — the checklist

Every decision below is a **settings page, not a file**. That is the whole
reason this page exists: a settings change produces no diff, no review comment
and no test that can go red, so the only record of what the repository is
supposed to be configured as is a document somebody wrote down. The workflows
already explain the settings *they* rely on — `ci.yml`'s header on fork safety,
`triage.yml`'s capitalised rule about `pull_request_target` — and the
repository-level ones had no such paragraph anywhere until this page.

Tick the rows in order. Each names the setting, the value it must have, and
**what breaks if it does not**.

**Every claim about GitHub's own behaviour on this page carries the URL it came
from.** Nothing here is asserted from memory, because a maintainer acting on a
half-remembered rule about fork secrets is the failure mode this page is meant
to prevent.

**This page does not repeat [Releasing](../releasing.md).** The release train's
own one-time setup — the `pypi` environment, the two PyPI tokens, the exact
required status check — is written there, once, and the rows below link to it
rather than restating it. (`docs/README.md` states that rule for the whole set.)

## 1. Issues

| | |
| --- | --- |
| **Where** | Settings ▸ General ▸ *Features* ▸ **Issues**, selected |
| **Breaks if not** | there is no door at all. A user's platform-gap report has nowhere to land, and the maintainer board's GitHub tab has nothing to read |
| **Docs** | [Disabling issues](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/disabling-issues) — *"Under 'Features', deselect **Issues**"*; the same checkbox, selected, is how it is on. The dropdown under it can also restrict issues to collaborators only, which for this repository is the wrong value |

Issues already added stay: *"If you decide to enable issues again in the
future, any issues that were previously added will be available."*

## 2. Issue templates

`.github/ISSUE_TEMPLATE/` holds `bug_report.yml`, `feature_request.yml` and
`config.yml` today. These are files, so they are reviewable and are not
settings — the only settings-shaped part is `config.yml`'s
`blank_issues_enabled`, which decides whether a contributor can bypass the
chooser.

- Templates and forms *"must"* live in `.github/ISSUE_TEMPLATE`, and the
  chooser is customised *"by adding a `config.yml` file to the
  `.github/ISSUE_TEMPLATE` folder"* —
  [Configuring issue templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository).

**A third template — the platform gap — is not written yet, and this page will
not guess its fields.** It is the one an automated door would file into, so its
fields have to be exactly the report allowlist and nothing else: version, kind,
node/tool type ids involved, the door that refused, the refusal text, the check
id, the first traceback line, OS, Python. That list has no schema behind it in
this repository yet, and a template written before the schema is a second
spelling of a contract that has no first one — which is the duplication rule
this project applies to every hand-mirrored wire type. It is filed as
`team-board-and-gap-reports/05` and `07`, and the template lands with the pin
that holds it to the model.

## 3. Actions — workflow permissions

| | |
| --- | --- |
| **Where** | Settings ▸ Actions ▸ General ▸ *Workflow permissions* |
| **Value** | **Read repository contents and packages permissions** (the restricted default) |
| **Breaks if not** | every workflow's token starts with write access to the whole repository, so a compromised action in any job can push to `main`. All six workflows here already declare what they need — `ci.yml` and `triage.yml` top-level `contents: read`, write granted per job in `release.yml`, `release-pr.yml` and `openwiki-update.yml` — so the permissive default buys this repository nothing and costs it the blast radius |
| **Docs** | [Managing GitHub Actions settings for a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository). *"The permissions for the `GITHUB_TOKEN` are initially set to the default setting for the enterprise, organization, or repository"* — [workflow syntax ▸ `permissions`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions) |

### 3a. "Allow GitHub Actions to create and approve pull requests" — the row with a conflict in it

Same settings page, separate checkbox, and this repository's two positions on
it disagree. **Record which one you chose and why; do not discover this from a
failing run.**

- **Off** is the posture the rest of this page assumes, and it is what an
  Actions-hardening checklist asks for.
- **On** is what `release-pr.yml` and `openwiki-update.yml` need to do the one
  thing each exists to do. Both have failed on exactly this, with GitHub's own
  message *"GitHub Actions is not permitted to create or approve pull
  requests"*, and a workflow cannot grant itself past it: `release-pr.yml`
  already declares `pull-requests: write`. The account is in
  [Releasing ▸ *The first half of the train is broken*](../releasing.md).

There is no third value. Either the box is ticked and two workflows work, or it
is not and preparing a release is the by-hand path `docs/releasing.md`
describes — which is how `0.3.0rc1` was actually prepared.

## 4. Fork pull requests get no secrets

This one is **not a setting**. It is a property GitHub enforces, and `ci.yml`'s
header already leans on it in writing, so it belongs on the checklist as a fact
to *verify you have not undermined* rather than a box to tick:

> *"With the exception of `GITHUB_TOKEN`, secrets are not passed to the runner
> when a workflow is triggered from a forked repository."*
> — [Using secrets in GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

The way to lose it is to move a job from `pull_request` to
`pull_request_target`, which runs with the base branch's privileges against an
untrusted diff. `ci.yml` says so at the top and `triage.yml` — the one workflow
here that does use `pull_request_target` — states in capitals that it never
checks out, builds or executes the pull request's code. **Breaks if not:** a
fork's pull request can read every secret in the table below.

## 5. Branch protection on `main`

| | |
| --- | --- |
| **Where** | Settings ▸ Branches ▸ protect `main` |
| **Value** | *Require a pull request before merging* with *Require review from Code Owners*; *Require status checks to pass before merging* with the single check `ci-success` |
| **Breaks if not** | a push straight to `main` publishes unreviewed code, and `ci-success` — the job whose whole purpose is to fail unless every other job passed — gates nothing |
| **Docs** | [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches): required status checks *"must have a `successful`, `skipped`, or `neutral` status"*; with code-owner review, *"any pull request that affects code with a code owner must be approved by that code owner"* |

**Why one check and not a list** — and the trap with the matrix job — is in
[Releasing ▸ *Branch protection*](../releasing.md). Read the names out of
`ci-success`'s `needs:` list, never out of a page.

### 5a. CODEOWNERS resolves, or the review requirement is theatre

`.github/CODEOWNERS` exists and its catch-all owner is still literally
`@PLACEHOLDER`. GitHub's rule: *"If you specify a user or team that doesn't
exist or has insufficient access, a code owner will not be assigned"*
([About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners),
which also fixes the file's three legal locations: `.github/`, the repository
root, or `docs/`). So *Require review from Code Owners* over an unresolvable
owner requests nobody. Before the repository is public:

```bash
grep -rn PLACEHOLDER .github/CODEOWNERS backend/pyproject.toml site/index.html
```

## 6. Secrets and variables

Settings ▸ Secrets and variables ▸ Actions. **This table is a census, not a
wish list** — a test asserts it names exactly the `secrets.*` and `vars.*`
references that exist in `.github/workflows/`, in both directions, so a
workflow cannot start needing a secret nobody was told to set. That is the
`openwiki-update.yml` failure this repository has been running on a schedule
and losing every time.

**Names only. No value of any kind belongs on this page, or in any file in
`docs/`.**

<!-- secret-census:start -->

| Secret | Read by | Breaks if unset |
| --- | --- | --- |
| `OPENWIKI_API_KEY` | `openwiki-update.yml` | the scheduled wiki refresh fires and fails, every time, in about 40 seconds. It is the standing example |
| `TEST_PYPI_API_TOKEN` | `release.yml` ▸ `testpypi` | the rehearsal cannot upload, so the human gate is never reached |
| `PYPI_API_TOKEN` | `release.yml` ▸ `pypi` | the publish step fails after the human has already approved it |
| `GITHUB_TOKEN` | `triage.yml` | nothing — **you do not set this one.** GitHub provides it per run; it is listed because it appears in a workflow and the census is derived, and because it is the one secret a fork's pull request *does* receive |

| Variable | Read by | Breaks if unset |
| --- | --- | --- |
| `OPENWIKI_PROVIDER` | `openwiki-update.yml` | the refresh has a key and no provider to send it to |
| `OPENWIKI_MODEL_ID` | `openwiki-update.yml` | same run, same failure — the two are set together or not at all |

<!-- secret-census:end -->

Where each token is minted, and why the PyPI one should be project-scoped as
soon as a project exists to scope it to, is in
[Releasing ▸ *Secrets*](../releasing.md).

## 7. Environments

Settings ▸ Environments. One environment, `pypi`, with **required reviewers** —
*"Only one of the required reviewers needs to approve the job for it to
proceed"*
([Managing environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)).
Without it the environment is a label and `release.yml`'s publish job waits for
nobody. Deployment branches: `main` only. The full description to paste in is
in [Releasing ▸ *The `pypi` environment*](../releasing.md).

## 8. Pages

| | |
| --- | --- |
| **Where** | Settings ▸ Pages ▸ *Build and deployment* ▸ **Source: GitHub Actions** |
| **Breaks if not** | `pages.yml` fails at `actions/configure-pages` with `HttpError: Not Found` — which is what every run of it has done so far (`production-ready/28`) |
| **Docs** | [Configuring a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) — *"Under 'Build and deployment', under 'Source', select **GitHub Actions**"* |

`pages.yml` needs no secret: it declares `pages: write` and `id-token: write`
in its own `permissions:` block and deploys through the `github-pages`
environment.

## What is deliberately not here

The credential map — which key lives where, who holds which read account, when
each is rotated — is **not in `docs/`** and never will be. It holds no secret
value either, but it is a description of where our credentials live and what
each one can do, which is not a thing to publish. It is a private runbook
(`team-board-and-gap-reports/10`).
