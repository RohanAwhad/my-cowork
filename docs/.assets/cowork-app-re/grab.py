import sys

path = "/tmp/claude-asar/app/.vite/build/index.js"
pat = sys.argv[1]
before = int(sys.argv[2]) if len(sys.argv) > 2 else 200
after = int(sys.argv[3]) if len(sys.argv) > 3 else 600

with open(path, "r", errors="replace") as f:
    data = f.read()

import re
idxs = [m.start() for m in re.finditer(re.escape(pat), data)]
print(f"=== {len(idxs)} occurrences of {pat!r} ===")
for i, idx in enumerate(idxs[:12]):
    print(f"\n----- occurrence {i+1} @ byte {idx} -----")
    print(data[max(0,idx-before):idx+after])
