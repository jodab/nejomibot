#!/usr/bin/env bash
# build-image.sh - test nejomibot and build its container image, for x86 and ARM.
#
# Usage: tools/build-image.sh [--platforms LIST] [--source URL] [--push DESTINATION]
#
# Runs the tests, lint and type check in the image's test stage, and stops if
# they fail. Then builds the image for linux/amd64 and linux/arm64, the one
# that isn't this machine's through QEMU emulation, which takes a few minutes.
# The result is the manifest list localhost/nejomibot:VERSION, VERSION from
# pyproject.toml, also tagged localhost/nejomibot:latest.
#
# With --platforms, it builds those instead, a comma-separated list such as
# linux/amd64: CI builds only that, and leaves arm64 to the release.
#
# With --source, the image says where its source is, the repository's URL,
# such as https://github.com/someone/nejomibot (the label
# org.opencontainers.image.source, by which GitHub's registry links an image
# to its repository), and which commit it was built from.
#
# With --push, it then pushes what it built to DESTINATION, a registry
# and name such as ghcr.io/someone/nejomibot, as :VERSION and :latest.
#
# Needs podman, and for the other architecture QEMU's binfmt handlers, from
# qemu-user-static (Debian, Arch) or qemu-user-static-binfmt.

set -euo pipefail

IMAGE=localhost/nejomibot
platforms=linux/amd64,linux/arm64

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# build WHAT ARGS...: podman build ARGS, quiet unless it fails: then the end
# of its output, which names the failed tests.
build() {
  local what=$1 output
  shift
  if ! output=$(podman build "$@" . 2>&1); then
    printf '%s\n' "$output" | tail -n 60 >&2
    die "$what failed"
  fi
}

cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.."
destination=""
labels=()
while (($#)); do
  case $1 in
    --push)
      (($# > 1)) || die "--push needs a destination, like ghcr.io/someone/nejomibot"
      destination=${2#docker://}
      shift
      ;;
    --platforms)
      (($# > 1)) || die "--platforms needs a list, like linux/amd64,linux/arm64"
      platforms=$2
      shift
      ;;
    --source)
      (($# > 1)) || die "--source needs the repository's URL"
      labels=(--label "org.opencontainers.image.source=$2"
        --label "org.opencontainers.image.revision=$(git rev-parse HEAD)")
      shift
      ;;
    -h | --help)
      sed -n '2,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
  shift
done

version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
[[ -n $version ]] || die "No version in pyproject.toml"

echo "==> Running the tests, lint and type check"
build "The tests" --target test --tag "$IMAGE:test"

echo "==> Building $IMAGE:$version for $platforms"
# A manifest list gathers every image built into it, so start anew
podman manifest rm "$IMAGE:$version" "$IMAGE:latest" >/dev/null 2>&1 || true
# Docker's format, as OCI's has no HEALTHCHECK
build "The build" --platform "$platforms" --build-arg "VERSION=$version" \
  "${labels[@]}" --format docker --manifest "$IMAGE:$version"
podman tag "$IMAGE:$version" "$IMAGE:latest"

if [[ -n $destination ]]; then
  for tag in "$version" latest; do
    echo "==> Pushing to $destination:$tag"
    podman manifest push --all "$IMAGE:$version" "docker://$destination:$tag"
  done
fi
echo "==> Built $IMAGE:$version, also :latest"
