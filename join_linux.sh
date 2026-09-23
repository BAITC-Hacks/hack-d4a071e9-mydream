#!/usr/bin/env bash
cd "$(dirname "$0")"
for f in moneygraph-linux-x64.tar.gz moneygraph-win-x64.zip; do
  ls "$f".part* >/dev/null 2>&1 && cat "$f".part* > "$f"
done
sha256sum -c --ignore-missing SHA256SUMS 2>/dev/null || shasum -a 256 -c --ignore-missing SHA256SUMS
