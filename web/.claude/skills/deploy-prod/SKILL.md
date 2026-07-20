---
name: deploy-prod
description: Walk through the staging → main release checklist (SEO tests, manual QA verification, changelog entry + version bump, push, print compare URL)
---

# Deploy prod

Run before merging `staging` into `main` (~monthly cadence). This skill is a
gated checklist: hard gates block the release, soft gates print a warning and
ask the user.

The user does **not** use the GitHub CLI — never run `gh pr create`. Stop at
"push staging + print the compare URL" and let the user open the PR manually.

## Steps

Run them in order. Stop and report to the user the moment any **hard gate**
fails. For **soft gates**, ask the user whether to proceed before continuing.

### 1. Verify git state — hard gate

- `git rev-parse --abbrev-ref HEAD` must return `staging`. If not, stop and
  tell the user to switch.
- `git status --porcelain` must be empty. If not, stop — do not stash, do
  not commit on the user's behalf.
- `git fetch origin` then compare `staging` vs `origin/staging` with
  `git rev-list --left-right --count origin/staging...staging`. If `staging`
  is behind, stop and tell the user to pull.

### 2. Run automated SEO tests — hard gate

Run `pnpm test:seo` (this builds + starts on :3100 + runs the suite).
If anything fails, stop and surface the failing URL(s) to the user. Do
not attempt to fix.

### 3. Check manual mobile QA was run recently — soft gate

Look for the most recent file in `docs/manual-tests/runs/`. The filename is
the run date (`YYYY-MM-DD.md`).

- If no file exists, or the most recent one is older than 7 days, warn the
  user and ask whether to proceed without a fresh QA run.
- Briefly grep the file for unresolved `❌` markers. If any are present,
  surface them and ask whether to proceed.

### 4. Show the release diff — informational

Run `git log main..staging --oneline` and paste the output back to the
user so they can sanity-check what's being released. No gate — just visibility.

### 5. Write the changelog entry — action (needs review)

Turn the release diff into a new `CHANGELOG.md` entry and a matching
version bump. The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [SemVer](https://semver.org/).

1. Read the current version from `package.json` (`version` field) — it
   always matches the latest `CHANGELOG.md` heading.
2. Decide the next version from the nature of `git log main..staging`:
   - **minor** (`x.Y.0`) — any new user-facing feature or capability
     (`Added`, or a substantial `Changed`).
   - **patch** (`x.y.Z`) — only bug fixes, copy tweaks, refactors, deps,
     or internal changes (`Fixed` / small `Changed`).
   When it's genuinely ambiguous, propose one and say why; let the user
   pick.
3. Draft the entry under a new `## [X.Y.Z] - YYYY-MM-DD` heading (use
   today's date), grouping bullets under `Added` / `Changed` / `Fixed` as
   the existing entries do. Write for users, not commit-by-commit — merge
   related commits, drop noise (merge commits, "small fixes", tooling).
   Move anything under `## [Unreleased]` into the new entry.
4. Bump `version` in `package.json` to the same `X.Y.Z`.
5. **Show the user the proposed version + the drafted entry and wait for
   their approval.** Do not commit yet. Once they approve (applying any
   edits they ask for), commit both files together:

   ```
   git add CHANGELOG.md package.json
   git commit -m "Release X.Y.Z"
   ```

   This is the one commit this skill makes on the user's behalf, and only
   after explicit approval. If the user declines, leave the files written
   to disk and stop.

### 6. Push staging — action

- `git push origin staging` (only if local is ahead of `origin/staging` —
  step 1's check plus the release commit from step 5 will have established
  this).
- Skip if there's nothing to push.

### 7. Print the compare URL and stop

Derive the repo path from `git remote get-url origin` (handles both
`git@github.com:OWNER/REPO.git` and `https://github.com/OWNER/REPO.git`).
Print:

```
Open the PR here:
https://github.com/<OWNER>/<REPO>/compare/main...staging
```

Then **stop**. Do not run `gh pr create`. Do not push to `main`. Do not
merge. The user creates the PR by hand.

## What this skill does not do

- Create the PR (no `gh` CLI per user preference).
- Merge to `main` or trigger a deployment.
- Run lint / typecheck — `pnpm test:seo` already runs `next build` which
  covers compilation. If you want stricter gating, add lint/tsc here later.
