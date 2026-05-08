---
name: release-with-gh
description: Create and verify GitHub Releases from terminal with GitHub CLI for this repository. Use when the user asks to cut, publish, or verify a release/tag with gh.
disable-model-invocation: true
---

# Release With GH

Use this skill to execute a safe, repeatable release flow for `RiccardoDalFiume/bayrol-ha-rdf`.

## Preconditions

- `gh` is installed and available in PATH.
- User is authenticated (`gh auth status`).
- User confirms the target version tag (`vX.Y.Z`).
- Release should normally be created from `main`.

## Workflow

Copy this checklist and track progress:

```text
Release progress:
- [ ] Confirm version tag with user
- [ ] Validate clean repository state
- [ ] Update local main branch
- [ ] Create and push annotated tag
- [ ] Create GitHub release with generated notes
- [ ] Verify release existence and summarize result
```

### 1) Confirm version

Ask for the exact version if missing. Use semantic versioning with `v` prefix.

### 2) Validate state

Run:

```bash
git status
git branch --show-current
gh auth status
```

Guardrails:

- Do not continue if auth fails.
- Do not create releases from dirty trees unless user explicitly confirms.
- Do not force-push tags.

### 3) Sync branch

Run:

```bash
git checkout main
git pull origin main
```

### 4) Create and push tag

Use this pattern:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

### 5) Create release

Default command:

```bash
gh release create vX.Y.Z \
  --repo RiccardoDalFiume/bayrol-ha-rdf \
  --title "vX.Y.Z" \
  --generate-notes \
  --target main
```

Optional flags:

- `--draft` when user wants a draft release.
- `--prerelease` for beta/rc releases.

### 6) Verify and report

Run:

```bash
gh release view vX.Y.Z --repo RiccardoDalFiume/bayrol-ha-rdf
gh release list --repo RiccardoDalFiume/bayrol-ha-rdf --limit 5
```

Report back:

- release tag
- release URL
- whether release is draft/prerelease/final
- any errors or follow-up actions

## Failure handling

- If `tag already exists`, stop and ask whether to use a new version.
- If `403` or permission errors occur, ask user to verify repository write access.
- If the release exists but is incorrect, ask whether to edit release notes or create a new patch tag.
