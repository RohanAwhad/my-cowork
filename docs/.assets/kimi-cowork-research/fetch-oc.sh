#!/bin/bash
# fetch raw files from openclaw/openclaw main branch
REPO="openclaw/openclaw"
BR="main"
OUT="/tmp/opencode/deepresearch/cowork_re-A7X2/oc/src"
mkdir -p "$OUT"
for f in "$@"; do
  mkdir -p "$OUT/$(dirname "$f")"
  curl -s "https://raw.githubusercontent.com/$REPO/$BR/$f" -o "$OUT/$f"
done
