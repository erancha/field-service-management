#!/usr/bin/env bash
#
# Tag the next release and push the tag; the release job of .github/workflows/ci.yml publishes it
# as a GitHub Release once both test jobs pass on the tagged commit.
#
#   ./scripts/tools/release.sh            # the next patch version (v1.2.3 -> v1.2.4)
#   ./scripts/tools/release.sh --minor    # the next minor version (v1.2.3 -> v1.3.0)
#   ./scripts/tools/release.sh --major    # the next major version (v1.2.3 -> v2.0.0)
#   -h, --help                            show this help
#
# The first release is v1.0.0 (v1.1.0 with --minor, v2.0.0 with --major). A tag whose push fails
# is deleted again, so a retry can take the same name.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../common.sh
source "$SCRIPT_DIR/common.sh"

bump="${1:-}"
case "$bump" in
  ""|--minor|--major) ;;
  -h|--help) print_help; exit 0 ;;
  *) print_help >&2; exit 2 ;;
esac
cd "$ROOT"

# The v* tags on origin are the single source of released versions, so the newest one is the build
# counter. Reading from origin (not local tags) means an un-fetched clone still sees the true
# latest. --refs drops the peeled ^{} lines annotated tags emit; sort -V orders numerically so
# tail picks the real latest regardless of push order. Empty until the first release.
last=$(git ls-remote --tags --refs origin 'v*' | sed -E 's#.*/##' | sort -V | tail -n1)

if [ -n "$last" ]; then
    IFS=. read -r major minor patch <<<"${last#v}"
    case "$bump" in
        "")      patch=$((patch + 1)) ;;
        --minor) minor=$((minor + 1)); patch=0 ;;
        --major) major=$((major + 1)); minor=0; patch=0 ;;
    esac
else
    # First release seeds at 1.0.0 rather than incrementing a non-existent value.
    case "$bump" in
        "")      major=1; minor=0; patch=0 ;;
        --minor) major=1; minor=1; patch=0 ;;
        --major) major=2; minor=0; patch=0 ;;
    esac
fi

version="$major.$minor.$patch"
tag="v$version"
echo "→ next version: $version (last: ${last:-none})"

git tag -a "$tag" -m "$tag"
if ! git push origin "$tag"; then
    # Drop the local tag so the burned name does not block a retry after a failed push.
    git tag -d "$tag" >/dev/null
    echo "push failed; removed local tag $tag" >&2
    exit 1
fi
echo "→ released $tag"
