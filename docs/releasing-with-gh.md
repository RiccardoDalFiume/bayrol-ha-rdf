# Releasing from Terminal with GitHub CLI

This guide describes how to create a new GitHub Release for this repository using terminal commands and `gh`.

## Prerequisites

- `gh` installed (`gh --version`)
- `gh` authenticated (`gh auth status`)
- A clean working tree (or intentional pending changes)
- Release version decided using semantic versioning, for example `v0.3.0`

Repository used in examples: `RiccardoDalFiume/bayrol-ha-rdf`

## 1) Prepare local branch

```powershell
git checkout main
git pull origin main
git status
```

Expected result: branch is up to date and there are no unexpected uncommitted changes.

## 2) Review commits for release notes input

```powershell
git log --oneline --decorate -20
```

Use this output to decide the release title and check what should be highlighted.

## 3) Create and push the release tag

Set your new version once and reuse it:

```powershell
$Version = "v0.3.0"
```

Create an annotated tag:

```powershell
git tag -a $Version -m "Release $Version"
```

Push the tag:

```powershell
git push origin $Version
```

Verify:

```powershell
git tag --list $Version
git ls-remote --tags origin $Version
```

## 4) Create the GitHub Release with `gh`

Generate release notes automatically from merged PRs/commits:

```powershell
gh release create $Version `
  --repo RiccardoDalFiume/bayrol-ha-rdf `
  --title $Version `
  --generate-notes `
  --target main
```

Useful variants:

- Draft release:

```powershell
gh release create $Version --repo RiccardoDalFiume/bayrol-ha-rdf --title $Version --generate-notes --target main --draft
```

- Pre-release:

```powershell
gh release create $Version --repo RiccardoDalFiume/bayrol-ha-rdf --title $Version --generate-notes --target main --prerelease
```

- Attach assets:

```powershell
gh release create $Version `
  --repo RiccardoDalFiume/bayrol-ha-rdf `
  --title $Version `
  --generate-notes `
  --target main `
  ".\dist\bayrol-package.zip"
```

## 5) Verify release creation

```powershell
gh release view $Version --repo RiccardoDalFiume/bayrol-ha-rdf
gh release list --repo RiccardoDalFiume/bayrol-ha-rdf --limit 5
```

This confirms the release exists and is visible to downstream checks.

## 6) HACS and CI expectations

- HACS validation expects the repository to have at least one GitHub Release.
- `hassfest` and HACS workflows run independently; keep both green before publishing more changes.
- If a workflow fails after a release, inspect Actions logs and publish a follow-up patch release (`vX.Y.(Z+1)`) when needed.

## Troubleshooting

- `gh: command not found`
  - Install GitHub CLI and reopen terminal.
- `gh auth status` reports not logged in
  - Run `gh auth login` and complete browser login.
- `HTTP 403` or permission denied
  - Ensure your account has write permissions on the repository.
- `tag already exists`
  - Choose the next version (`vX.Y.Z`) or delete/recreate tag only if you intentionally want to replace it.
- release command opens editor unexpectedly
  - Add `--generate-notes` or `--notes "..."` explicitly to avoid interactive prompts.

## Recommended quick release checklist

- [ ] `git status` is clean
- [ ] On `main` and updated from `origin/main`
- [ ] Tag created and pushed
- [ ] Release created with `gh release create`
- [ ] Release visible with `gh release view`
- [ ] CI workflows are green
