#!/bin/sh
# Dataset: "Ghost Data Still Exists", from the HackerRank Orchestrate (October 2026) problem statement,
# https://github.com/interviewstreet/hackerrank-orchestrate-october26 (fetched as published, not redistributed here).
set -eu

REPO_URL="${GHOST_DATASET_REPO:-https://github.com/interviewstreet/hackerrank-orchestrate-october26}"
REF="${GHOST_DATASET_REF:-main}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/dataset"

if [ -e "$DEST/deletion_requests.csv" ] && [ "${1:-}" != "--force" ]; then
    echo "dataset/ already present at $DEST (pass --force to fetch again)"
    exit 0
fi

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t ghostdata)
trap 'rm -rf "$TMP"' EXIT INT TERM

if command -v git >/dev/null 2>&1; then
    git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$TMP/src"
elif command -v curl >/dev/null 2>&1; then
    curl -fsSL "$REPO_URL/archive/refs/heads/$REF.tar.gz" | tar -xzf - -C "$TMP"
    mv "$TMP"/*-"$REF" "$TMP/src"
else
    echo "need git or curl to fetch the dataset" >&2
    exit 1
fi

if [ ! -f "$TMP/src/dataset/deletion_requests.csv" ]; then
    echo "no dataset/ folder found in $REPO_URL@$REF" >&2
    exit 1
fi

rm -rf "$DEST"
cp -R "$TMP/src/dataset" "$DEST"
echo "dataset/ copied to $DEST from $REPO_URL@$REF"
echo "Source and attribution: HackerRank Orchestrate (October 2026), $REPO_URL"
