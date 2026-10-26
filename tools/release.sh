#!/usr/bin/env bash
# release.sh - release nejomibot: version, changelog, tag and GitHub release.
#
# Usage: tools/release.sh patch|minor|major
#
# For now, patch only: nejomibot stays on 0.99.x until the owner says it
# moves to 1.0, and minor and major stop with an error.
#
# Releases main as it is on GitHub, once CI has passed on it. It moves the
# version in pyproject.toml and uv.lock up a patch (0.93.4 to 0.93.5), minor
# (0.94.0) or major (1.0.0) version, makes CHANGELOG.md's Unreleased section
# that version's, dated today, commits and tags that, both signed, and pushes
# them. Then it publishes the release on GitHub, with the section as its
# notes, which starts .github/workflows/release.yml: that builds the image,
# pushes it to the registries, makes README.md its page on Docker Hub, and
# with PYPI_PUBLISH set, publishes the package on PyPI.
# The script waits for it; Ctrl-C stops only the waiting.
#
# If anything fails, fix it and run the script again. Before the push, a
# failure or Ctrl-C puts everything back as it was. After it, the next run
# publishes the version that was pushed, not a new one. A published release
# stays: if one is broken, release a fixed one, as some may run its image.
#
# Needs uv, gh logged in to GitHub (gh auth login), and git set up to sign.
# The script keeps no credentials: git and gh have them.

set -euo pipefail

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# notes VERSION: the changelog's section for VERSION, or for Unreleased,
# without its heading.
notes() {
  awk -v version="$1" '$1 == "##" { if (found) exit; found = ($2 == version); next } found' CHANGELOG.md
}

# wait_for WORKFLOW COMMIT: wait for the workflow's run on the commit, and
# stop if it failed.
wait_for() {
  local run=
  for _ in {1..30}; do # GitHub lists a run a few seconds after the push
    run=$(gh run list --workflow "$1" --commit "$2" --limit 1 --json databaseId --jq '.[].databaseId')
    [[ -n $run ]] && break
    sleep 2
  done
  [[ -n $run ]] || die "GitHub has no $1 run for $2"
  gh run watch --compact --exit-status "$run" ||
    die "$1 failed: gh run view $run --log-failed shows why, gh run rerun $run --failed runs it again"
}

# publish VERSION: publish the release of the tag vVERSION, and wait for
# its image.
publish() {
  echo "==> Publishing $1 on GitHub"
  gh release create "v$1" --verify-tag --title "$1" --notes "$(notes "$1")" ||
    die "Publishing $1 failed: run this again to publish it"
  echo "==> Waiting for the image to be built and pushed, and its page (Ctrl-C stops only the waiting)"
  wait_for release.yml "$(git rev-parse "v$1^{commit}")"
  echo "==> Released $1"
}

cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.."
case "$*" in
  patch | minor | major) ;;
  -h | --help)
    sed -n '2,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
    exit 0
    ;;
  *) die "Usage: tools/release.sh patch|minor|major (see --help)" ;;
esac
# The owner's decision, 2026-10-19: 0.99.x until they say it's time for 1.0.
# Take this out then.
[[ $1 == patch ]] ||
  die "No $1 release for now: nejomibot stays on 0.99.x until the owner says it moves to 1.0, so tools/release.sh patch"
gh auth status >/dev/null 2>&1 || die "gh isn't logged in to GitHub: gh auth login"
git fetch --quiet --tags origin

# The version in pyproject.toml is the last release's, unless publishing it
# failed: then publish it now.
version=$(uv version --short)
git rev-parse --quiet --verify "refs/tags/v$version" >/dev/null ||
  die "pyproject.toml has $version, which has no tag v$version: set it back to the last release's"
releases=$(gh release list --json tagName --jq '.[].tagName')
if ! grep -qx "v$version" <<<"$releases"; then
  echo "==> v$version is tagged but not published: publishing it, not a new version"
  git push --quiet origin "v$version"
  publish "$version"
  exit 0
fi

echo "==> Checking that main is as on GitHub, and that CI passed on it"
[[ $(git branch --show-current) == main ]] || die "Not on main: git switch main"
git diff --quiet HEAD || die "There are uncommitted changes: commit or stash them"
[[ $(git rev-parse HEAD) == "$(git rev-parse origin/main)" ]] ||
  die "main differs from GitHub's: pull or push first"
grep -q '^- ' <<<"$(notes Unreleased)" || die "CHANGELOG.md has nothing under ## Unreleased"
wait_for ci.yml "$(git rev-parse HEAD)"

version=$(uv version --bump "$1" --dry-run --short)
if git rev-parse --quiet --verify "refs/tags/v$version" >/dev/null; then
  die "The tag v$version exists already"
fi
echo "==> Releasing $version"

# Until the push succeeds, a failure or Ctrl-C puts everything back
start=$(git rev-parse HEAD)
rollback() {
  echo "==> Nothing was pushed: putting everything back" >&2
  git tag --delete "v$version" >/dev/null 2>&1 || true
  git reset --quiet --soft "$start"
  git restore --source="$start" --staged --worktree -- pyproject.toml uv.lock CHANGELOG.md
}
trap rollback EXIT
uv version --bump "$1" --no-sync --quiet
sed -i "s/^## Unreleased$/## $version - $(date +%F)/" CHANGELOG.md
git commit --quiet --gpg-sign --message "$version" --message "$(notes "$version")" \
  -- pyproject.toml uv.lock CHANGELOG.md
git tag --sign --message "nejomibot $version" "v$version"
git push --quiet --atomic origin main "v$version"
trap - EXIT

publish "$version"
