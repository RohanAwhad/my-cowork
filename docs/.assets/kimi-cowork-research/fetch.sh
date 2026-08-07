#!/bin/bash
# fetch raw files from MoonshotAI/kimi-code main branch
REPO="MoonshotAI/kimi-code"
BR="main"
OUT="/tmp/opencode/deepresearch/cowork_re-A7X2/src"
mkdir -p "$OUT"
for f in "$@"; do
  mkdir -p "$OUT/$(dirname "$f")"
  curl -s "https://raw.githubusercontent.com/$REPO/$BR/$f" -o "$OUT/$f"
done
